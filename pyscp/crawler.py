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
        log_message = '<{} request>: {}'.format(method, url)
        if kwargs:
            log_message += ' {}'.format(kwargs)
        log.debug(log_message)
        kwargs.setdefault('timeout', 30)
        kwargs.setdefault('allow_redirects', False)
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

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


###############################################################################
# Public Classes
###############################################################################


class ConnectorError(Exception):
    pass


class WikidotConnector:

    """
    Provide a low-level interface to a Wikidot site.

    This class does not use any of the official Wikidot API, and instead
    relies on sending http post/get requests to internal Wikidot pages and
    parsing the returned data.
    """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site):
        parsed = urlparse(site)
        netloc = parsed.netloc or parsed.path
        if '.' not in netloc:
            netloc += '.wikidot.com'
        self.site = urlunparse(['http', netloc, '', '', '', ''])
        self.req = InsistentRequest()

    def __call__(self, url):
        # if something needs to use a child class of Page here instead
        # they can just override the whole __call__ method
        return Page(url, self)

    def __repr__(self):
        return "{}('{}')".format(
            self.__class__.__name__,
            urlparse(self.site).netloc.replace('.wikidot.com', ''))

    ###########################################################################
    # Connector Page API
    ###########################################################################

    def _page_id(self, url, html):
        pageid = re.search('pageId = ([^;]*);', html)
        return pageid.group(1) if pageid is not None else None

    def _thread_id(self, page_id, html):
        link = bs4(html).find(id='discuss-button')
        return link['href'].split('/')[2].split('-')[1] if link else None

    def _html(self, url):
        """Download the html data of the page."""
        try:
            return self.req.get(url).text
        except (requests.ConnectionError, requests.HTTPError) as err:
            log.warning('Failed to get the page: {}'.format(err))
            return None

    def _source(self, page_id):
        """Download page source."""
        if page_id is None:
            return None
        data = self._module('viewsource/ViewSourceModule',
                            page_id=page_id)['body']
        return bs4(data).text[11:].strip()

    def _history(self, page_id):
        """Download the revision history of the page."""
        if page_id is None:
            return None
        data = self._module('history/PageRevisionListModule',
                            page_id=page_id, page=1, perpage=1000000)['body']
        for elem in bs4(data)('tr')[1:]:
            time = elem('td')[5].span['class'][1].split('_')[1]
            yield dict(
                revision_id=int(elem['id'].split('-')[-1]),
                page_id=page_id,
                number=int(elem('td')[0].text.strip('.')),
                user=elem('td')[4].text,
                time=arrow.get(time).format('YYYY-MM-DD HH:mm:ss'),
                comment=elem('td')[6].text)

    def _votes(self, page_id):
        """Download the vote data."""
        if page_id is None:
            return None
        data = self._module('pagerate/WhoRatedPageModule',
                            page_id=page_id)['body']
        spans = iter(bs4(data)('span'))
        # exploits statefullness of iterators
        for user, value in zip(spans, spans):
            yield dict(
                page_id=page_id,
                user=user.text,
                value=1 if value.text.strip() == '+' else -1)

    def _tags(self, page_id, html):
        for elem in bs4(html).select('div.page-tags a'):
            yield elem.text

    ###########################################################################

    def _edit(self, page_id, url, source, title, comment):
        """Overwrite the page with the new source and title."""
        lock = self._module('edit/PageEditModule',
                            page_id=page_id, mode='page')
        return self._page_action(
            page_id, 'savePage',
            source=source, title=title, comments=comment,
            wiki_page=url.split('/')[-1],
            lock_id=lock['lock_id'],
            lock_secret=lock['lock_secret'],
            revision_id=lock['page_revision_id'])

    def _revert_to(self, page_id, revision_id):
        return self._page_action(page_id, 'revert', revisionId=revision_id)

    def _set_tags(self, page_id, tags):
        """Replace the tags of the page."""
        return self._page_action(page_id, 'saveTags', tags=' '.join(tags))

    def _set_vote(self, page_id, value, force=False):
        return self._module('Empty',
                            page_id=page_id,
                            action='RateAction',
                            event='ratePage' if value else 'cancelVote',
                            points=value,
                            force='yes' if force else '')

    ###########################################################################

    def _posts(self, thread_id):
        """Download and parse the contents of the forum thread."""
        if thread_id is None:
            return
        for page in self._pager('forum/ForumViewThreadPostsModule',
                                lambda x: {'pageNo': x}, t=thread_id):
            for post in self._parse_thread(page['body']):
                post.update(thread_id=thread_id)
                yield post

    def reply_to(self, thread_id, post_id, source, title):
        """Make a new post in the given thread."""
        return self._module('Empty',
                            threadId=thread_id,
                            parentId=post_id,
                            title=title,
                            source=source,
                            action='ForumAction',
                            event='savePost')

    ###########################################################################
    # Connector Public API
    ###########################################################################

    def auth(self, username, password):
        """Login to wikidot with the given username/password pair."""
        data = {'login': username,
                'password': password,
                'action': 'Login2Action',
                'event': 'login'}
        return self.req.post(
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

    def categories(self):
        """Yield dicts describing all forum categories on the site."""
        for elem in (
                bs4(self._module('forum/ForumStartModule')['body'])
                (class_='name')):
            yield int(
                elem.find(class_='title').a['href']
                .split('/')[2].split('-')[1])
            yield dict(
                category_id=int(elem.find(class_='title').a['href']
                                .split('/')[2].split('-')[1]),
                title=elem.select('div.title')[0].text.strip(),
                threads=int(elem.parent.select('td.threads')[0].text),
                description=elem.select('div.description')[0].text.strip())

    def threads(self, category_id):
        """Yield dicts describing all threads in a given category."""
        for page in self._pager('forum/ForumViewCategoryModule',
                                lambda x: {'p': x}, c=category_id):
            for elem in bs4(page['body'])(class_='name'):
                yield dict(
                    thread_id=int(
                        elem.find(class_='title').a['href']
                        .split('/')[2].split('-')[1]),
                    title=elem.select('div.title')[0].text.strip(),
                    description=elem.select('div.description')[0].text.strip(),
                    category_id=category_id)

    def recent_changes(self, number):
        """Return the last 'num' revisions on the site."""
        data = self._module(
            name='changes/SiteChangesListModule',
            options={'all': True}, page=1, perpage=number)['body']
        for elem in bs4(data)('div', 'changes-list-item'):
            revnum = elem.find('td', 'revision-no').text.strip()
            time = elem.find('span', 'odate')['class'][1].split('_')[1]
            comment = elem.find('div', 'comments')
            yield dict(
                url=self.site + elem.find('td', 'title').a['href'],
                number=0 if revnum == '(new)' else int(revnum[6:-1]),
                user=elem.find('span', 'printuser').text.strip(),
                time=arrow.get(time).format('YYYY-MM-DD HH:mm:ss'),
                comment=comment.text.strip() if comment else None)

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    def rewrites(self):
        if 'scp-wiki' not in self.site:
            return None
        for elem in bs4(self._html(
                'http://05command.wikidot.com/alexandra-rewrite'))('tr')[1:]:
            # possibly add other options here, like collaborator
            if ':override:' in elem('td')[1].text:
                status = 'override'
            else:
                status = 'rewrite'
            yield dict(
                url=urljoin(self.site, elem('td')[0].text),
                author=elem('td')[1].text.split(':override:')[-1],
                status=status)

    def images(self):
        if 'scp-wiki' not in self.site:
            return None
        for index in range(1, 28):
            for elem in bs4(self._html(
                    'http://scpsandbox2.wikidot.com/image-review-{}'
                    .format(index)))('tr'):
                if not elem('td'):
                    continue
                source = elem('td')[3].find('a')
                status = elem('td')[4].text
                notes = elem('td')[5].text
                yield dict(
                    url=elem('td')[0].img['src'],
                    page=elem('td')[1].a['href'],
                    source=source['href'] if source else None,
                    status=status if status else None,
                    notes=notes if notes else None)

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
        page_id = kwargs.get('page_id', None)
        payload = {
            'page_id': page_id,
            'pageId': page_id,  # fuck wikidot
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
                        .format(name, page_id, kwargs, err))

    def _page_action(self, page_id, event, **kwargs):
        return self._module('Empty', action='WikiPageAction',
                            page_id=page_id, event=event, **kwargs)

    def _parse_thread(self, html):
        for elem in bs4(html)(class_='post'):
            granpa = elem.parent.parent
            if 'post-container' in granpa.get('class', ''):
                parent = granpa.find(class_='post')['id'].split('-')[1]
            else:
                parent = None
            time = elem.find(class_='odate')['class'][1].split('_')[1]
            title = elem.find(class_='title').text.strip()
            content = elem.find(class_='content')
            content.attrs.clear()
            for i in list(content.strings):
                i.replace_with(i.strip())
            yield {
                'post_id': elem['id'].split('-')[1],
                'title': title if title else None,
                'content': str(content),
                'user': elem.find(class_='printuser').text,
                'time': arrow.get(time).format('YYYY-MM-DD HH:mm:ss'),
                'parent': parent}

    def _pager(self, name, _next, **kwargs):
        """Iterate over multi-page module results."""
        first_page = self._module(name, **kwargs)
        yield first_page
        counter = bs4(first_page['body']).find(class_='pager-no')
        if counter:
            for page in range(2, int(counter.text.split(' ')[-1]) + 1):
                kwargs.update(_next(page))
                yield self._module(name, **kwargs)


class SnapshotConnector:

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

    def __init__(self, site, dbpath):
        parsed = urlparse(site)
        netloc = parsed.netloc or parsed.path
        if '.' not in netloc:
            netloc += '.wikidot.com'
        self.site = urlunparse(['http', netloc, '', '', '', ''])
        self.dbpath = dbpath
        orm.connect(self.dbpath)
        self.wiki = WikidotConnector(site)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=25)

    def __call__(self, url):
        return Page(url, self)

    def __repr__(self):
        return "{}('{}', '{}')".format(
            self.__class__.__name__,
            urlparse(self.site).netloc.replace('.wikidot.com', ''),
            self.dbpath)

    ###########################################################################
    # Connector Page API
    ###########################################################################

    def _page_id(self, url, html):
        try:
            return orm.Page.get(orm.Page.url == url).page_id
        except orm.Page.DoesNotExist:
            return None

    def _thread_id(self, page_id, html):
        return orm.Page.get(orm.Page.page_id == page_id).thread_id

    def _html(self, url):
        try:
            return orm.Page.get(orm.Page.url == url).html
        except orm.Page.DoesNotExist:
            return None

    def _source(self, page_id):
        raise ConnectorError

    def _history(self, page_id):
        for i in orm.Revision.select().where(orm.Revision.page_id == page_id):
            yield dict(
                revision_id=i.revision_id,
                page_id=page_id,
                number=i.number,
                user=i.user,
                time=i.time,
                comment=i.comment)

    def _votes(self, page_id):
        for i in orm.Vote.select().where(orm.Vote.page_id == page_id):
            yield dict(page_id=page_id, user=i.user, value=i.value)

    def _tags(self, page_id, html):
        for i in orm.Tag.select().where(orm.Tag.page_id == page_id):
            yield i.tag

    ###########################################################################

    def _edit(self, page_id, url, source, title, comment):
        raise ConnectorError

    def _revert_to(self, page_id, revision_id):
        raise ConnectorError

    def _set_tags(self, page_id, tags):
        raise ConnectorError

    def _set_vote(self, page_id, value, force=False):
        raise ConnectorError

    ###########################################################################

    def _posts(self, thread_id):
        for i in orm.ForumPost.select().where(
                orm.ForumPost.thread_id == thread_id):
            yield dict(
                thread_id=thread_id,
                post_id=i.post_id,
                title=i.title,
                content=i.content,
                user=i.user,
                time=i.time,
                parent=i.parent)

    def reply_to(self, thread_id, post_id, source, title):
        raise ConnectorError

    ###########################################################################
    # Connector Public API
    ###########################################################################

    def auth(self, username, password):
        return self.wiki.auth(username, password)

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
                (orm.Page._id << created_pages) |
                (orm.Page.url << include_pages)) &
                ~(orm.Page.url << exclude_pages))
        for i in query.order_by(orm.Page.url):
            yield i.url

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _save_page(self, url):
        """Download the page and write it to the db."""
        log.info('Saving page: {}'.format(url))
        html = self.wiki._html(url)
        if html is None:
            return
        page_id = self.wiki._page_id(None, html)
        thread_id = self.wiki._thread_id(None, html)
        orm.Page.create(url=url, page_id=page_id, thread_id=thread_id,
                        html=str(bs4(html).find(id='main-content')))
        orm.Revision.insert_many(self.wiki._history(page_id))
        orm.Vote.insert_many(self.wiki._votes(page_id))
        orm.ForumPost.insert_many(self.wiki._posts(thread_id))
        orm.Tag.insert_many(dict(page_id=page_id, tag=i)
                            for i in self.wiki._tags(None, html))

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

    def _save_meta(self):
        log.info('Downloading image metadata.')
        orm.Image.create_table()
        images = [i for i in self.wiki.images() if i['status'] in (
            'PERMISSION GRANTED',
            'BY-NC-SA CC',
            'BY-SA CC',
            'PUBLIC DOMAIN')]
        total = len(images)
        for index, _ in enumerate(self.pool.map(self._save_image, images)):
            log.info('Saved image {}/{}.'.format(index + 1, total))
        log.info('Downloading author metadata.')
        orm.Rewrite.create_table()
        orm.Rewrite.insert_many(self.wiki.rewrites())

    def _save_image(self, image):
        if not image['source']:
            log.info('Image skipped: source not specified: {}'.format(image))
            return
        try:
            data = self.wiki.req.get(image['url']).content
        except requests.HTTPError as err:
            log.warning('Failed to download the image: {}'.format(err))
            return
        image.update(data=data)
        orm.Image.create(**image)

    ###########################################################################
    # Public Methods
    ###########################################################################

    def take(self, include_forums=False):
        time_start = arrow.now()
        orm.purge()
        for i in [
                orm.Page, orm.Revision, orm.Vote,
                orm.ForumPost, orm.Tag]:
            i.create_table()
        #concurrent.futures.wait([
        #    self.pool.submit(self._save_page, i)
        #    for i in self.wiki.list_pages()])
        if include_forums:
            ftrs = self._save_forums()
            concurrent.futures.wait(ftrs)
        if 'scp-wiki' in self.site:
            self._save_meta()
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


