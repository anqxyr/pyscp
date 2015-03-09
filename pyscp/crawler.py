#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import concurrent.futures
import itertools
import logging
import re
import requests

from bs4 import BeautifulSoup as bs4
from cached_property import cached_property
from collections import namedtuple
from peewee import OperationalError
from pyscp import orm
from urllib.parse import urlparse, urlunparse, urljoin

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('scp.crawler')
log.setLevel(logging.DEBUG)

###############################################################################
# Utility Classes
###############################################################################


class InsistentRequest(requests.Session):

    """Make an auto-retrying request that handles connection loss."""

    def __init__(self, retry_count=5):
        super().__init__()
        self.retry_count = retry_count

    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 30)
        kwargs['allow_redirects'] = False
        for _ in range(self.retry_count):
            try:
                resp = super().request(method=method, url=url, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                continue
            if 200 <= resp.status_code < 300:
                return resp
            elif 300 <= resp.status_code < 400:
                raise requests.HTTPError(
                    'Redirect attempted with url: {}'.format(url))
            elif 400 <= resp.status_code < 600:
                continue
        raise requests.ConnectionError(
            'Max retries exceeded with url: {}'.format(url))

###############################################################################
# Public Classes
###############################################################################


class WikidotConnector:

    """
    Provide a low-level interface to a Wikidot site.

    This class does not use any of the official Wikidot API, and instead
    relies on sending http post/get requests to internal Wikidot pages and
    parsing the returned data.
    """

    def __init__(self, site):
        parsed = urlparse(site)
        netloc = parsed.netloc or parsed.path
        if '.' not in netloc:
            netloc += '.wikidot.com'
        self.site = urlunparse(['http', netloc, '', '', '', ''])
        self.req = InsistentRequest()

    def __call__(self, url):
        if 'scp-wiki' in self.site:
            return SCPWikiPage(url, self)
        else:
            return Page(url, self)

    def __repr__(self):
        short = urlparse(self.site).netloc.replace('.wikidot.com', '')
        cls_name = self.__class__.__name__
        return "{}('{}')".format(cls_name, short)

    ###########################################################################
    # Connector Page API
    ###########################################################################

    def _pageid(self, page):
        pageid = re.search('pageId = ([^;]*);', page.html)
        return pageid.group(1) if pageid is not None else None

    def _thread_id(self, page):
        try:
            return re.search(
                r'/forum/t-([0-9]+)/',
                bs4(page.html).select('#discuss-button')[0]['href']
            ).group(1)
        except (IndexError, AttributeError):
            return None

    def _html(self, page):
        """Download the html data of the page."""
        log.debug('Downloading page html: {}'.format(page.url))
        try:
            return self.req.get(page.url).text
        except (requests.ConnectionError, requests.HTTPError) as err:
            log.warning('Failed to get the page: {}'.format(err))

    def _source(self, page):
        """Download page source."""
        if page._pageid is None:
            return None
        data = self._module(name='viewsource/ViewSourceModule',
                            pageid=page._pageid)['body']
        return bs4(data).text[11:].strip()

    def _history(self, page):
        """Download the revision history of the page."""
        if page._pageid is None:
            return None
        data = self._module(
            name='history/PageRevisionListModule',
            pageid=page._pageid, page=1, perpage=1000000)['body']
        for elem in bs4(data)('tr')[1:]:
            time = arrow.get(elem('td')[5].span['class'][1].split('_')[1])
            yield {
                'id': int(elem['id'].split('-')[-1]),
                'number': int(elem('td')[0].text.strip('.')),
                'user': elem('td')[4].text,
                'time': time.format('YYYY-MM-DD HH:mm:ss'),
                'comment': elem('td')[6].text}

    def _votes(self, page):
        """Download the vote data."""
        if page._pageid is None:
            return None
        data = self._module(name='pagerate/WhoRatedPageModule',
                            pageid=page._pageid)['body']
        spans = iter(bs4(data)('span'))
        # exploits statefullness of iterators
        for user, value in zip(spans, spans):
            yield {
                'user': user.text,
                'value': 1 if value.text.strip() == '+' else -1}

    def _tags(self, page):
        return [a.string for a in bs4(page.html).select('div.page-tags a')]

    ###########################################################################

    def _edit(self, page, source, title, comment):
        """
        Overwrite the page with the new source and title.

        'pageid' and 'url' must belong to the same page.
        'comments' is the optional edit message that will be displayed in
        the page's revision history.
        """
        lock = self._module('edit/PageEditModule', page._pageid, mode='page')
        params = {
            'source': source,
            'comments': comment,
            'title': title,
            'lock_id': lock['lock_id'],
            'lock_secret': lock['lock_secret'],
            'revision_id': lock['page_revision_id'],
            'action': 'WikiPageAction',
            'event': 'savePage',
            'wiki_page': page._url.split('/')[-1]}
        self._module('Empty', page._pageid, **params)

    def _revert_to(self, page, rev_n):
        params = {
            'revisionId': page.history[rev_n].id,
            'action': 'WikiPageAction',
            'event': 'revert'}
        self._module('Empty', page._pageid, **params)

    def _set_tags(self, page, tags):
        """Replace the tags of the page."""
        params = {
            'tags': ' '.join(tags),
            'action': 'WikiPageAction',
            'event': 'saveTags'}
        self._module('Empty', page._pageid, **params)

    ###########################################################################
    # Connector ForumThread API
    ###########################################################################

    def _thread(self, thread_id):
        """Download and parse the contents of the forum thread."""
        if thread_id is None:
            return
        first_page = self._module(
            name='forum/ForumViewThreadModule', t=thread_id)['body']
        soup = bs4(first_page)
        crumbs = soup.find('div', 'forum-breadcrumbs')
        category = int(crumbs('a')[1]['href'].split('/')[2].split('-')[1])
        title = crumbs.contents[-1].string.strip().lstrip('» ')
        description = ' '.join(
            i.string.strip() for i in soup.find('div', 'well').contents[2:])
        yield (title, description, category)
        yield from self._parse_thread(first_page)
        try:
            counter = bs4(first_page).find('span', 'pager-no').text
        except AttributeError:
            return
        for index in range(2, int(counter.split(' ')[-1]) + 1):
            page = self._module(name='forum/ForumViewThreadPostsModule',
                                pageNo=index, t=thread_id)['body']
            yield from self._parse_thread(page)

    def _reply(self, thread_id, parent, source, title):
        """Make a new post in the given thread."""
        params = {
            'threadId': thread_id,
            'parentId': parent,
            'title': title,
            'source': source,
            'action': 'ForumAction',
            'event': 'savePost'}
        self._module('Empty', None, **params)

    ###########################################################################
    # Connector Public API
    ###########################################################################

    def auth(self, username, password):
        """Login to wikidot with the given username/password pair."""
        data = {'login': username,
                'password': password,
                'action': 'Login2Action',
                'event': 'login'}
        self.req.post(
            'https://www.wikidot.com/default--flow/login__LoginPopupScreen',
            data=data)

    def list_pages(self, **kwargs):
        """Yield urls of the pages matching the specified criteria."""
        for page in self._pager(
                'list/ListPagesModule',
                _next=lambda x: {'offset': 250 * (x - 1)},
                category='*',
                tags=kwargs.get('tag', None),
                created_by=kwargs.get('author', None),
                order='title',
                module_body='%%title_linked%%',
                perPage=250):
            for elem in bs4(page['body']).select('div.list-pages-item a'):
                yield self.site + elem['href']

    def recent_changes(self, num):
        """Return the last 'num' revisions on the site."""
        data = self._module(
            name='changes/SiteChangesListModule', pageid=None,
            options={'all': True}, page=1, perpage=num)['body']
        for elem in bs4(data)('div', 'changes-list-item'):
            revnum = elem.find('td', 'revision-no').text.strip()
            time = elem.find('span', 'odate')['class'][1].split('_')[1]
            comment = elem.find('div', 'comments')
            yield {
                'url': self.site + elem.find('td', 'title').a['href'],
                'number': 0 if revnum == '(new)' else int(revnum[6:-1]),
                'user': elem.find('span', 'printuser').text.strip(),
                'time': arrow.get(time).format('YYYY-MM-DD HH:mm:ss'),
                'comment': comment.text.strip() if comment else None}

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _module(self, name, **kwargs):
        """
        Call a Wikidot module.

        This method is responsible for most of the class' functionality.
        Almost all other methods of the class are using _module in one way
        or another.
        """
        log.debug('_module call: {} {}'.format(name, kwargs))
        pageid = kwargs.get('pageid', None)
        payload = {
            'page_id': pageid,
            'pageId': pageid,  # fuck wikidot
            'moduleName': name,
            # token7 can be any 6-digit number, as long as it's the same
            # in the payload and in the cookie
            'wikidot_token7': '123456'}
        payload.update(kwargs)
        try:
            return self.req.post(
                self.site + '/ajax-module-connector.php',
                data=payload,
                headers={'Content-Type': 'application/x-www-form-urlencoded;'},
                cookies={'wikidot_token7': '123456'}).json()
        except (requests.ConnectionError, requests.HTTPError) as err:
            log.warning('Failed module call ({} - {} - {}): {}'
                        .format(name, pageid, kwargs, err))

    def _parse_thread(self, html):
        for elem in bs4(html)('div', 'post'):
            granpa = elem.parent.parent
            if 'post-container' in granpa.get('class', ''):
                parent = granpa.find(class_='post')['id'].split('-')[1]
            else:
                parent = None
            time = arrow.get(
                elem.find(class_='odate')['class'][1].split('_')[1])
            title = elem.find(class_='title').text.strip()
            yield {
                'post_id': elem['id'].split('-')[1],
                'title': title if title else None,
                'content': elem.find(class_='content'),
                'user': elem.find(class_='printuser').text,
                'time': time.format('YYYY-MM-DD HH:mm:ss'),
                'parent': parent}

    def _pager(self, name, _next, **kwargs):
        """Iterate over multi-page module results."""
        first_page = self._module(name, **kwargs)
        yield first_page
        try:
            counter = bs4(first_page['body']).select('span.pager-no')[0].text
        except IndexError:
            return
        for page in range(2, int(counter.split(' ')[-1]) + 1):
            kwargs.update(_next(page))
            yield self._module(name, **kwargs)

    ###########################

    def list_categories(self):
        """Yield dicts describing all forum categories on the site."""
        soup = bs4(self._module('forum/ForumStartModule')['body'])
        for i in soup.select('td.name'):
            yield {
                'category_id': re.search(
                    r'/forum/c-([0-9]+)/',
                    i.select('div.title')[0].a['href']).group(1),
                'title': i.select('div.title')[0].text.strip(),
                'threads': int(i.parent.select('td.threads')[0].text),
                'description': i.select('div.description')[0].text.strip()}

    def list_threads(self, category_id):
        """Yield dicts describing all threads in a given category."""
        for page in self._pager(
                'forum/ForumViewCategoryModule',
                _next=lambda x: {'p': x},
                c=category_id):
            for i in bs4(page['body']).select('td.name'):
                yield {
                    'thread_id': re.search(
                        r'/forum/t-([0-9]+)',
                        i.select('div.title')[0].a['href']).group(1),
                    'title': i.select('div.title')[0].text.strip(),
                    'description': i.select('div.description')[0].text.strip(),
                    'category_id': category_id}


class Snapshot:

    """
    Create and manipulate a snapshot of a wikidot site.

    This class uses WikidotConnector to iterate over all the pages of a site,
    and save the html content, revision history, votes, and the discussion
    of each to a sqlite database. Optionally, standalone forum threads can be
    saved too.

    In case of the scp-wiki, some additional information is saved:
    images for which their CC status has been confirmed, and info about
    overwriting page authorship.

    In general, this class will not save images hosted on the site that is
    being saved. Only the html content, discussions, and revision/vote
    metadata is saved.
    """

    def __init__(self, dbpath):
        self.dbpath = dbpath
        orm.connect(self.dbpath)
        try:
            first_url = orm.Page.select(orm.Page.url).first().url
            netloc = urlparse(first_url).netloc
            self.site = urlunparse(['http', netloc, '', '', '', ''])
        except (AttributeError, OperationalError):
            self.site = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=20)

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _scrape_images(self):
        #TODO: rewrite this to get images from the review pages
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        req = InsistentRequest()
        data = []
        for i in bs4(req.get(url).text).select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            try:
                image_data = req.get(image_url).content
            except requests.HTTPError as err:
                log.warning('Image not saved: {}'.format(err))
            data.append({
                "url": image_url,
                "source": image_source,
                "data": image_data})
        return data

    def _save_page(self, url):
        """Download the page and write it to the db."""
        log.info('Saving page: {}'.format(url))
        html = self.wiki.get_page_html(url)
        if html is None:
            return
        pageid, thread_id = _parse_html_for_ids(html)
        soup = bs4(html)
        html = str(soup.select('#main-content')[0])  # cut off side-bar, etc.
        orm.Page.create(
            pageid=pageid, url=url, html=html, thread_id=thread_id)
        orm.Revision.insert_many(self.wiki.get_page_history(pageid))
        orm.Vote.insert_many(self.wiki.get_page_votes(pageid))
        orm.ForumPost.insert_many(self.wiki.get_forum_thread(thread_id))
        orm.Tag.insert_many(
            {'tag': a.string, 'url': url} for a in
            bs4(html).select('div.page-tags a'))

    def _save_forums(self):
        """Download and save standalone forum threads."""
        orm.ForumThread.create_table()
        orm.ForumCategory.create_table()
        categories = [
            i for i in self.wiki.list_categories()
            if i['title'] != 'Per page discussions']
        total = sum([i['threads'] for i in categories])
        index = itertools.count(1)
        futures = []
        _save = lambda x: (orm.ForumPost.insert_many(
            self.wiki.get_forum_thread(x['thread_id'])))
        for category in categories:
            orm.ForumCategory.create(**category)
            for thread in self.wiki.list_threads(category['category_id']):
                orm.ForumThread.create(**thread)
                log.info(
                    'Saving forum thread #{}/{}: {}'
                    .format(next(index), total, thread['title']))
                futures.append(self.pool.submit(_save, thread))
        return futures

    ###########################################################################
    # Page Interface
    ###########################################################################

    def get_page_html(self, url):
        try:
            return orm.Page.get(orm.Page.url == url).html
        except orm.Page.DoesNotExist:
            return None

    def get_pageid(self, url):
        try:
            return orm.Page.get(orm.Page.url == url).pageid
        except orm.Page.DoesNotExist:
            return None

    def get_thread_id(self, url):
        return orm.Page.get(orm.Page.url == url).thread_id

    def get_page_history(self, pageid):
        query = (orm.Revision.select()
                 .where(orm.Revision.pageid == pageid)
                 .order_by(orm.Revision.number))
        history = []
        for i in query:
            history.append({
                'pageid': pageid,
                'number': i.number,
                'user': i.user,
                'time': i.time,
                'comment': i.comment})
        return history

    def get_page_votes(self, pageid):
        for i in orm.Vote.select().where(orm.Vote.pageid == pageid):
            yield {a: getattr(i, a) for a in ('pageid', 'user', 'value')}

    def get_page_tags(self, url):
        query = orm.Tag.select().where(orm.Tag.url == url)
        tags = []
        for tag in query:
            tags.append(tag.tag)
        return tags

    def get_forum_thread(self, thread_id):
        query = (orm.ForumPost.select()
                 .where(orm.ForumPost.thread_id == thread_id)
                 .order_by(orm.ForumPost.post_id))
        posts = []
        for i in query:
            posts.append({
                'thread_id': thread_id,
                'post_id': i.post_id,
                'title': i.title,
                'content': i.content,
                'user': i.user,
                'time': i.time,
                'parent': i.parent})
        return posts

    ###########################################################################
    # Public Methods
    ###########################################################################

    def take(self, site, include_forums=False):
        self.wiki = WikidotConnector(site)
        time_start = arrow.now()
        orm.purge()
        for i in [
                orm.Page, orm.Revision, orm.Vote,
                orm.ForumPost, orm.Tag]:
            i.create_table()
        ftrs = [self.pool.submit(self._save_page, i)
                for i in self.wiki.list_pages()]
        concurrent.futures.wait(ftrs)
        if include_forums:
            ftrs = self._save_forums()
            concurrent.futures.wait(ftrs)
        if self.wiki.site == 'http://www.scp-wiki.net':
            orm.Image.create_table()
            log.info('Downloading image metadata.')
            orm.Image.insert_many(self._scrape_images())
            orm.Author.create_table()
            log.info('Downloading author metadata.')
            orm.Author.insert_many(_get_rewrite_list())
        orm.queue.join()
        time_taken = (arrow.now() - time_start)
        hours, remainder = divmod(time_taken.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = 'Snapshot succesfully taken. [{:02d}:{:02d}:{:02d}]'
        msg = msg.format(hours, minutes, seconds)
        log.info(msg)

    def get_rewrite_list(self):
        for au in orm.Author.select():
            yield {i: getattr(au, i) for i in ('url', 'author', 'override')}

    def get_image_metadata(self, url):
        try:
            img = orm.Image.get(orm.Image.url == url)
            return {'url': img.url, 'source': img.source, 'data': img.data}
        except orm.Image.DoesNotExist:
            return None

    def list_pages(self, **kwargs):
        query = orm.Page.select(orm.Page.url)
        tag = kwargs.get('tag', None)
        if tag:
            with_tag = orm.Tag.select(orm.Tag.url).where(orm.Tag.tag == tag)
            query = query.where(orm.Page.url << with_tag)
        author = kwargs.get('author', None)
        if author:
            created_pages = (
                orm.Revision.select(orm.Revision.pageid)
                .where(orm.Revision.user == author)
                .where(orm.Revision.number == 0))
            rewrite_list = list(self.get_rewrite_list())
            exclude_pages = [
                i['url'] for i in rewrite_list
                if i['author'] != author and i['override']]
            include_pages = [
                i['url'] for i in rewrite_list
                if i['author'] == author]
            query = query.where((
                (orm.Page.pageid << created_pages) |
                (orm.Page.url << include_pages)) &
                ~(orm.Page.url << exclude_pages))
        for i in query.order_by(orm.Page.url):
            yield i.url


class Page:

    """ """

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url, connector):
        if url is not None and not urlparse(url).netloc:
            url = urljoin(connector.site, url)
        self.url = url.lower()
        self._cn = connector

    def __repr__(self):
        short = self.url.replace(self._cn.site, '').lstrip('/')
        cls_name = self.__class__.__name__
        return "{}('{}', {})".format(cls_name, short, repr(self._cn))

    ###########################################################################
    # Core Properties
    ###########################################################################

    @cached_property
    def _pageid(self):
        return self._cn._pageid(self)

    @cached_property
    def _thread_id(self):
        return self._cn._thread_id(self)

    @cached_property
    def html(self):
        return self._cn._html(self)

    @cached_property
    def source(self):
        return self._cn._source(self)

    @cached_property
    def history(self):
        data = self._cn._history(self)
        attrs = 'id number user time comment'
        Revision = namedtuple('Revision', attrs)
        history = [Revision(*[i[a] for a in attrs.split()]) for i in data]
        return list(sorted(history, key=lambda x: x.number))

    @cached_property
    def votes(self):
        data = self._cn._votes(self)
        Vote = namedtuple('Vote', 'user value')
        return [Vote(i['user'], i['value']) for i in data]

    @cached_property
    def tags(self):
        return self._cn._tags(self)

    @cached_property
    def comments(self):
        return ForumThread(self._thread_id, self._cn)

    ###########################################################################
    # Derived Properties
    ###########################################################################

    @property
    def text(self):
        return bs4(self.html).select('#page-content')[0].text

    @property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    @property
    def images(self):
        return [i['src'] for i in bs4(self.html).select('img')]

    @property
    def title(self):
        elems = bs4(self.html).select('#page-title')
        return elems[0].text.strip() if elems else ''

    @property
    def created(self):
        return self.history[0].time

    @property
    def author(self):
        return self.history[0].user

    @property
    def rating(self):
        if not self.votes:
            return None
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

    @property
    def links(self):
        if self.html is None:
            return []
        links = set()
        for a in bs4(self.html).select('#page-content a'):
            if (('href' not in a.attrs) or
                (a['href'][0] != '/') or
                    (a['href'][-4:] in ['.png', '.jpg', '.gif'])):
                continue
            url = 'http://www.scp-wiki.net{}'.format(a['href'])
            url = url.rstrip("|")
            links.add(url)
        return list(links)

    ###########################################################################
    # Methods
    ###########################################################################

    def edit(self, source, title=None, comment=None):
        if title is None:
            title = self.title
        self._cn._edit(self, source, title, comment)
        del self._cache

    def revert_to(self, rev_n):
        self._cn._revert_to(self, rev_n)
        del self._cache

    def set_tags(self, tags):
        self._cn._set_tags(self, tags)
        del self._cache


