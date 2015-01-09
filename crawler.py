#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import logging
import orm
import queue
import re
import requests
import threading

from bs4 import BeautifulSoup
from cached_property import cached_property
from contextlib import contextmanager
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from os import listdir

###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.crawler')
logger.setLevel(logging.DEBUG)

###############################################################################
# Primary Classes
###############################################################################


class WikidotConnector:

    def __init__(self, site):
        self.site = site.rstrip('/')
        req = requests.Session()
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _module(self, name, pageid, **kwargs):
        '''Retrieve data from the specified wikidot module.'''
        msg = '_module call: {} ({}) ({})'
        kwstring = ', '.join('{}: {}'.format(k, v) for k, v in kwargs.items())
        logger.debug(msg.format(name, pageid, kwstring))
        headers = {'Content-Type': 'application/x-www-form-urlencoded;'}
        payload = {
            'page_id': pageid,
            'pageId': pageid,  # fuck wikidot
            'moduleName': name,
            'wikidot_token7': '123456'}
        cookies = {'wikidot_token7': '123456'}
        for i in self.req.cookies:
            cookies[i.name] = i.value
        for k, v in kwargs.items():
            payload[k] = v
        data = self.req.post(self.site + '/ajax-module-connector.php',
                             data=payload, headers=headers, cookies=cookies)
        return data.json()

    def _parse_forum_thread_page(self, page_html):
        soup = BeautifulSoup(page_html)
        posts = []
        for e in soup.select('div.post'):
            post_id = e['id'].split('-')[1]
            title = e.select('div.title')[0].text.strip()
            content = e.select('div.content')[0]
            user = e.select('span.printuser')[0].text
            unix_time = e.select('span.odate')[0]['class'][1].split('_')[1]
            time = arrow.get(unix_time).format('YYYY-MM-DD HH:mm:ss')
            granpa = e.parent.parent
            if 'class' in granpa.attrs and 'post-container' in granpa['class']:
                parent = granpa.select('div.post')[0]['id'].split('-')[1]
            else:
                parent = None
            posts.append({
                'post_id': post_id,
                'title': title,
                'content': content,
                'user': user,
                'time': time,
                'parent': parent})
        return posts

    def _pager(self, baseurl):
        logger.debug('Paging through {}'.format(baseurl))
        first_page = self.get_page_html(baseurl)
        yield first_page
        soup = BeautifulSoup(first_page)
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
    # Page Interface Methods
    ###########################################################################

    def get_page_html(self, url):
        data = self.req.get(url, allow_redirects=False)
        if data.status_code == 200:
            return data.text
        else:
            msg = 'Page {} returned http status code {}'
            logger.warning(msg.format(url, data.status_code))
            return None

    def get_page_history(self, pageid):
        if pageid is None:
            return None
        data = self._module(
            name='history/PageRevisionListModule',
            pageid=pageid,
            page=1,
            perpage=1000000)['body']
        soup = BeautifulSoup(data)
        history = []
        for i in soup.select('tr')[1:]:
            rev_data = i.select('td')
            number = int(rev_data[0].text.strip('.'))
            user = rev_data[4].text
            unix_time = rev_data[5].span['class'][1].split('_')[1]
            time = arrow.get(unix_time).format('YYYY-MM-DD HH:mm:ss')
            comment = rev_data[6].text
            history.append({
                'pageid': pageid,
                'number': number,
                'user': user,
                'time': time,
                'comment': comment})
        return history

    def get_page_votes(self, pageid):
        if pageid is None:
            return None
        data = self._module(
            name='pagerate/WhoRatedPageModule',
            pageid=pageid)['body']
        soup = BeautifulSoup(data)
        votes = []
        for i in soup.select('span.printuser'):
            user = i.text
            vote = i.next_sibling.next_sibling.text.strip()
            if vote == '+':
                vote = 1
            else:
                vote = -1
            votes.append({'pageid': pageid, 'user': user, 'vote': vote})
        return votes

    def get_page_source(self, pageid):
        if pageid is None:
            return None
        html = self._module(
            name='viewsource/ViewSourceModule',
            pageid=pageid)['body']
        source = BeautifulSoup(html).text
        source = source[11:].strip()
        return source

    ###########################################################################
    # Helper Methods
    ###########################################################################

    def parse_pageid(self, html):
        pageid = re.search("pageId = ([^;]*);", html)
        if pageid is not None:
            pageid = pageid.group(1)
        return pageid

    def parse_page_title(self, html):
        soup = BeautifulSoup(html)
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        return title

    def parse_discussion_id(self, html):
        soup = BeautifulSoup(html)
        try:
            link = soup.select('#discuss-button')[0]['href']
            return re.search(r'/forum/t-([0-9]+)/', link).group(1)
        except (IndexError, AttributeError):
            return None

    ###########################################################################
    # Read-only Methods
    ###########################################################################

    def list_all_pages(self):
        baseurl = self.site + '/system:list-all-pages'
        for page in self._pager(baseurl):
            soup = BeautifulSoup(page)
            for link in soup.select('div.list-pages-item a'):
                url = self.site + link['href']
                yield url

    def list_forum_categories(self):
        baseurl = '{}/forum:start'.format(self.site)
        soup = BeautifulSoup(self.get_page_html(baseurl))
        categories = []
        for i in soup.select('td.name'):
            title = i.select('div.title')[0].text.strip()
            category_id = i.select('div.title')[0].a['href']
            category_id = re.search(r'/forum/c-([0-9]+)/',
                                    category_id).group(1)
            description = i.select('div.description')[0].text.strip()
            categories.append({
                'category_id': category_id,
                'title': title,
                'description': description})
        return categories

    def list_threads_in_category(self, category_id):
        baseurl = '{}/forum/c-{}'.format(self.site, category_id)
        for page in self._pager(baseurl):
            soup = BeautifulSoup(page)
            for i in soup.select('td.name'):
                thread_id = i.select('div.title')[0].a['href']
                thread_id = re.search(r'/forum/t-([0-9]+)', thread_id).group(1)
                title = i.select('div.title')[0].text.strip()
                description = i.select('div.description')[0].text.strip()
                yield {
                    'thread_id': thread_id,
                    'title': title,
                    'description': description,
                    'category_id': category_id}

    def get_forum_thread(self, thread_id):
        if thread_id is None:
            return []
        data = self._module(
            name='forum/ForumViewThreadPostsModule',
            t=thread_id,
            pageid=None,
            pageNo=1)['body']
        soup = BeautifulSoup(data)
        try:
            pager = soup.select('span.pager-no')[0].text
            num_of_pages = int(pager.split(' of ')[1])
        except IndexError:
            num_of_pages = 1
        posts = []
        for post in self._parse_forum_thread_page(data):
            post['thread_id'] = thread_id
            posts.append(post)
        for n in range(2, num_of_pages + 1):
            data = self._module(
                name='forum/ForumViewThreadPostsModule',
                t=thread_id,
                pageid=None,
                pageNo=n)['body']
            for post in self._parse_forum_thread_page(data):
                post['thread_id'] = thread_id
                posts.append(post)
        return posts

    ###########################################################################
    # Active Methods
    ###########################################################################

    def auth(self, username, password):
        payload = {
            'login': username,
            'password': password,
            'action': 'Login2Action',
            'event': 'login'}
        url = 'https://www.wikidot.com/default--flow/login__LoginPopupScreen'
        self.req.post(url, data=payload)

    def edit_page(self, pageid, url, source, title, comments=None):
        wiki_page = url.split('/')[-1]
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
            'wiki_page': wiki_page}
        self._module('Empty', pageid, **params)

    def post_in_thread(self, thread_id, source, title=None):
        params = {
            'threadId': thread_id,
            'parentId': None,
            'title': title,
            'source': source,
            'action': 'ForumAction',
            'event': 'savePost'}
        self._module('Empty', None, **params)

    def set_page_tags(self, pageid, tags):
        params = {
            'tags': ' '.join(tags),
            'action': 'WikiPageAction',
            'event': 'saveTags'}
        self._module('Empty', pageid, **params)