class Page:

    """ """

    ###########################################################################
    # Special Methods
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
    # Special Methods
    ###########################################################################

    def _flush(self, *properties):
        for i in properties:
            if i in self.cache:
                del self._cache[i]

    ###########################################################################
    # Core Properties
    ###########################################################################

    @cached_property
    def page_id(self):
        return self._cn._pageid(self.url, self.html)

    @cached_property
    def thread_id(self):
        return self._cn._thread_id(self.url, self.html)

    @cached_property
    def html(self):
        return self._cn._html(self.url)

    @cached_property
    def source(self):
        return self._cn._source(self)

    @cached_property
    def history(self):
        data = self._cn._history(self)
        history = [Revision(**i) for i in data]
        return list(sorted(history, key=lambda x: x.number))

    @cached_property
    def votes(self):
        data = self._cn._votes(self)
        Vote = namedtuple('Vote', 'user value')
        return [Vote(i['user'], i['value']) for i in data]

    @cached_property
    def tags(self):
        return list(self._cn._tags(self.page_id, self.html))

    @cached_property
    def comments(self):
        return ForumThread(
            self.thread_id, None, None,
            [ForumPost(**i) for i in self._cn._posts(self.thread_id)])

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
        self._flush('html', 'history', 'source')

    def revert_to(self, rev_n):
        self._cn._revert_to(self, self.history[rev_n].revision_id)
        self._flush('html', 'history', 'source', 'tags')

    def set_tags(self, tags):
        self._cn._set_tags(self, tags)
        self._flush('history', 'tags')

    def cancel_vote(self):
        self._cn._set_vote(self, 0)
        self._flush('votes')

    def upvote(self):
        self._cn._set_vote(self, 1)
        self._flush('votes')

    def downvote(self):
        self._cn._set_vote(self, -1)
        self._flush('votes')


class ForumThread:

    def __init__(self, thread_id, title, description, posts):
        for k, v in locals().items():
            if k != 'self':
                setattr(self, k, v)

    def __repr__(self):
        return '<{}({})>'.format(self.__class__.__name__, self.thread_id)

    def __getitem__(self, index):
        return self.posts[index]

    def __len__(self):
        return len(self.posts)


class ForumPost:

    def __init__(self, post_id, thread_id, title, content, user, time, parent):
        for k, v in locals().items():
            if k != 'self':
                setattr(self, k, v)

    def __repr__(self):
        return '<{}({})>'.format(self.__class__.__name__, self.post_id)

    @property
    def text(self):
        return '\n\n'.join(bs4(self.content).stripped_strings)

    @property
    def wordcount(self):
        return len(self.text.split())


class Revision:

    def __init__(self, revision_id, number, user, time, comment):
        for k, v in locals().items():
            if k != 'self':
                setattr(self, k, v)

    def __repr__(self):
        return '<{}({})>'.format(self.__class__.__name__, self.revision_id)


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
