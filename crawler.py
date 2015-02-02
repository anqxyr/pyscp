#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import cached_property
import collections
import concurrent.futures
import contextlib
import itertools
import logging
import orm
import os
import re
import requests

###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.crawler')
logger.setLevel(logging.DEBUG)

###############################################################################
# Primary Classes
###############################################################################


class WikidotConnector:

    """
    Provide a low-level interface to a Wikidot site.

    This class does not use any of the official Wikidot API, and instead
    relies on sending http post/get requests to internal Wikidot pages and
    parsing the returned data.
    """

    def __init__(self, site):
        """
        Initialize an instance of the class.

        Args:
            site (str): Full url of the main page of the site
        """
        self.site = site.rstrip('/')
        req = requests.Session()
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _module(self, name, pageid, **kwargs):
        """
        Call a Wikidot module.

        This method is responsible for most of the class' functionality.
        Almost all other methods of the class are using _module in one way
        or another.
        """
        logger.debug('_module call: {} ({}) {}'.format(name, pageid, kwargs))
        payload = {
            'page_id': pageid,
            'pageId': pageid,  # fuck wikidot
            'moduleName': name,
            # token7 can be any 6-digit number, as long as it's the same
            # in the payload and in the cookie
            'wikidot_token7': '123456'}
        cookies = {'wikidot_token7': '123456'}
        for i in self.req.cookies:
            cookies[i.name] = i.value
        for k, v in kwargs.items():
            payload[k] = v
        data = self.req.post(
            self.site + '/ajax-module-connector.php',
            data=payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded;'},
            cookies=cookies, timeout=30)
        if data.status_code != 200:
            logger.warning(
                'Status code {} recieved from _module call: {} ({}) {}'
                .format(data.status_code, name, pageid, kwargs))
        return data.json()

    def _parse_forum_thread_page(self, page_html, thread_id):
        """Parse posts from an html string of a single forum page."""
        for tag in bs4.BeautifulSoup(page_html).select('div.post'):
            granpa = tag.parent.parent
            if 'class' in granpa.attrs and 'post-container' in granpa['class']:
                parent = granpa.select('div.post')[0]['id'].split('-')[1]
            else:
                parent = None
            yield {
                'post_id': tag['id'].split('-')[1],
                'thread_id': thread_id,
                'title': tag.select('div.title')[0].text.strip(),
                'content': tag.select('div.content')[0],
                'user': tag.select('span.printuser')[0].text,
                'time': (arrow.get(
                    tag.select('span.odate')[0]['class'][1].split('_')[1])
                    .format('YYYY-MM-DD HH:mm:ss')),
                'parent': parent}

    def _pager(self, baseurl):
        """
        Iterate over multi-page pages.

        Some Wikidot pages that seem to employ the paging mechanism
        actually don't. For example, discussion pages have a navigation
        bar that displays '<< previous' and 'next >>' buttons; however,
        discussion pages actually use separate calls to the
        ForumViewThreadPostsModule.
        """
        logger.debug('Paging through {}'.format(baseurl))
        first_page = self.get_page_html(baseurl)
        yield first_page
        soup = bs4.BeautifulSoup(first_page)
        try:
            counter = soup.select('div.pager span.pager-no')[0].text
        except IndexError:
            return
        last_page_index = int(counter.split(' ')[-1])
        for index in range(2, last_page_index + 1):
            logger.debug('Paging through {} ({}/{})'.format(
                baseurl, index, last_page_index))
            url = '{}/p/{}'.format(baseurl, index)
            yield self.get_page_html(url)

    ###########################################################################
    # Data Retrieval Methods
    ###########################################################################

    def get_page_html(self, url):
        """Download the html data of the page."""
        data = self.req.get(url, allow_redirects=False, timeout=30)
        if data.status_code == 200:
            return data.text
        else:
            msg = 'Page {} returned http status code {}'
            logger.warning(msg.format(url, data.status_code))
            return None

    def get_page_history(self, pageid):
        """Download the revision history of the page."""
        if pageid is None:
            return None
        data = self._module(name='history/PageRevisionListModule',
                            pageid=pageid, page=1, perpage=1000000)['body']
        for i in bs4.BeautifulSoup(data).select('tr')[1:]:
            yield {
                'pageid': pageid,
                'number': int(i.select('td')[0].text.strip('.')),
                'user': i.select('td')[4].text,
                'time': (arrow.get(
                    i.select('td')[5].span['class'][1].split('_')[1])
                    .format('YYYY-MM-DD HH:mm:ss')),
                'comment': i.select('td')[6].text}

    def get_page_votes(self, pageid):
        """Download the vote data."""
        if pageid is None:
            return None
        data = self._module(name='pagerate/WhoRatedPageModule',
                            pageid=pageid)['body']
        for i in bs4.BeautifulSoup(data).select('span.printuser'):
            yield {'pageid': pageid, 'user': i.text, 'vote': (
                1 if i.next_sibling.next_sibling.text.strip() == '+'
                else -1)}

    def get_page_source(self, pageid):
        """Download page source."""
        if pageid is None:
            return None
        data = self._module(
            name='viewsource/ViewSourceModule',
            pageid=pageid)['body']
        return bs4.BeautifulSoup(data).text[11:].strip()

    def get_forum_thread(self, thread_id):
        """Download and parse the contents of the forum thread."""
        if thread_id is None:
            return
        data = self._module(name='forum/ForumViewThreadPostsModule',
                            t=thread_id, pageid=None, pageNo=1)['body']
        try:
            pager = bs4.BeautifulSoup(data).select('span.pager-no')[0].text
            num_of_pages = int(pager.split(' of ')[1])
        except IndexError:
            num_of_pages = 1
        yield from self._parse_forum_thread_page(data, thread_id)
        for n in range(2, num_of_pages + 1):
            data = self._module(name='forum/ForumViewThreadPostsModule',
                                t=thread_id, pageid=None, pageNo=n)['body']
            yield from self._parse_forum_thread_page(data, thread_id)

    ###########################################################################
    # Site Structure Methods
    ###########################################################################

    def list_all_pages(self):
        """Yield urls of all the pages on the site."""
        for page in self._pager(self.site + '/system:list-all-pages'):
            for l in bs4.BeautifulSoup(page).select('div.list-pages-item a'):
                yield self.site + l['href']

    def list_categories(self):
        """Yield dicts describing all forum categories on the site."""
        baseurl = '{}/forum:start'.format(self.site)
        soup = bs4.BeautifulSoup(self.get_page_html(baseurl))
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
        baseurl = '{}/forum/c-{}'.format(self.site, category_id)
        for page in self._pager(baseurl):
            for i in bs4.BeautifulSoup(page).select('td.name'):
                yield {
                    'thread_id': re.search(
                        r'/forum/t-([0-9]+)',
                        i.select('div.title')[0].a['href']).group(1),
                    'title': i.select('div.title')[0].text.strip(),
                    'description': i.select('div.description')[0].text.strip(),
                    'category_id': category_id}

    ###########################################################################
    # Methods Requiring Authorization
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

    def edit_page(self, pageid, url, source, title, comments=None):
        """
        Overwrite the page with the new source and title.

        'pageid' and 'url' must belong to the same page.
        'comments' is the optional edit message that will be displayed in
        the page's revision history.
        """
        lock = self._module('edit/PageEditModule', pageid, mode='page')
        params = {
            'source': source,
            'comments': comments,
            'title': title,
            'lock_id': lock['lock_id'],
            'lock_secret': lock['lock_secret'],
            'revision_id': lock['page_revision_id'],
            'action': 'WikiPageAction',
            'event': 'savePage',
            'wiki_page': url.split('/')[-1]}
        self._module('Empty', pageid, **params)

    def post_in_thread(self, thread_id, source, title=None):
        """Make a new post in the given thread."""
        params = {
            'threadId': thread_id,
            # used for replying to other posts, not currently implemented.
            'parentId': None,
            'title': title,
            'source': source,
            'action': 'ForumAction',
            'event': 'savePost'}
        self._module('Empty', None, **params)

    def set_page_tags(self, pageid, tags):
        """Replace the tags of the page."""
        params = {
            'tags': ' '.join(tags),
            'action': 'WikiPageAction',
            'event': 'saveTags'}
        self._module('Empty', pageid, **params)