class Snapshot:

    database_directory = '/home/anqxyr/heap/_scp/'

    def __init__(self, dbname, site='http://www.scp-wiki.net'):
        self.dbname = dbname
        dbpath = self.database_directory + dbname
        orm.connect(dbpath)
        self.db = orm.db
        self.thread_limit = 20
        self.queue = queue.Queue()
        self.site = site
        self.wiki = WikidotConnector(self.site)

    ###########################################################################
    # Scraping Methods
    ###########################################################################

    def _scrape_images(self):
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        req = requests.Session()
        req.mount('http://', requests.adapters.HTTPAdapter(max_retries=5))
        soup = BeautifulSoup(req.get(url).text)
        for i in soup.select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            image_data = req.get(image_url).content
            yield {"url": image_url,
                   "source": image_source,
                   "data": image_data}

    def _scrape_authors(self):
        url = "http://05command.wikidot.com/alexandra-rewrite"
        req = requests.Session()
        site = 'http://05command.wikidot.com'
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        soup = BeautifulSoup(req.get(url).text)
        for i in soup.select("tr")[1:]:
            url = "http://www.scp-wiki.net/{}".format(i.select("td")[0].text)
            author = i.select("td")[1].text
            if author.startswith(":override:"):
                override = True
                author = author[10:]
            else:
                override = False
            yield {"url": url, "author": author, "override": override}

    ###########################################################################
    # Database Methods
    ###########################################################################

    def _insert_many(self, table, data):
        data = list(data)
        for idx in range(0, len(data), 500):
            with orm.db.transaction():
                table.insert_many(data[idx:idx + 500]).execute()

    def _save_page_to_db(self, url):
        exclusion_list = ['http://www.scp-wiki.net/forum:thread']
        if url in exclusion_list:
            msg = 'Page {} is in the exlusion list and will not be saved'
            msg = msg.format(url)
            logger.warning(msg)
            return
        logger.info('Saving page: {}'.format(url))
        html = self.wiki.get_page_html(url)
        if html is None:
            msg = 'Page {} is empty and will not be saved.'
            logger.warning(msg.format(url))
            return
        pageid = self.wiki.parse_pageid(html)
        thread_id = self.wiki.parse_discussion_id(html)
        soup = BeautifulSoup(html)
        html = str(soup.select('#main-content')[0])
        self.queue.put({'func': orm.Page.create,
                        'kwargs': {
                            'pageid': pageid,
                            'url': url,
                            'html': html,
                            'thread_id': thread_id}})
        history = self.wiki.get_page_history(pageid)
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Revision, history)})
        votes = self.wiki.get_page_votes(pageid)
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Vote, votes)})
        self._save_thread_to_db(thread_id)
        tags = [
            {'tag': i, 'url': url}
            for i in [a.string for a in
                      BeautifulSoup(html).select("div.page-tags a")]]
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Tag, tags)})
        logger.debug('Finished saving page: {}'.format(url))

    def _save_thread_to_db(self, thread_id):
        comments = list(self.wiki.get_forum_thread(thread_id))
        self.queue.put({'func': self._insert_many,
                        'args': (orm.ForumPost, comments)})

    ###########################################################################
    # Threading Methods
    ###########################################################################
    # Since most of the time taken by snapshot creation is spent waiting for
    # responses from wikidot servers to http get/post requests, it's possible
    # to speed up this process by scraping several pages simultaneously in
    # parallel threads.
    # However, concurrent writes to the database are either impossible, in
    # case of sqlite, or may cause unobvious issues later on. As such, after
    # scraping the data, we will delegate saving it to the database to another
    # thread, which will perform all write operations sequentially.
    ###########################################################################

    def _process_queue(self):
        n = 1
        while True:
            with orm.db.transaction():
                for _ in range(500):
                    logger.debug('Processing queue item #{}'.format(n))
                    n += 1
                    item = self.queue.get()
                    func = item['func']
                    args = item.get('args', ())
                    kwargs = item.get('kwargs', {})
                    try:
                        func(*args, **kwargs)
                    except Exception:
                        logger.exception('Unable to write to the database.')
                    self.queue.task_done()
                    for i in self.futures:
                        if i.done():
                            self.futures.remove(i)
                    if not self.futures:
                        return

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
        orm.purge()
        for i in [orm.Page, orm.Revision, orm.Vote, orm.ForumPost, orm.Tag]:
            i.create_table()
        self.futures = []
        db_writer = threading.Thread(target=self._process_queue)
        db_writer.start()
        with ThreadPoolExecutor(max_workers=self.thread_limit) as executor:
            for url in self.wiki.list_all_pages():
                future = executor.submit(self._save_page_to_db, url)
                self.futures.append(future)
            if include_forums:
                self.queue.put({'func': orm.ForumThread.create_table})
                self.queue.put({'func': orm.ForumCategory.create_table})
                for c in self.wiki.list_forum_categories():
                    if c['title'] == 'Per page discussions':
                        continue
                    self.queue.put({'func': orm.ForumCategory.create,
                                    'kwargs': c})
                    c_id = c['category_id']
                    for t in self.wiki.list_threads_in_category(c_id):
                        msg = 'Saving forum thread: {}'.format(t['title'])
                        logger.info(msg)
                        self.queue.put({'func': orm.ForumThread.create,
                                        'kwargs': t})
                        t_id = t['thread_id']
                        future = executor.submit(self._save_thread_to_db, t_id)
                        self.futures.append(future)
        db_writer.join()
        if self.site == 'http://www.scp-wiki.net':
            orm.Image.create_table()
            logger.info('Downloading image metadata.')
            self._insert_many(orm.Image, self._scrape_images())
            orm.Author.create_table()
            logger.info('Downloading author metadata.')
            self._insert_many(orm.Author, self._scrape_authors())
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
    @contextmanager
    def from_snapshot(cls, name=None):
        previous_sn = cls.sn
        if name is None:
            name = sorted([
                i for i in listdir(Snapshot.database_directory)
                if i.startswith('scp-wiki') and i.endswith('.db')])[-1]
        cls.sn = Snapshot(name)
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
            if set(p.tags) & set(['tale', 'goi-format', 'goi2014']):
                maybe_children.append(p.url)
            if self.url in p.links:
                confirmed_children.append(p.url)
            elif p.html:
                crumb = BeautifulSoup(p.html).select('#breadcrumbs a')
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
            soup = BeautifulSoup(cls(url).html)
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

    @cached_property
    def _pageid(self):
        return self.sn.get_pageid(self.url)

    @cached_property
    def _thread_id(self):
        return self.sn.get_thread_id(self.url)

    @cached_property
    def _wikidot_title(self):
        '''
        Page title as used by wikidot. Should only be used by the self.title
        property or when editing the page. In all other cases, use self.title.
        '''
        title_tag = BeautifulSoup(self.html).select('#page-title')
        if title_tag:
            return title_tag[0].text.strip()
        else:
            return ''

    ###########################################################################
    # Public Properties
    ###########################################################################

    @cached_property
    def html(self):
        return self.sn.get_page_html(self.url)

    @cached_property
    def text(self):
        return BeautifulSoup(self.html).select('#page-content')[0].text

    @cached_property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    @cached_property
    def images(self):
        return [i['src'] for i in BeautifulSoup(self.html).select('img')]

    @cached_property
    def title(self):
        if 'scp' in self.tags and re.search('[scp]+-[0-9]+$', self.url):
            if self._title_index is None:
                self._construct_title_index()
            title = '{}: {}'.format(
                self._wikidot_title,
                self._title_index[self.url])
            return title
        return self._wikidot_title

    @cached_property
    def history(self):
        data = self.sn.get_page_history(self._pageid)
        rev = namedtuple('Revision', 'number user time comment')
        history = []
        for i in data:
            history.append(rev(
                i['number'],
                i['user'],
                i['time'],
                i['comment']))
        return history

    @cached_property
    def creation_time(self):
        return self.history[0].time

    @cached_property
    def authors(self):
        authors = []
        author = namedtuple('Author', 'user status')
        second_author = self.sn.get_author_metadata(self.url)
        if ((second_author is None or not second_author['override'])
                and self.history):
            authors.append(author(self.history[0].user, 'original'))
        if second_author is not None:
            if second_author['override']:
                authors.append(author(second_author['user'], 'override'))
            else:
                authors.append(author(second_author['user'], 'rewrite'))
        return authors

    @cached_property
    def author(self):
        if len(self.authors) == 1:
            return self.authors[0].user
        else:
            for i in self.authors:
                if i.status == 'override':
                    return i.user
                if i.status == 'original':
                    original_author = i.user
            return original_author

    @cached_property
    def votes(self):
        data = self.sn.get_page_votes(self._pageid)
        vote = namedtuple('Vote', 'user value')
        votes = []
        for i in data:
            votes.append(vote(i['user'], i['vote']))
        return votes

    @cached_property
    def rating(self):
        if not self.votes:
            return None
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

    @cached_property
    def tags(self):
        return self.sn.get_page_tags(self.url)

    @cached_property
    def comments(self):
        data = self.sn.get_forum_thread(self._thread_id)
        com = namedtuple('Comment', 'post_id parent title user time content')
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

    @cached_property
    def links(self):
        if self.html is None:
            return []
        links = set()
        for a in BeautifulSoup(self.html).select('#page-content a'):
            if (('href' not in a.attrs) or
                (a['href'][0] != '/') or
                    (a['href'][-4:] in ['.png', '.jpg', '.gif'])):
                continue
            url = 'http://www.scp-wiki.net{}'.format(a['href'])
            url = url.rstrip("|")
            links.add(url)
        return list(links)

    @cached_property
    def children(self):
        if 'scp' in self.tags or 'splash' in self.tags:
            return self._get_children_if_skip()
        if 'hub' in self.tags and (set(self.tags) & set(['tale', 'goi2014'])):
            return self._get_children_if_hub()
        return []

###############################################################################
# Main Methods
###############################################################################


def enable_logging(logger):
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
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
    with Page.from_snapshot():
        print(Page('scp-1797').images)
    pass


if __name__ == "__main__":
    enable_logging(logger)
    main()
