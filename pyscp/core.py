#!/usr/bin/env python3

"""
Python API and utilities for the scp-wiki.net website.

pyscp is a python library for interacting with wikidot-hosted websites. The
library is mainly intended for use by the administrative staff of the
www.scp-wiki.net website, and has a host of feature exclusive to it. However,
the majority of the core functionality should be applicalbe to any
wikidot-based site.

The core module holds the classes responsible for communicating with the
wikidot sites, representing individual wiki pages as python objects, and
creating and accessing site snapshots.
"""


###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import collections
import concurrent.futures
import functools
import itertools
import logging
import operator
import pathlib
import re
import requests
import urllib.parse

from pyscp import orm, utils

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Utility Classes
###############################################################################


class InsistentRequest(requests.Session):

    """Make an auto-retrying request that handles connection loss."""

    def __init__(self, max_attempts=10):
        super().__init__()
        self.max_attempts = max_attempts

    def __repr__(self):
        return '{}(max_attempts={})'.format(
            self.__class__.__name__, self.max_attempts)

    def request(self, method, url, **kwargs):
        log.debug('%s: %s %s', method, url, repr(kwargs) if kwargs else '')
        kwargs.setdefault('timeout', 30)
        kwargs.setdefault('allow_redirects', False)
        for _ in range(self.max_attempts):
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


class WikidotPageAdapter:

    """
    Retrieve page data.

    Page Adapters are used by the Page class to gain information pertaining to
    a specific page. They request raw data from their respective Connectors and
    format it in a manner that is expected by the Page class.

    This class supports the following fields:

    - page_id
    - thread_id
    - html
    - history
    - votes
    - tags
    - source

    """

    def __init__(self, connector):
        self.cn = connector
        for i in 'page_id', 'thread_id', 'html', 'tags':
            setattr(self, 'get_' + i, self._load_page)

    ###########################################################################
    # Private Methods
    ###########################################################################

    @utils.morph(requests.RequestException, ConnectorError)
    @utils.log_errors(log.warning)
    def _load_page(self, page):
        """
        Download the page and extract data from the html.

        Returns a dict of page_id, thread_id, html, and tags. Methods such
        as get_html are in fact merely aliases for this method.
        """
        html = self.cn.req.get(page.url).text
        soup = bs4.BeautifulSoup(html)
        return dict(
            page_id=int(re.search('pageId = ([0-9]+);', html).group(1)),
            thread_id=self.cn._get_id(soup.find(id='discuss-button')),
            html=str(soup.find(id='main-content')),
            tags={e.text for e in soup.select('.page-tags a')})

    @staticmethod
    def _crawl_posts(post_containers, parent=None):
        """
        Retrieve posts from the comment tree.

        For each post-container in the given list, returns a tuple of
        (post, parent). Then recurses onto all the post-container children
        of the current post-container.
        """
        for container in post_containers:
            yield container.find(class_='post'), parent
            yield from WikidotPageAdapter._crawl_posts(
                container(class_='post-container', recursive=False),
                int(container['id'].split('-')[1]))

    ###########################################################################
    # Public Methods
    ###########################################################################

    def get_posts(self, page):
        return {'posts': list(self.get_thread_posts(page.thread_id))}

    def get_thread_posts(self, thread_id):
        """Download and parse the contents of the forum thread."""
        if thread_id is None:
            return
        pages = self.cn._pager(
            'forum/ForumViewThreadPostsModule',
            _key='pageNo',
            t=thread_id)
        pages = (bs4.BeautifulSoup(p['body']).body for p in pages)
        pages = (p for p in pages if p)
        posts = (p(class_='post-container', recursive=False) for p in pages)
        posts = itertools.chain.from_iterable(posts)
        for post, parent in self._crawl_posts(posts):
            post_id = int(post['id'].split('-')[1])
            title = post.find(class_='title').text.strip()
            if not title:
                title = None
            content = post.find(class_='content')
            content.attrs.clear()
            content = str(content)
            user = post.find(class_='printuser').text
            time = self.cn._parse_time(post)
            yield ForumPost(post_id, title, content, user, time, parent)