class Snapshot:

    database_directory = '/home/anqxyr/heap/_scp/'

    def __init__(self, site='http://www.scp-wiki.net', dbname=None):
        if dbname is None:
            domain = site.split('.')[-2]
            if domain == 'wikidot':
                domain = site.split('.')[-3]
            domain = re.sub(r'^http://', '', domain)
            dbname = '{}.{}.db'.format(
                domain,
                arrow.now().format('YYYY-MM-DD'))
        self.dbname = dbname
        self.dbpath = self.database_directory + dbname
        orm.connect(self.dbpath)
        self.db = orm.db
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
        self.site = site
        self.wiki = WikidotConnector(self.site)

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _scrape_images(self):
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        req = requests.Session()
        req.mount('http://', requests.adapters.HTTPAdapter(max_retries=5))
        soup = bs4.BeautifulSoup(req.get(url).text)
        data = []
        for i in soup.select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            image_data = req.get(image_url).content
            data.append({
                "url": image_url,
                "source": image_source,
                "data": image_data})
        return data

    def _scrape_authors(self):
        url = "http://05command.wikidot.com/alexandra-rewrite"
        req = requests.Session()
        site = 'http://05command.wikidot.com'
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        soup = bs4.BeautifulSoup(req.get(url).text)
        data = []
        for i in soup.select("tr")[1:]:
            url = "http://www.scp-wiki.net/{}".format(i.select("td")[0].text)
            author = i.select("td")[1].text
            if author.startswith(":override:"):
                override = True
                author = author[10:]
            else:
                override = False
            data.append({"url": url, "author": author, "override": override})
        return data

    def _save_page(self, url):
        exclusion_list = ['http://www.scp-wiki.net/forum:thread']
        if url in exclusion_list:
            logger.warning(
                'Page {} is in the exlusion list and will not be saved'
                .format(url))
            return
        logger.info('Saving page: {}'.format(url))
        html = self.wiki.get_page_html(url)
        if html is None:
            return
        pageid = re.search('pageId = ([^;]*);', html)
        pageid = pageid.group(1) if pageid is not None else None
        soup = bs4.BeautifulSoup(html)
        try:
            link = soup.select('#discuss-button')[0]['href']
            thread_id = re.search(r'/forum/t-([0-9]+)/', link).group(1)
        except (IndexError, AttributeError):
            thread_id = None
        html = str(soup.select('#main-content')[0])
        orm.Page.create(pageid=pageid, url=url, html=html, thread_id=thread_id)
        orm.Revision.insert_many(self.wiki.get_page_history(pageid))
        orm.Vote.insert_many(self.wiki.get_page_votes(pageid))
        orm.ForumPost.insert_many(self.wiki.get_forum_thread(thread_id))
        orm.Tag.insert_many(
            {'tag': a.string, 'url': url} for a in
            bs4.BeautifulSoup(html).select("div.page-tags a"))
        logger.debug('Finished saving page: {}'.format(url))

    def _save_thread(self, thread, msg):
        logger.info(msg)
        orm.ForumThread.create(**thread)
        orm.ForumPost.insert_many(
            self.wiki.get_forum_thread(thread['thread_id']))

    def _save_forums(self,):
        orm.ForumThread.create_table()
        orm.ForumCategory.create_table()
        categories = [
            i for i in self.wiki.list_categories()
            if i['title'] != 'Per page discussions']
        total_threads = sum([i['threads'] for i in categories])
        index = 1
        futures = []
        for c in categories:
            orm.ForumCategory.create(**c)
            for t in self.wiki.list_threads(c['category_id']):
                msg = 'Saving forum thread #{}/{}: {}'
                msg = msg.format(index, total_threads, t['title'])
                index += 1
                futures.append(self.executor.submit(self._save_thread, t, msg))
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
        query = orm.Vote.select().where(orm.Vote.pageid == pageid)
        votes = []
        for i in query:
            votes.append({'pageid': pageid, 'user': i.user, 'vote': i.vote})
        return votes

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

    def take(self, include_forums=False):
        time_start = arrow.now()
        orm.purge(self.dbpath)
        for i in [orm.Page, orm.Revision, orm.Vote, orm.ForumPost, orm.Tag]:
            i.create_table()
        ftrs = [self.executor.submit(self._save_page, i)
                for i in itertools.islice(self.wiki.list_all_pages(), 10)]
        concurrent.futures.wait(ftrs)
        if include_forums:
            ftrs = self._save_forums()
            concurrent.futures.wait(ftrs)
        if self.site == 'http://www.scp-wiki.net':
            orm.Image.create_table()
            logger.info('Downloading image metadata.')
            orm.Image.insert_many(self._scrape_images())
            orm.Author.create_table()
            logger.info('Downloading author metadata.')
            orm.Author.insert_many(self._scrape_authors())
        orm.queue.join()
        time_taken = (arrow.now() - time_start)
        hours, remainder = divmod(time_taken.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = 'Snapshot succesfully taken. [{:02d}:{:02d}:{:02d}]'
        msg = msg.format(hours, minutes, seconds)
        logger.info(msg)

    def get_tag(self, tag):
        """Retrieve list of pages with the tag from the database"""
        for i in orm.Tag.select().where(orm.Tag.tag == tag):
            yield i.url

    def get_author_metadata(self, url):
        try:
            au = orm.Author.get(orm.Author.url == url)
            return {'user': au.author, 'override': au.override}
        except orm.Author.DoesNotExist:
            return None

    def get_image_metadata(self, url):
        try:
            img = orm.Image.get(orm.Image.url == url)
            return {'url': img.url, 'source': img.source, 'data': img.data}
        except orm.Image.DoesNotExist:
            return None

    def list_all_pages(self):
        count = orm.Page.select().count()
        for n in range(1, count // 200 + 2):
            query = orm.Page.select(
                orm.Page.url).order_by(
                orm.Page.url).paginate(n, 200)
            for i in query:
                yield i.url


class Page:

    """Scrape and store contents and metadata of a page."""

    sn = None   # Snapshot instance used to init the pages
    _title_index = None

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url=None):
        prefix = 'http://www.scp-wiki.net/'
        if url is not None and not url.startswith(prefix):
            url = prefix + url
        self.url = url

    ###########################################################################
    # Class Methods
    ###########################################################################

    @classmethod
    @contextlib.contextmanager
    def from_snapshot(cls, name=None):
        previous_sn = cls.sn
        if name is None:
            name = sorted([
                i for i in os.listdir(Snapshot.database_directory)
                if i.startswith('scp-wiki') and i.endswith('.db')])[-1]
        cls.sn = Snapshot(dbname=name)
        yield cls.sn
        if previous_sn is not None:
            orm.connect(previous_sn.dbname)
        cls.sn = previous_sn

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _get_children_if_skip(self):
        children = []
        for url in self.links:
            p = self.__class__(url)
            if 'supplement' in p.tags or 'splash' in p.tags:
                children.append(p.url)
        return children

    def _get_children_if_hub(self):
        maybe_children = []
        confirmed_children = []
        for url in self.links:
            p = self.__class__(url)
            if set(p.tags) & {'tale', 'goi-format', 'goi2014'}:
                maybe_children.append(p.url)
            if self.url in p.links:
                confirmed_children.append(p.url)
            elif p.html:
                crumb = bs4.BeautifulSoup(p.html).select('#breadcrumbs a')
                if crumb:
                    parent = crumb[-1]
                    parent = 'http://www.scp-wiki.net{}'.format(parent['href'])
                    if self.url == parent:
                        confirmed_children.append(p.url)
        if confirmed_children:
            return confirmed_children
        else:
            return maybe_children

    @classmethod
    def _construct_title_index(cls):
        logger.info('constructing title index')
        index_pages = ['scp-series', 'scp-series-2', 'scp-series-3']
        index = {}
        for url in index_pages:
            soup = bs4.BeautifulSoup(cls(url).html)
            items = [i for i in soup.select('ul > li')
                     if re.search('[SCP]+-[0-9]+', i.text)]
            for i in items:
                url = cls.sn.site + i.a['href']
                try:
                    skip, title = i.text.split(' - ', maxsplit=1)
                except ValueError:
                    skip, title = i.text.split(', ', maxsplit=1)
                    #skip, title = i.text.split('- ', maxsplit=1)
                if url not in cls.sn.get_tag('splash'):
                    index[url] = title
                else:
                    true_url = '{}/{}'.format(cls.sn.site, skip.lower())
                    index[true_url] = title
        cls._title_index = index

    ###########################################################################
    # Internal Properties
    ###########################################################################

    @cached_property.cached_property
    def _pageid(self):
        return self.sn.get_pageid(self.url)

    @cached_property.cached_property
    def _thread_id(self):
        return self.sn.get_thread_id(self.url)

    @cached_property.cached_property
    def _wikidot_title(self):
        '''
        Page title as used by wikidot. Should only be used by the self.title
        property or when editing the page. In all other cases, use self.title.
        '''
        tag = bs4.BeautifulSoup(self.html).select('#page-title')
        return tag[0].text.strip() if tag else ''

    ###########################################################################
    # Public Properties
    ###########################################################################

    @cached_property.cached_property
    def html(self):
        return self.sn.get_page_html(self.url)

    @cached_property.cached_property
    def text(self):
        return bs4.BeautifulSoup(self.html).select('#page-content')[0].text

    @cached_property.cached_property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    @cached_property.cached_property
    def images(self):
        return [i['src'] for i in bs4.BeautifulSoup(self.html).select('img')]

    @cached_property.cached_property
    def title(self):
        if 'scp' in self.tags and re.search('[scp]+-[0-9]+$', self.url):
            if self._title_index is None:
                self._construct_title_index()
            title = '{}: {}'.format(
                self._wikidot_title,
                self._title_index[self.url])
            return title
        return self._wikidot_title

    @cached_property.cached_property
    def history(self):
        data = self.sn.get_page_history(self._pageid)
        rev = collections.namedtuple('Revision', 'number user time comment')
        history = []
        for i in data:
            history.append(rev(
                i['number'],
                i['user'],
                i['time'],
                i['comment']))
        return history

    @cached_property.cached_property
    def created(self):
        return self.history[0].time

    @cached_property.cached_property
    def authors(self):
        if self.url is None:
            return None
        authors = []
        author = collections.namedtuple('Author', 'user status')
        second_author = self.sn.get_author_metadata(self.url)
        if ((second_author is None
                or not second_author['override'])):
            authors.append(author(self.history[0].user, 'original'))
        if second_author is not None:
            if second_author['override']:
                authors.append(author(second_author['user'], 'override'))
            else:
                authors.append(author(second_author['user'], 'rewrite'))
        return authors

    @cached_property.cached_property
    def author(self):
        if len(self.authors) == 0:
            return None
        if len(self.authors) == 1:
            return self.authors[0].user
        else:
            for i in self.authors:
                if i.status == 'override':
                    return i.user
                if i.status == 'original':
                    original_author = i.user
            return original_author

    @cached_property.cached_property
    def votes(self):
        data = self.sn.get_page_votes(self._pageid)
        vote = collections.namedtuple('Vote', 'user value')
        votes = []
        for i in data:
            votes.append(vote(i['user'], i['vote']))
        return votes

    @cached_property.cached_property
    def rating(self):
        if not self.votes:
            return None
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

    @cached_property.cached_property
    def tags(self):
        return self.sn.get_page_tags(self.url)

    @cached_property.cached_property
    def comments(self):
        data = self.sn.get_forum_thread(self._thread_id)
        com = collections.namedtuple(
            'Comment', 'post_id parent title user time content')
        comments = []
        for i in data:
            comments.append(com(
                i['post_id'],
                i['parent'],
                i['title'],
                i['user'],
                i['time'],
                i['content']))
        return comments

    @cached_property.cached_property
    def links(self):
        if self.html is None:
            return []
        links = {}
        for a in bs4.BeautifulSoup(self.html).select('#page-content a'):
            if (('href' not in a.attrs) or
                (a['href'][0] != '/') or
                    (a['href'][-4:] in ['.png', '.jpg', '.gif'])):
                continue
            url = 'http://www.scp-wiki.net{}'.format(a['href'])
            url = url.rstrip("|")
            links.add(url)
        return list(links)

    @cached_property.cached_property
    def children(self):
        if 'scp' in self.tags or 'splash' in self.tags:
            return self._get_children_if_skip()
        if 'hub' in self.tags and (set(self.tags) & {'tale', 'goi2014'}):
            return self._get_children_if_hub()
        return []

###############################################################################
# Main Methods
###############################################################################


def enable_logging(logger):
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('scp').addHandler(console)
    logfile = logging.FileHandler('logfile.txt', mode='w', delay=True)
    logfile.setLevel(logging.WARNING)
    file_format = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
    file_formatter = logging.Formatter(file_format)
    logfile.setFormatter(file_formatter)
    logging.getLogger('scp').addHandler(logfile)


def main():
    Snapshot(dbname='test.db').take()
    pass


if __name__ == "__main__":
    enable_logging(logger)
    main()
