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
from collections import namedtuple, defaultdict
from pyscp import orm
from pyscp.utils import listify
from urllib.parse import urlparse, urlunparse, urljoin
from functools import lru_cache, wraps

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('pyscp')

###############################################################################
# Utility Classes
###############################################################################


class InsistentRequest(requests.Session):

    """Make an auto-retrying request that handles connection loss."""

    def __init__(self, max_attempts=10):
        super().__init__()
        self.max_attempts = max_attempts

    def request(self, method, url, **kwargs):
        log_message = '<{} request>: {}'.format(method, url)
        if kwargs:
            log_message += ' {}'.format(kwargs)
        log.debug(log_message)
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
        page_id = re.search('pageId = ([0-9]+);', html)
        return int(page_id.group(1)) if page_id is not None else None

    def _thread_id(self, page_id, html):
        link = bs4(html).find(id='discuss-button')
        if not link or link['href'] == 'javascript:;':
            return None
        else:
            return int(link['href'].split('/')[2].split('-')[1])

    def _html(self, url):
        """Download the html data of the page."""
        try:
            return self.req.get(url).text
        except (requests.ConnectionError, requests.HTTPError) as error:
            message = 'Failed to get the page: {}'.format(error)
            log.warning(message)
            raise ConnectorError(message)

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
        for elem in reversed(bs4(data)('tr')[1:]):
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
                value=int(
                    value.text.strip().replace('+', '1').replace('-', '-1')))

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
            if 'body' not in page:
                raise ConnectorError(page['message'])
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

    def _list(self, **kwargs):
        """Yield urls of the pages matching the specified criteria."""
        for page in self._pager(
                'list/ListPagesModule',
                _next=lambda x: {'offset': 250 * (x - 1)},
                category='*',
                limit=kwargs.get('limit', None),
                tags=kwargs.get('tag', None),
                rating=kwargs.get('rating', None),
                created_by=kwargs.get('author', None),
                order=kwargs.get('order', 'title'),
                module_body='%%title_linked%%',
                perPage=250):
            for elem in bs4(page['body']).select('div.list-pages-item a'):
                yield self.site + elem['href']

    def list_pages(self, **kwargs):
        pages = self._list(**kwargs)
        author = kwargs.pop('author', None)
        if not author or not kwargs:
            yield from pages
            return
        include, exclude = [], []
        for i in self.rewrites():
            if i['author'] == author:
                include.append(i['url'])
            elif i['status'] == 'override':
                exclude.append(i['url'])
        pages = list(pages)
        for url in self._list(**kwargs):
            if url in pages or url in include and url not in exclude:
                yield url

    def categories(self):
        """Yield dicts describing all forum categories on the site."""
        for elem in (
                bs4(self._module('forum/ForumStartModule')['body'])
                (class_='name')):
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
            page = self._html(
                'http://scpsandbox2.wikidot.com/image-review-{}'.format(index))
            if page is None:
                break
            for elem in bs4(page)('tr'):
                if not elem('td'):
                    continue
                source = elem('td')[3].find('a')
                status = elem('td')[4].text
                notes = elem('td')[5].text
                yield dict(
                    url=elem('td')[0].img['src'],
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
        except (requests.ConnectionError, requests.HTTPError) as error:
            message = (
                'Failed module call ({} - {} - {}): {}'
                .format(name, page_id, kwargs, error))
            log.warning(message)
            raise ConnectorError(message)

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
            yield dict(
                post_id=int(elem['id'].split('-')[1]),
                title=title if title else None,
                content=str(content),
                user=elem.find(class_='printuser').text,
                time=arrow.get(time).format('YYYY-MM-DD HH:mm:ss'),
                parent=int(parent) if parent else None)

    def _pager(self, name, _next, **kwargs):
        """Iterate over multi-page module results."""
        first_page = self._module(name, **kwargs)
        yield first_page
        counter = bs4(first_page['body']).find(class_='pager-no')
        if counter:
            for index in range(2, int(counter.text.split(' ')[-1]) + 1):
                kwargs.update(_next(index))
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
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=20)
        self._remap_queue = defaultdict(list)

    def __call__(self, url):
        return Page(url, self)

    def __repr__(self):
        return "{}('{}', '{}')".format(
            self.__class__.__name__,
            urlparse(self.site).netloc.replace('.wikidot.com', ''),
            self.dbpath)

    ###########################################################################
    # Decorators
    ###########################################################################

    def _must_exist(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except orm.peewee.DoesNotExist:
                raise ConnectorError(
                    'The requested page does not exist in the snapshot.')
        return wrapped

    ###########################################################################
    # Connector Page API
    ###########################################################################

    @_must_exist
    def _page_id(self, url, html):
        return orm.Page.get(orm.Page.url == url).id

    @_must_exist
    def _thread_id(self, page_id, html):
        return orm.Page.get(orm.Page.id == page_id).thread.id

    @_must_exist
    def _html(self, url):
        return orm.Page.get(orm.Page.url == url).html

    @_must_exist
    def _history(self, page_id):
        for revision in orm.Page.get(orm.Page.id == page_id).revisions:
            yield dict(
                revision_id=revision.id,
                page_id=page_id,
                number=revision.number,
                user=revision.user.name,
                time=str(revision.time),
                comment=revision.comment)

    @_must_exist
    def _votes(self, page_id):
        for vote in orm.Page.get(orm.Page.id == page_id).votes:
            yield dict(page_id=page_id, user=vote.user.name, value=vote.value)

    def _tags(self, page_id, html):
        for tag in orm.Page.get(orm.Page.id == page_id).tags:
            yield tag.tag.name

    ###########################################################################

    def _posts(self, thread_id):
        for post in orm.ForumThread.get(orm.ForumThread.id == thread_id).posts:
            yield dict(
                thread_id=thread_id,
                post_id=post.id,
                title=post.title,
                content=post.content,
                user=post.user.name,
                time=str(post.time),
                parent=post.parent)

    ###########################################################################
    # Connector Public API
    ###########################################################################

    def auth(self, username, password):
        return self.wiki.auth(username, password)

    def _list_author(self, author):
        query = (
            orm.Page.select(orm.Page.url)
            .join(orm.Revision).join(orm.User)
            .where(orm.Revision.number == 0)
            .where(orm.User.name == author))
        include, exclude = [], []
        for item in self.rewrites():
            if item['author'] == author:
                include.append(item['url'])
            elif item['status'] == 'override':
                exclude.append(item['url'])
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
        if 'tag' in kwargs:
            query = query & (
                orm.Page.select(orm.Page.url)
                .join(orm.PageTag).join(orm.Tag)
                .where(orm.Tag.name == kwargs['tag']))
        if 'author' in kwargs:
            query = query & self._list_author(kwargs['author'])
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

    def rewrites(self):
        for row in orm.Rewrite.select():
            try:
                yield dict(
                    url=row.page.url,
                    author=row.user.name,
                    status=row.status.name)
            except orm.peewee.DoesNotExist:
                pass

    def images(self):
        for row in orm.Image.select():
            yield dict(
                url=row.url, source=row.source, status=row.status,
                notes=row.notes, data=row.data)

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _save_pages(self):
        for i in (
                orm.Page, orm.Revision, orm.Vote, orm.ForumPost,
                orm.PageTag, orm.ForumThread):
            i.create_table()
        for _ in self.pool.map(
                self._save_page, self.wiki.list_pages(), itertools.count(1)):
            pass

    def _save_page(self, url, index):
        """Download the page and write it to the db."""
        log.info('Saving page {}: {}'.format(index, url))
        try:
            html = self.wiki._html(url)
        except ConnectorError:
            return
        page_id = self.wiki._page_id(None, html)
        thread_id = self.wiki._thread_id(None, html)
        orm.Page.create(
            id=page_id,
            url=url,
            thread=thread_id,
            html=str(bs4(html).find(id='main-content')))
        orm.Revision.insert_many(dict(
            id=i['revision_id'],
            page=page_id,
            user=self._remap(orm.User, i['user']),
            number=i['number'],
            time=i['time'],
            comment=i['comment'])
            for i in self.wiki._history(page_id))
        orm.Vote.insert_many(dict(
            page=page_id,
            user=self._remap(orm.User, i['user']),
            value=i['value'])
            for i in self.wiki._votes(page_id))
        self._save_thread(dict(thread_id=thread_id))
        orm.PageTag.insert_many(dict(
            page=page_id,
            tag=self._remap(orm.Tag, i))
            for i in self.wiki._tags(None, html))

    def _remap(self, orm_cls, item):
        if item in self._remap_queue[orm_cls]:
            return self._remap_queue[orm_cls].index(item) + 1
        self._remap_queue[orm_cls].append(item)
        return len(self._remap_queue[orm_cls])

    def _save_remaps(self):
        for orm_cls, items in self._remap_queue.items():
            orm_cls.create_table()
            orm_cls.insert_many(dict(
                id=index + 1,
                name=name) for index, name in enumerate(items))

    def _save_forums(self):
        """Download and save standalone forum threads."""
        orm.ForumPost.create_table(True)
        orm.ForumThread.create_table(True)
        orm.ForumCategory.create_table(True)
        categories = [
            i for i in self.wiki.categories()
            if i['title'] != 'Per page discussions']
        log.info('Saving Forum Categories.')
        for i in categories:
            orm.ForumCategory.create(
                id=i['category_id'],
                title=i['title'],
                description=i['description'])
        threads = (
            i for j in categories for i in self.wiki.threads(j['category_id']))
        for _ in self.pool.map(
                self._save_thread, threads, itertools.count(1),
                itertools.repeat(sum([i['threads'] for i in categories]))):
            pass

    def _save_thread(self, thread, index=None, total=None):
        if index:
            log.info('Saving thread {}/{}: {}'.format(
                index, total, thread['title']))
        orm.ForumThread.create(
            id=thread['thread_id'],
            category=thread.get('category_id', None),
            title=thread.get('title', None),
            description=thread.get('description', None))
        orm.ForumPost.insert_many(dict(
            id=i['post_id'],
            thread=thread['thread_id'],
            user=self._remap(orm.User, i['user']),
            parent=i['parent'],
            title=i['title'],
            time=i['time'],
            content=i['content'])
            for i in self.wiki._posts(thread['thread_id']))

    def _save_meta(self):
        log.info('Downloading image metadata.')
        orm.Image.create_table()
        images = [i for i in self.wiki.images() if i['status'] in (
            'PERMISSION GRANTED',
            'BY-NC-SA CC',
            'BY-SA CC',
            'PUBLIC DOMAIN')]
        for _ in self.pool.map(
                self._save_image, images, itertools.count(1),
                itertools.repeat(len(images))):
            pass
        log.info('Downloading author metadata.')
        orm.Rewrite.create_table()
        orm.Rewrite.insert_many(dict(
            page=i['url'],
            user=self._remap(orm.User, i['author']),
            status=self._remap(orm.RewriteStatus, i['status']))
            for i in self.wiki.rewrites())

    def _save_image(self, image, index, total):
        if not image['source']:
            log.info(
                'Aborted image {}: source not specified: {}'
                .format(index, image))
            return
        log.info('Saving image {}/{}.'.format(index, total))
        try:
            data = self.wiki.req.get(image['url']).content
        except requests.HTTPError as err:
            log.warning('Failed to download the image: {}'.format(err))
            return
        orm.Image.create(
            url=image['url'],
            source=image['source'],
            data=data,
            status=self._remap(orm.ImageStatus, image['status']),
            notes=image['notes'])

    ###########################################################################
    # Public Methods
    ###########################################################################

    def take_snapshot(self, include_forums=False):
        time_start = arrow.now()
        orm.purge()
        self._save_pages()
        if include_forums:
            self._save_forums()
        if 'scp-wiki' in self.site:
            self._save_meta()
        self._save_remaps()
        time_taken = (arrow.now() - time_start)
        hours, remainder = divmod(time_taken.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = 'Snapshot succesfully taken. [{:02d}:{:02d}:{:02d}]'
        msg = msg.format(hours, minutes, seconds)
        log.info(msg)


class Page:

    """ """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, url, connector):
        if not urlparse(url).netloc:
            url = '{}/{}'.format(connector.site, url)
        self.url = url.lower()
        self._cn = connector

    def __repr__(self):
        short = self.url.replace(self._cn.site, '').lstrip('/')
        cls_name = self.__class__.__name__
        return "{}('{}', {})".format(cls_name, short, repr(self._cn))

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _flush(self, *properties):
        for i in properties:
            if i in self._cache:
                del self._cache[i]

    @classmethod
    @lru_cache()
    @listify(wrapper=dict)
    def _scp_titles(cls, connector):
        log.debug('Constructing title index.')
        splash = list(connector.list_pages(tag='splash'))
        for url in ('scp-series', 'scp-series-2', 'scp-series-3'):
            for element in bs4(connector(url).html).select('ul > li'):
                if not re.search('[SCP]+-[0-9]+', element.text):
                    continue
                url = connector.site + element.a['href']
                try:
                    skip, title = element.text.split(' - ', maxsplit=1)
                except ValueError:
                    skip, title = element.text.split(', ', maxsplit=1)
                if url not in splash:
                    yield url, title
                else:
                    yield '{}/{}'.format(connector.site, skip.lower()), title

    @property
    def _onpage_title(self):
        """Title as displayed on the page."""
        title = bs4(self.html).find(id='page-title')
        return title.text.strip() if title else ''

    ###########################################################################
    # Core Properties
    ###########################################################################

    @cached_property
    def page_id(self):
        return self._cn._page_id(self.url, self.html)

    @cached_property
    def thread_id(self):
        return self._cn._thread_id(self.page_id, self.html)

    @cached_property
    def html(self):
        return self._cn._html(self.url)

    @cached_property
    def source(self):
        return self._cn._source(self.page_id)

    @cached_property
    def history(self):
        data = self._cn._history(self.page_id)
        Revision = namedtuple(
            'Revision', 'revision_id page_id number user time comment')
        history = [Revision(**i) for i in data]
        return list(sorted(history, key=lambda x: x.number))

    @cached_property
    def votes(self):
        data = self._cn._votes(self.page_id)
        Vote = namedtuple('Vote', 'page_id user value')
        return [Vote(**i) for i in data]

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
        if 'scp' in self.tags and re.search('[scp]+-[0-9]+$', self.url):
            return '{}: {}'.format(
                self._onpage_title, self._scp_titles(self._cn)[self.url])
        return self._onpage_title

    @property
    def created(self):
        return self.history[0].time

    @property
    def authors(self):
        Author = namedtuple('Author', 'user status')
        first_author = Author(self.history[0].user, 'original')
        for item in self._cn.rewrites():
            if item['url'] == self.url:
                new_author = Author(item['author'], item['status'])
                return [first_author, new_author]
        else:
            return [first_author]

    @property
    def author(self):
        if len(self.authors) == 1 or self.authors[1].status == 'rewrite':
            return self.authors[0].user
        else:
            return self.authors[1].user

    @property
    def rating(self):
        if not self.votes:
            return None
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

    @property
    @listify
    def links(self):
        if self.html is None:
            return []
        unique = []
        for a in bs4(self.html).find(id='page-content')('a'):
            href = a.get('href', None)
            if not href or href[0] != '/':  # bad or absolute link
                continue
            if href[-4:] in ('.png', '.jpg', '.gif'):  # link to image
                continue
            url = self._cn.site + href.rstrip('|')
            if url not in unique:
                unique.append(url)
                yield url

    ###########################################################################
    # Methods
    ###########################################################################

    def edit(self, source, title=None, comment=None):
        if title is None:
            title = self._onpage_title
        self._cn._edit(self.page_id, self.url, source, title, comment)
        self._flush('html', 'history', 'source')

    def revert_to(self, rev_n):
        self._cn._revert_to(self.page_id, self.history[rev_n].revision_id)
        self._flush('html', 'history', 'source', 'tags')

    def set_tags(self, tags):
        self._cn._set_tags(self.page_id, tags)
        self._flush('html', 'history', 'tags')

    def cancel_vote(self):
        self._cn._set_vote(self, 0)
        self._flush('votes')

    def upvote(self, force=False):
        self._cn._set_vote(self, 1, force)
        self._flush('votes')

    def downvote(self, force=False):
        self._cn._set_vote(self, -1, force)
        self._flush('votes')


class ForumThread:

    def __init__(self, thread_id, title, description, posts):
        self.thread_id = thread_id
        self.title = title
        self.description = description
        self.posts = sorted(posts, key=lambda x: x.time)

    def __repr__(self):
        return '{}(thread_id={}, title={}, description={}, posts={})'.format(
            self.__class__.__name__,
            self.thread_id, self.title, self.description, self.posts)

    def __getitem__(self, index):
        return self.posts[index]

    def __len__(self):
        return len(self.posts)

    def tree(self):
        tree = []
        for i in self.posts:
            if not i.parent:
                tree.append(i)
            else:
                for index, j in enumerate(tree):
                    if j.post_id == i.parent:
                        tree.insert(index + 1, i)
                        break
        return tree


class ForumPost(namedtuple(
        'ForumPostBase',
        'post_id thread_id parent title user time content')):

    def __str__(self):
        snippet_len = 75 - len(self.user)
        text = self.text.replace('\n', ' ').strip()
        if len(text) <= snippet_len + 1:
            snippet = text
        else:
            snippet = text[:snippet_len] + '…'
        return '<{}: {}>'.format(self.user, snippet)

    @property
    def text(self):
        return bs4(self.content).text.strip()

    @property
    def wordcount(self):
        return len(self.text.split())


###############################################################################
# Module-level Functions
###############################################################################


def use_default_logging(debug=False):
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logfile = logging.FileHandler('scp.log', mode='w', delay=True)
    logfile.setLevel(logging.WARNING)
    logfile.setFormatter(logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'))
    logger = logging.getLogger('pyscp')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console)
    logger.addHandler(logfile)
