#!/usr/bin/env python3

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

    @utils.log_calls(log.debug)
    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    @utils.log_calls(log.debug)
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
        self.site = full_url(site)
        self.req = InsistentRequest()
        self.adapter = functools.partial(WikidotPageAdapter, self)

    def __call__(self, url):
        """Convinience method to quickly create Page instances."""
        return Page(url, self)

    def __repr__(self):
        return "{}({})".format(
            self.__class__.__name__,
            repr(self.site[7:].replace('.wikidot.com', '')))

    ###########################################################################

    def _edit(self, page_id, url, source, title, comment):
        """Overwrite the page with the new source and title."""
        lock = self._module(
            'edit/PageEditModule',
            page_id=page_id,
            mode='page')
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
        data = dict(login=username,
                    password=password,
                    action='Login2Action',
                    event='login')
        return self.req.post(
            'https://www.wikidot.com/default--flow/login__LoginPopupScreen',
            data=data)

    def _list_pages_base(self, **kwargs):
        """
        Call ListPages module.

        Wikidot's ListPages is an extremely versatile php module that can be
        used to retrieve all sorts of interesting informations, from urls of
        pages created by a given user, and up to full html contents of every
        page on the site.

        This method returns the raw data returned by the ListPages module.
        The data is later processed by WikidotConnector.list_pages module.
        """
        yield from self._pager(
            'list/ListPagesModule',
            _key='offset',
            _update=lambda x: 250 * (x - 1),
            category='*',
            limit=kwargs.get('limit', None),
            tags=kwargs.get('tag', None),
            rating=kwargs.get('rating', None),
            created_by=kwargs.get('author', None),
            order=kwargs.get('order', 'title'),
            module_body=kwargs.get('body', '%%title_linked%%'),
            perPage=250)

    def _extract_urls(self, pages):
        """
        Return the urls from the list_pages.

        Lazily extracts urls from the html data returned when list_pages is
        called without specifying the 'body' keyword.
        """
        soups = (bs4.BeautifulSoup(p['body']) for p in pages)
        elems = (s.select('div.list-pages-item a') for s in soups)
        yield from (self.site + e['href'] for e in itertools.chain(*elems))

    def list_pages(self, **kwargs):
        """
        Return urls matching the specified criteria.

        This method uses the results of the ListPages module and the custom
        override data to correctly return urls for pages that have been
        rewritten or have author that differs from the 0th revision for
        some other reasons.
        """
        pages = self._list_pages_base(**kwargs)
        if 'body' in kwargs:
            # if 'body' is specified, return raw pages
            yield from pages
        urls = self._extract_urls(pages)
        author = kwargs.pop('author', None)
        if not author:
            # if 'author' isn't specified, there's no need to check rewrites
            yield from urls
            return
        include, exclude = set(), set()
        for over in self.list_overrides():
            if over.user == author:
                # if username matches, include regardless of type
                include.add(over.url)
            elif over.type == 'author':
                # exclude only if override type is author.
                # if url has author and rewrite author,
                # it will appear in list_pages for both.
                exclude.add(over.url)
        urls = set(urls) | include - exclude
        # if no other options beside author were specified,
        # just return everything we can
        if not kwargs:
            yield from urls
            return
        # otherwise, make an additional ListPages request to check
        # which urls from include we should return and in which order
        for url in self._extract_urls(self._list_pages_base(**kwargs)):
            if url in urls:
                yield url

    def categories(self):
        """Yield dicts describing all forum categories on the site."""
        data = self._module('forum/ForumStartModule')['body']
        for elem in bs4.BeautifulSoup(data)(class_='name'):
            yield dict(
                category_id=int(elem.find(class_='title').a['href']
                                .split('/')[2].split('-')[1]),
                title=elem.select('div.title')[0].text.strip(),
                threads=int(elem.parent.select('td.threads')[0].text),
                description=elem.select('div.description')[0].text.strip())

    def threads(self, category_id):
        """Yield dicts describing all threads in a given category."""
        for page in self._pager('forum/ForumViewCategoryModule',
                                lambda x: dict(p=x), c=category_id):
            for elem in bs4.BeautifulSoup(page['body'])(class_='name'):
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
            options=dict(all=True), page=1, perpage=number)['body']
        for elem in bs4.BeautifulSoup(data)(class_='changes-list-item'):
            revnum = elem.find('td', 'revision-no').text.strip()
            comment = elem.find('div', 'comments')
            yield dict(
                url=self.site + elem.find('td', 'title').a['href'],
                number=0 if revnum == '(new)' else int(revnum[6:-1]),
                user=elem.find('span', 'printuser').text.strip(),
                time=parse_time(elem),  # TODO: fix
                comment=comment.text.strip() if comment else None)

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    @functools.lru_cache(maxsize=1)
    @utils.listify()
    def list_overrides(self):
        if 'scp-wiki' not in self.site:
            return None
        urls = 'http://05command.wikidot.com/alexandra-rewrite'
        soup = bs4.BeautifulSoup(self.req.get(urls).text)
        for row in [r('td') for r in soup('tr')[1:]]:
            url = '{}/{}'.format(self.site, row[0].text)
            user = row[1].text.split(':override:')[-1]
            if ':override:' in row[1].text:
                type_ = 'author'
            else:
                type_ = 'rewrite_author'
            yield Override(url, user, type_)

    @functools.lru_cache(maxsize=1)
    @utils.listify()
    def images(self):
        if 'scp-wiki' not in self.site:
            return None
        for index in range(1, 28):
            page = self._html(
                'http://scpsandbox2.wikidot.com/image-review-{}'.format(index))
            for elem in bs4.BeautifulSoup(page)('tr'):
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

    @utils.morph(requests.RequestException, ConnectorError)
    @utils.log_errors(log.warning)
    def _module(self, name, **kwargs):
        """
        Call a Wikidot module.

        This method is responsible for most of the class' functionality.
        Almost all other methods of the class are using _module in one way
        or another.
        """
        return self.req.post(
            self.site + '/ajax-module-connector.php',
            data=dict(
                pageId=kwargs.get('page_id', None),  # fuck wikidot
                moduleName=name,
                # token7 can be any 6-digit number, as long as it's the same
                # in the payload and in the cookie
                wikidot_token7='123456',
                **kwargs),
            headers={'Content-Type': 'application/x-www-form-urlencoded;'},
            cookies={'wikidot_token7': '123456'}).json()

    def _page_action(self, page_id, event, **kwargs):
        return self._module('Empty', action='WikiPageAction',
                            page_id=page_id, event=event, **kwargs)

    def _pager(self, name, _key, _update=None, **kwargs):
        """Iterate over multi-page module results."""
        first_page = self._module(name, **kwargs)
        yield first_page
        counter = bs4.BeautifulSoup(first_page['body']).find(class_='pager-no')
        if not counter:
            return
        for idx in range(2, int(counter.text.split(' ')[-1]) + 1):
            kwargs.update({_key: idx if _update is None else _update(idx)})
            yield self._module(name, **kwargs)