class SnapshotConnector:

    """
    """

    def __init__(self, site, dbpath):
        if not pathlib.Path(dbpath).exists():
            raise FileNotFoundError(dbpath)
        self.site = full_url(site)
        self.dbpath = dbpath
        self.adapter = SnapshotPageAdapter(self)
        orm.connect(dbpath)

    def __call__(self, url):
        return Page(url, self)

    def __repr__(self):
        return '{}({}, {})'.format(
            self.__class__.__name__,
            repr(self.site.replace('http://', '')),
            repr(self.dbpath))

    ###########################################################################
    # Connector Public API
    ###########################################################################

    def _list_author(self, author):
        query = (
            orm.Page.select(orm.Page.url)
            .join(orm.Revision).join(orm.User)
            .where(orm.Revision.number == 0)
            .where(orm.User.name == author))
        include, exclude = [], []
        for over in self.list_overrides():
            if over.user == author:
                include.append(over.url)
            elif over.type == 'author':
                exclude.append(over.url)
        return (query.where(~(orm.Page.url << exclude)) |
                orm.Page.select(orm.Page.url).where(orm.Page.url << include))

    def _list_rating(self, rating):
        op, value, *_ = re.split('([0-9]+)', rating)
        if op not in ('>', '<', '>=', '<=', '=', ''):
            raise ValueError
        if not op or op == '=':
            op = '=='
        compare = lambda x: eval('x {} {}'.format(op, value))
        return (orm.Page.select(orm.Page.url)
                .join(orm.Vote).group_by(orm.Page.url)
                .having(compare(orm.peewee.fn.sum(orm.Vote.value))))

    def _list_created(self, created):
        op, date, *_ = re.split('([0-9-]+)', created)
        year, month, day, *_ = date.split('-') + [None, None]
        if op not in ('>', '<', '>=', '<=', '=', ''):
            raise ValueError
        code_year = '(x.year {{}} {})'.format(year)
        if op and op != '=':
            if op in ('<', '>='):
                month = month if month else 1
                day = day if day else 1
            else:
                month = month if month else 12
                day = day if day else 31
            code_month = '(x.month {{}} {})'.format(month)
            code_day = '(x.day {{}} {})'.format(day)
            code_string = '({0} | ({0} & {1}) | ({0} & {1} & {2}))'.format(
                code_year, code_month, code_day)
            code_string = code_string.format(op, '==', op, '==', '==', op)
        else:
            code_string = code_year.format('==')
            if month:
                code_string += ' & (x.month == {})'.format(int(month))
            if day:
                code_string += ' & (x.day == {})'.format(int(day))
            code_string = '({})'.format(code_string)
        compare = lambda x: eval(code_string)
        return (orm.Page.select(orm.Page.url)
                .join(orm.Revision).where(orm.Revision.number == 0)
                .group_by(orm.Page.url)
                .having(compare(orm.Revision.time)))

    def list_pages(self, **kwargs):
        query = orm.Page.select(orm.Page.url)
        if 'author' in kwargs:
            query = query & self._list_author(kwargs['author'])
        if 'tag' in kwargs:
            query = query & (
                orm.Page.select(orm.Page.url)
                .join(orm.PageTag).join(orm.Tag)
                .where(orm.Tag.name == kwargs['tag']))
        if 'rating' in kwargs:
            query = query & self._list_rating(kwargs['rating'])
        if 'created' in kwargs:
            query = query & self._list_created(kwargs['created'])
        if 'order' in kwargs:
            query = query.order_by(orm.peewee.fn.Random())
        else:
            query = query.order_by(orm.Page.url)
        if 'limit' in kwargs:
            query = query.limit(kwargs['limit'])
        for i in query:
            yield i.url

    @functools.lru_cache()
    @utils.listify()
    def list_overrides(self):
        for row in (
                orm.Override
                .select(orm.Override, orm.User.name, orm.OverrideType.name)
                .join(orm.User).switch(orm.Override).join(orm.OverrideType)):
            yield Override(row._data['url'], row.user.name, row.type.name)

    @functools.lru_cache()
    @utils.listify()
    def images(self):
        for row in orm.Image.select():
            yield dict(
                url=row.url, source=row.source, status=row.status.label,
                notes=row.notes, data=row.data)