class ForumThread:

    def __init__(self, thread_id, connector):
        self._id = thread_id
        self._cn = connector
        gen = connector._thread(thread_id)
        self.title, self.description, self.category = next(gen)
        self._data = [ForumPost(self, **i) for i in gen]

    def __repr__(self):
        cls_name = self.__class__.__name__
        return '{}({}, {})'.format(cls_name, self._id, repr(self._cn))

    def __getitem__(self, index):
        return self._data[index]

    def __len__(self):
        return len(self._data)

    def reply(self, content, title=None):
        self._cn._reply(self._id, None, content, title)
        del self._cache


class ForumPost:

    def __init__(self, thread, **data):
        self._id = data['post_id']
        self.title = data['title']
        self.user = data['user']
        self.time = data['time']
        self.content = data['content']
        self._thread = thread

    def __repr__(self):
        cls_name = self.__class__.__name__
        return('<{}({})>'.format(cls_name, self._id))

    def __str__(self):
        prefix = '{}|{}'.format(self._id, self.user)
        snip = 64 - len(prefix)
        trun = self.text.replace('\n', ' ').strip()
        trun = trun[:snip] + '…' if len(trun) > snip else trun
        return '<{}: {}>'.format(prefix, trun)

    @property
    def text(self):
        return self.content.text

    @property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    def reply(self, content, title=None):
        self._thread._cn(self._thread._id, self._id, content, title)


class SCPWikiPage(Page):
    pass

###############################################################################
# Module-level Functions
###############################################################################


def use_default_logging(debug=False):
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('scp').addHandler(console)
    logfile = logging.FileHandler('scp.log', mode='w', delay=True)
    logfile.setLevel(logging.WARNING)
    logfile.setFormatter(logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'))
    logging.getLogger('scp').addHandler(logfile)