class WikidotPageAdapter:

    """
    Retrieve data about the page.

    Page Adapters are used by the Page class to gain information pertaining to
    a specific page. They request raw data from their respective Connectors and
    format it in a manner that is expected by the Page class.

    The Adapters are also responsible for caching and any other optimizations,
    depending on the connector.

    This class supports the following fields:

    - page_id
    - thread_id
    - html
    - history
    - votes
    - tags
    - source

    """

    def __init__(self, connector, page):
        self.cn = connector
        self.page = page

    ###########################################################################
    # Private Methods
    ###########################################################################

    @utils.morph(requests.RequestException, ConnectorError)
    @utils.log_errors(log.warning)
    @functools.lru_cache(maxsize=1)
    def _load_page(self):
        """
        Download the page and extract data from the html.

        Returns a tuple consisting of the id of the page, id of the comment
        thread, stripped-down html string, and a set of tags. The tuple is
        saved via lru_cache, and the individual get_ methods can then
        take the parts of the tuple they need.
        """
        html = self.cn.req.get(self.page.url).text
        page_id = int(re.search('pageId = ([0-9]+);', html).group(1))
        soup = bs4.BeautifulSoup(html)
        href = soup.find(id='discuss-button')['href']
        thread_id = int(href.split('/')[2].split('-')[1])
        tags = {e.text for e in soup.select('.page-tags a')}
        clean_html = str(soup.find(id='main-content'))
        return (page_id, thread_id, clean_html, tags)

    @staticmethod
    def _parse_time(element):
        """Extract and format time from an html element."""
        unixtime = element.find(class_='odate')['class'][1].split('_')[1]
        return arrow.get(unixtime).format('YYYY-MM-DD HH:mm:ss')

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

    def get_page_id(self):
        """Return the id of the page."""
        return self._load_page()[0]

    def get_thread_id(self):
        """Return the id of the discussion thread."""
        return self._load_page()[1]

    def get_html(self):
        """Return the html source of the page."""
        return self._load_page()[2]

    @functools.lru_cache(maxsize=1)
    @utils.listify()
    def get_history(self):
        """Return the revision history of the page."""
        data = self.cn._module(
            'history/PageRevisionListModule',
            page_id=self.page.page_id,
            page=1,
            perpage=99999)['body']
        soup = bs4.BeautifulSoup(data)
        for row in reversed(soup('tr')[1:]):
            rev_id = int(row['id'].split('-')[-1])
            cells = row('td')
            number = int(cells[0].text.strip('.'))
            user = cells[4].text
            time = self._parse_time(cells[5])
            comment = cells[6].text
            if not comment:
                comment = None
            yield Revision(rev_id, number, user, time, comment)

    @functools.lru_cache(maxsize=1)
    def get_votes(self):
        """Return all votes made on the page."""
        data = self.cn._module(
            'pagerate/WhoRatedPageModule',
            page_id=self.page.page_id)['body']
        soup = bs4.BeautifulSoup(data)
        spans = [i.text.strip() for i in soup('span')]
        pairs = zip(spans[::2], spans[1::2])
        return [Vote(user=u, value=1 if v == '+' else -1) for u, v in pairs]

    def get_tags(self):
        return self._load_page()[3]

    @functools.lru_cache(maxsize=1)
    @utils.listify()
    def get_posts(self):
        """Download and parse the contents of the forum thread."""
        if self.page.thread_id is None:
            return
        pages = self.cn._pager(
            'forum/ForumViewThreadPostsModule',
            _key='pageNo',
            t=self.page.thread_id)
        pages = [bs4.BeautifulSoup(p['body']).body for p in pages]
        posts = [p(class_='post-container', recursive=False) for p in pages]
        posts = itertools.chain(*posts)
        for post, parent in self._crawl_posts(list(posts)):
            post_id = int(post['id'].split('-')[1])
            title = post.find(class_='title').text.strip()
            if not title:
                title = None
            content = post.find(class_='content')
            content.attrs.clear()
            content = str(content)
            user = post.find(class_='printuser').text
            time = self._parse_time(post)
            yield ForumPost(post_id, title, content, user, time, parent)

    @functools.lru_cache(maxsize=1)
    def get_source(self):
        """Return wikidot markup of the source."""
        data = self.cn._module(
            'viewsource/ViewSourceModule',
            page_id=self.page.page_id)['body']
        soup = bs4.BeautifulSoup(data)
        return soup.text[11:].strip().replace(chr(160), ' ')