class SnapshotCreator:

    """
    Create a snapshot of a wikidot site.

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
        if pathlib.Path(dbpath).exists():
            raise FileExistsError(dbpath)
        self.site = full_url(site)
        orm.connect(dbpath)
        self.wiki = WikidotConnector(site)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=20)

    def take_snapshot(self, forums=False):
        """Take new snapshot."""
        self._save_all_pages()
        if forums:
            self._save_forums()
        if 'scp-wiki' in self.site:
            self._save_meta()
        orm.queue.join()
        self._save_id_cache()
        orm.queue.join()
        log.info('Snapshot succesfully taken.')

    def auth(self, username, password):
        return self.wiki.auth(username, password)

    def _save_all_pages(self):
        """Iterate over the site pages, call _save_page for each."""
        orm.create_tables(
            'Page', 'Revision', 'Vote', 'ForumPost',
            'PageTag', 'ForumThread', 'User', 'Tag')
        count = self.wiki.list_pages(body='%%total%%', limit=1)
        count = list(count)[0]['body']
        count = int(bs4.BeautifulSoup(count)('p')[0].text)
        self.bar = utils.ProgressBar('SAVING PAGES'.ljust(20), count)
        self.bar.start()
        for _ in self.pool.map(self._save_page, self.wiki.list_pages()):
            pass
        self.bar.stop()

    @utils.ignore(ConnectorError)
    def _save_page(self, url):
        """Download contents, revisions, votes and discussion of the page."""
        self.bar.value += 1
        p = self.wiki(url)
        orm.Page.create(
            id=p.page_id, url=p.url, thread=p.thread_id, html=p.html)
        history, votes = [map(vars, i) for i in (p.history, p.votes)]
        history, votes = map(orm.User.convert_to_id, (history, votes))
        tags = orm.Tag.convert_to_id([{'tag': t} for t in p.tags], key='tag')
        for data, table in zip(
                (history, votes, tags), (orm.Revision, orm.Vote, orm.PageTag)):
            table.insert_many(dict(i, page=p.page_id) for i in data)
        self._save_thread(ForumThread(p.thread_id, None, None))

    def _save_forums(self):
        """Download and save standalone forum threads."""
        orm.create_tables('ForumPost', 'ForumThread', 'ForumCategory', 'User')
        cats = self.wiki.list_categories()
        cats = [c for c in cats if c.title != 'Per page discussions']
        orm.ForumCategory.insert_many(
            {k: v for k, v in vars(c).items() if k != 'size'} for c in cats)
        total_size = sum(c.size for c in cats)
        self.tbar = utils.ProgressBar('SAVING FORUM THREADS', total_size)
        self.tbar.start()
        for cat in cats:
            threads = set(self.wiki.list_threads(cat.id))
            c_id = itertools.repeat(cat.id)
            for _ in self.pool.map(self._save_thread, threads, c_id):
                pass
        self.tbar.stop()

    def _save_thread(self, thread, c_id=None):
        if c_id:
            self.tbar.value += 1
        orm.ForumThread.create(category=c_id, **vars(thread))
        posts = self.wiki.adapter.get_thread_posts(thread.id)
        posts = orm.User.convert_to_id(map(vars, posts))
        orm.ForumPost.insert_many(dict(p, thread=thread.id) for p in posts)

    def _save_meta(self):
        orm.create_tables('Image', 'ImageStatus', 'Override', 'OverrideType')
        licenses = {
            'PERMISSION GRANTED', 'BY-NC-SA CC', 'BY-SA CC', 'PUBLIC DOMAIN'}
        images = [i for i in self.wiki.list_images() if i.status in licenses]
        self.ibar = utils.ProgressBar('SAVING IMAGES'.ljust(20), len(images))
        self.ibar.start()
        data = list(self.pool.map(self._save_image, images))
        self.ibar.stop()
        images = orm.ImageStatus.convert_to_id(map(vars, images), key='status')
        orm.Image.insert_many(
            dict(i, data=d) for i, d in zip(images, data) if d)
        overs = orm.User.convert_to_id(map(vars, self.wiki.list_overrides()))
        overs = orm.OverrideType.convert_to_id(overs, key='type')
        orm.Override.insert_many(overs)

    @utils.ignore(requests.RequestException)
    def _save_image(self, image):
        self.ibar.value += 1
        if not image.source:
            log.info('Image source not specified: ' + image.url)
            return
        return self.wiki.req.get(image.url, allow_redirects=True).content

    def _save_id_cache(self):
        for table in orm.User, orm.Tag, orm.OverrideType, orm.ImageStatus:
            if table.table_exists():
                table.write_ids('name')


class SnapshotPageAdapter:

    """
    Retrieve data about the page.

    See the documentation for the WikidotPageAdapter for more details.

    This class supports the following fields:

    - page_id
    - thread_id
    - html
    - history
    - votes
    - tags
    - posts

    """

    def __init__(self, connector):
        self.cn = connector
        for i in 'page_id', 'thread_id', 'html':
            setattr(self, 'get_' + i, self._load_page)

    ###########################################################################
    # Private Methods
    ###########################################################################

    def _query(self, page, primary_table, secondary_table='User', key='page'):
        """Generate SQL queries used to retrieve data."""
        pt = getattr(orm, primary_table)
        st = getattr(orm, secondary_table)
        return pt.select(pt, st.name).join(st).where(
            getattr(pt, key) == getattr(page, key + '_id')).execute()

    # Only need to morph this methods, because *all* other methods
    # will eventually call it, and then the exception will bubble up.
    @utils.morph(orm.peewee.DoesNotExist, ConnectorError)
    def _load_page(self, page):
        """
        Retrieve the contents of the page.

        Returns a dict specifying the id of the page, id of the comment
        thread, and the html string.

        The idea here is that most of the time, the user will be needing all
        three of those, so it's better to get them all in a single query. This
        also mirrors the behavior of WikidotPageAdapter, which behaves
        similarly, but for a different reason.
        """
        pdata = orm.Page.get(orm.Page.url == page.url)
        return dict(page_id=pdata.id,
                    thread_id=pdata._data['thread'],
                    html=pdata.html)

    ###########################################################################
    # Public Methods
    ###########################################################################

    def get_history(self, page):
        """Return the revisions of the page."""
        revs = self._query(page, 'Revision')
        revs = sorted(revs, key=operator.attrgetter('number'))
        return {'history': [
            Revision(r.id, r.number, r.user.name, str(r.time), r.comment)
            for r in revs]}

    def get_votes(self, page):
        """Return all votes made on the page."""
        return {'votes': [
            Vote(user=v.user.name, value=v.value)
            for v in self._query(page, 'Vote')]}

    def get_tags(self, page):
        """Return the set of tags with which the page is tagged."""
        return {'tags': {
            pt.tag.name for pt in self._query(page, 'PageTag', 'Tag')}}

    def get_posts(self, page):
        """
        Return the page comments.

        This is also the only Adapter method to work on ForumThread objects,
        for which it returns the posts contained in the forum thread.
        """
        return {'posts': [ForumPost(
            p.id, p.title, p.content, p.user.name,
            str(p.time), p._data['parent'])
            for p in self._query(page, 'ForumPost', key='thread')]}

    def get_source(self):
        """Raise NotImplementedError."""
        raise NotImplementedError('Snapshots do not store the source.')


class Page:

    """ """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, url, connector):
        if connector.site not in url:
            url = '{}/{}'.format(connector.site, url)
        self.url = url.lower()
        self._cn = connector
        self._cache = {}

    def __repr__(self):
        return "{}({}, {})".format(
            self.__class__.__name__,
            repr(self.url.replace(self._cn.site, '').lstrip('/')),
            self._cn)

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _flush(self, *names):
        self._cache = {k: v for k, v in self._cache.items() if k not in names}

    @classmethod
    @functools.lru_cache()
    @utils.listify(dict)
    def _scp_titles(cls, connector):
        log.debug('Constructing title index.')
        splash = list(connector.list_pages(tag='splash'))
        for url in ('scp-series', 'scp-series-2', 'scp-series-3'):
            for element in bs4.BeautifulSoup(
                    connector(url).html).select('ul > li'):
                if not re.search('[SCP]+-[0-9]+', element.text):
                    continue
                url = connector.site + element.a['href']
                try:
                    skip, title = element.text.split(' - ', maxsplit=1)
                except ValueError:
                    skip, title = element.text.split(', ', maxsplit=1)
                if url in splash:
                    url = '{}/{}'.format(connector.site, skip.lower())
                yield url, title

    @property
    def _onpage_title(self):
        """Title as displayed on the page."""
        title = bs4.BeautifulSoup(self.html).find(id='page-title')
        return title.text.strip() if title else ''

    def _get_adapter_value(self, name):
        if name not in self._cache:
            self._cache.update(getattr(self._cn.adapter, 'get_' + name)(self))
        return self._cache[name]

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def page_id(self):
        return self._get_adapter_value('page_id')

    @property
    def thread_id(self):
        return self._get_adapter_value('thread_id')

    @property
    def html(self):
        return self._get_adapter_value('html')

    @property
    def source(self):
        return self._get_adapter_value('source')

    @property
    def history(self):
        return self._get_adapter_value('history')

    @property
    def votes(self):
        return self._get_adapter_value('votes')

    @property
    def tags(self):
        return self._get_adapter_value('tags')

    @property
    def posts(self):
        return self._get_adapter_value('posts')

    ###########################################################################

    @property
    def comments(self):
        return self.posts

    @property
    def text(self):
        return bs4.BeautifulSoup(self.html).find(id='page-content').text

    @property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    @property
    def images(self):
        return [i['src'] for i in bs4.BeautifulSoup(self.html)('img')]

    @property
    def title(self):
        if 'scp' in self.tags and re.search('[scp]+-[0-9]+$', self.url):
            try:
                return '{}: {}'.format(
                    self._onpage_title, self._scp_titles(self._cn)[self.url])
            except KeyError:
                pass
        return self._onpage_title

    @property
    def created(self):
        return self.history[0].time

    @property
    def author(self):
        for over in self._cn.list_overrides():
            if over.url == self.url and over.type == 'author':
                return over.user
        return self.history[0].user

    @property
    def rewrite_author(self):
        for over in self._cn.list_overrides():
            if over.url == self.url and over.type == 'rewrite_author':
                return over.user

    @property
    def rating(self):
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

    @property
    @utils.listify()
    def links(self):
        unique = set()
        for element in bs4.BeautifulSoup(self.html).select('#page-content a'):
            href = element.get('href', None)
            if (not href or href[0] != '/' or  # bad or absolute link
                    href[-4:] in ('.png', '.jpg', '.gif')):
                continue
            url = self._cn.site + href.rstrip('|')
            if url not in unique:
                unique.add(url)
                yield url


###############################################################################
# Simple Containers
###############################################################################

nt = collections.namedtuple
Revision = nt('Revision', 'id number user time comment')
Vote = nt('Vote', 'user value')
ForumPost = nt('ForumPost', 'id title content user time parent')
Override = nt('Override', 'url user type')
ForumCategory = nt('ForumCategory', 'id title description size')
ForumThread = nt('ForumThread', 'id title description')
Image = nt('Image', 'url source status notes')
del nt

###############################################################################
# Helper Functions
###############################################################################


def full_url(url):
    """Return the url with any missing segments filled in."""
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc if parsed.netloc else parsed.path
    if '.' not in netloc:
        netloc += '.wikidot.com'
    return urllib.parse.urlunparse(['http', netloc, '', '', '', ''])