class SnapshotConnector:

    """
    """

    def __init__(self, site, dbpath):
        if not pathlib.Path(dbpath).exists():
            raise FileNotFoundError(dbpath)
        self.site = full_url(site)
        self.dbpath = dbpath
        self.adapter = functools.partial(SnapshotPageAdapter, self)
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

    def list_urls(self, **kwargs):
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
    def rewrites(self):
        for row in orm.Rewrite.select():
            try:
                yield dict(
                    url=row.page.url,
                    author=row.user.name,
                    status=row.status.label)
            except orm.peewee.DoesNotExist:
                pass

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
        orm.purge()
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
        for _ in utils.pbar(
                self.pool.map(self._save_page, self.wiki.list_urls()),
                'SAVING PAGES'.ljust(20), count):
            pass

    @utils.ignore(ConnectorError)
    def _save_page(self, url):
        """Download contents, revisions, votes and discussion of the page."""
        html = self.wiki._html(url)
        page_id = self.wiki._page_id(None, html)
        thread_id = self.wiki._thread_id(None, html)
        orm.Page.create(
            id=page_id,
            url=url,
            thread=thread_id,
            html=str(bs4.BeautifulSoup(html).find(id='main-content')))
        orm.Revision.insert_many(dict(
            id=i['revision_id'],
            page=page_id,
            user=orm.User.get_id(i['user']),
            number=i['number'],
            time=i['time'],
            comment=i['comment']) for i in self.wiki._history(page_id))
        orm.Vote.insert_many(dict(
            page=page_id,
            user=orm.User.get_id(i['user']),
            value=i['value']) for i in self.wiki._votes(page_id))
        self._save_thread(dict(thread_id=thread_id))
        orm.PageTag.insert_many(dict(
            page=page_id,
            tag=orm.Tag.get_id(i)) for i in self.wiki._tags(None, html))

    def _save_forums(self):
        """Download and save standalone forum threads."""
        orm.create_tables('ForumPost', 'ForumThread', 'ForumCategory', 'User')
        cats = self.wiki.categories()
        cats = [i for i in cats if i['title'] != 'Per page discussions']
        orm.ForumCategory.insert_many(dict(
            id=i['category_id'],
            title=i['title'],
            description=i['description'])
            for i in cats)
        total = sum(i['threads'] for i in cats)
        threads = itertools.chain.from_iterable(
            self.wiki.threads(i['category_id']) for i in cats)
        for _ in utils.pbar(
                self.pool.map(self._save_thread, threads),
                'SAVING FORUM THREADS'.ljust(20), total):
            pass

    def _save_thread(self, thread):
        orm.ForumThread.create(
            id=thread['thread_id'],
            category=thread.get('category_id', None),
            title=thread.get('title', None),
            description=thread.get('description', None))
        orm.ForumPost.insert_many(dict(
            id=i['post_id'],
            thread=thread['thread_id'],
            user=orm.User.get_id(i['user']),
            parent=i['parent'],
            title=i['title'],
            time=i['time'],
            content=i['content'])
            for i in self.wiki._posts(thread['thread_id']))

    def _save_meta(self):
        log.info('Downloading image metadata.')
        orm.create_tables('Image', 'ImageStatus', 'Rewrite', 'RewriteStatus')
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
        orm.Rewrite.insert_many(dict(
            page=i['url'],
            user=orm.User.get_id(i['author']),
            status=orm.RewriteStatus.get_id(i['status']))
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
            status=orm.ImageStatus.get_id(image['status']),
            notes=image['notes'])

    def _save_id_cache(self):
        for table_name, field_name in zip(
                ('User', 'Tag', 'RewriteStatus', 'ImageStatus'),
                ('name', 'name', 'label', 'label')):
            table = getattr(orm, table_name)
            if table.table_exists():
                table.write_ids(field_name)


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

    def __init__(self, connector, page):
        self.cn = connector
        self.page = page

    ###########################################################################
    # Private Methods
    ###########################################################################

    @functools.lru_cache(maxsize=4)
    def _query(self, primary_table, secondary_table='User', key='page'):
        """Generate SQL queries used to retrieve data."""
        pt = getattr(orm, primary_table)
        st = getattr(orm, secondary_table)
        return pt.select(pt, st.name).join(st).where(
            getattr(pt, key) == getattr(self.page, key + '_id')).execute()

    # Only need to morph this methods, because *all* other methods
    # will eventually call it, and then the exception will bubble up.
    @utils.morph(orm.peewee.DoesNotExist, ConnectorError)
    @functools.lru_cache(maxsize=1)
    def _load_page(self):
        """
        Retrieve the contents of the page.

        Returns a tuple consisting of the id of the page, id of the comment
        thread, and the html string.The tuple is saved via lru_cache, and the
        individual get_ methods then take whichever part of the tuple they
        need.

        The idea here is that most of the time, you will be needing all three
        of those, so it's better to get them all in a single query. This also
        mirrors the behavior of WikidotPageAdapter, which does a similar
        thing for very different reason.
        """
        page = orm.Page.get(orm.Page.url == self.page.url)
        return (page.id, page._data['thread'], page.html)

    ###########################################################################
    # Public Methods
    ###########################################################################

    def get_page_id(self):
        """Retrieve the id of the page."""
        return self._load_page()[0]

    def get_thread_id(self):
        """
        Retrieve the id of the comments thread of the page.

        If the page has no comments, returns None.
        """
        return self._load_page()[1]

    def get_html(self):
        """
        Retrieve the html source of the page.
        """
        return self._load_page()[2]

    def get_history(self):
        """Return the revisions of the page."""
        revs = sorted(
            self._query('Revision'), key=operator.attrgetter('number'))
        return [Revision(r.id, r.number, r.user.name, str(r.time), r.comment)
                for r in revs]

    def get_votes(self):
        """Return all votes made on the page."""
        return [Vote(v.user.name, v.value) for v in self._query('Vote')]

    def get_tags(self):
        """Return the set of tags with which the page is tagged."""
        return {pt.tag.name for pt in self._query('PageTag', 'Tag')}

    def get_posts(self):
        """
        Return the page comments.

        This is also the only Adapter method to work on ForumThread objects,
        for which it returns the posts contained in the forum thread.
        """
        return [ForumPost(
                p.id, p.title, p.content, p.user.name,
                str(p.time), p._data['parent'])
                for p in self._query('ForumPost', key='thread')]

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
        self._adapter = connector.adapter(self)

    def __repr__(self):
        return "{}({}, {})".format(
            self.__class__.__name__,
            repr(self.url.replace(self.cn.site, '').lstrip('/')),
            self.cn)

    def __getattr__(self, name):
        if name not in (  # this has saved 85 lines of boilerplate defs
                'page_id', 'thread_id', 'html', 'source',
                'history', 'votes', 'tags', 'posts'):
            raise AttributeError
        return getattr(self._adapter, 'get_' + name)()

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _flush(self, *properties):
        pass
        #for i in properties:
        #    if i in self._cache:
        #        del self._cache[i]

    @classmethod
    @functools.lru_cache()
    @utils.listify(dict)
    def _scp_titles(cls, connector):
        log.debug('Constructing title index.')
        splash = list(connector.list_urls(tag='splash'))
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

    ###########################################################################
    # Properties
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
            return '{}: {}'.format(
                self._onpage_title, self._scp_titles(self.cn)[self.url])
        return self._onpage_title

    @property
    def created(self):
        return self.history[0].time

    @property
    def author(self):
        for item in self.cn.rewrites():
            if item['url'] == self.url and item['status'] == 'override':
                return item['author']
        return self.history[0].user

    @property
    def rewrite_author(self):
        for item in self._cn.rewrites():
            if item['url'] == self.url and item['status'] == 'rewrite':
                return item['author']

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

###############################################################################
# Simple Containers
###############################################################################

nt = collections.namedtuple
Revision = nt('Revision', 'id number user time comment')
Vote = nt('Vote', 'user value')
ForumPost = nt('ForumPost', 'id title content user time parent')
Override = nt('Override', 'url user type')
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
