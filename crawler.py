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
from collections import namedtuple

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
        if site[-1] != '/':
            site += '/'
        self.site = site
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
        data = self.req.post(self.site + 'ajax-module-connector.php',
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
        baseurl = '{}system:list-all-pages/p/{}'.format(self.site, '{}')
        soup = BeautifulSoup(self.get_page_html(baseurl))
        counter = soup.select('div.pager span.pager-no')[0].text
        last_page = int(counter.split(' ')[-1])
        for index in range(1, last_page + 1):
            logger.info('Downloading index: {}/{}'.format(index, last_page))
            soup = BeautifulSoup(self.get_page_html(baseurl.format(index)))
            pages = soup.select('div.list-pages-item a')
            for link in pages:
                url = self.site.rstrip('/') + link["href"]
                yield url

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

    def __init__(self, dbname, thread_limit=18):
        orm.connect(dbname)
        self.db = orm.db
        self.thread_limit = thread_limit
        self.queue = queue.Queue()
        self.wiki = WikidotConnector('http://www.scp-wiki.net')

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
            with self.db.transaction():
                table.insert_many(data[idx:idx + 500]).execute()

    def _save_page_to_db(self, url):
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
                        'args': (),
                        'kwargs': {
                            'pageid': pageid,
                            'url': url,
                            'html': html,
                            'thread_id': thread_id}})
        history = self.wiki.get_page_history(pageid)
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Revision, history),
                        'kwargs': {}})
        votes = self.wiki.get_page_votes(pageid)
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Vote, votes),
                        'kwargs': {}})
        comments = list(self.wiki.get_forum_thread(thread_id))
        self.queue.put({'func': self._insert_many,
                        'args': (orm.ForumPost, comments),
                        'kwargs': {}})
        tags = [
            {'tag': i, 'url': url}
            for i in [a.string for a in
                      BeautifulSoup(html).select("div.page-tags a")]]
        self.queue.put({'func': self._insert_many,
                        'args': (orm.Tag, tags),
                        'kwargs': {}})
        logger.debug('Finished saving page: {}'.format(url))

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

    def _threaded_save(self, urls):
        for url in urls:
            try:
                self._save_page_to_db(url)
            except Exception:
                logger.exception('Failed to save page: {}'.format(url))

    def _process_queue(self):
        n = 1
        while True:
            with self.db.transaction():
                for _ in range(500):
                    logger.debug('Processing queue item #{}'.format(n))
                    n += 1
                    item = self.queue.get()
                    func = item['func']
                    args = item['args']
                    kwargs = item['kwargs']
                    try:
                        func(*args, **kwargs)
                    except Exception:
                        logger.exception('Unable to write to the database.')
                    self.queue.task_done()
                    empty = self.queue.empty()
                    all_done = all(not i.is_alive() for i in self.threads)
                    if empty and all_done:
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
        return orm.Page.get(orm.Page.url == url).pageid

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

    def take(self):
        time_start = arrow.now()
        orm.purge()
        all_pages = list(self.wiki.list_all_pages())
        self.threads = []
        for i in range(self.thread_limit):
            new_thread = threading.Thread(
                target=self._threaded_save,
                args=(all_pages[i::self.thread_limit], ))
            new_thread.start()
            self.threads.append(new_thread)
        db_writer = threading.Thread(target=self._process_queue)
        db_writer.start()
        for thread in self.threads:
            thread.join()
        db_writer.join()
        logger.info('Downloading image metadata.')
        self._insert_many(orm.Image, self._scrape_images())
        logger.info('Downloading author metadata.')
        self._insert_many(orm.Author, self._scrape_authors())
        time_taken = (arrow.now() - time_start)
        hours, remainder = divmod(time_taken.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        msg = 'Snapshot succesfully taken. [{:02d}:{:02d}:{:02d}]'
        msg = msg.format(hours, minutes, seconds)
        logger.warning(msg)

    def get_tag(self, tag):
        """Retrieve list of pages with the tag from the database"""
        for i in orm.Tag.select().where(orm.Tag.tag == tag):
            yield i.url

    def get_author(self, url):
        rd = namedtuple('DBAuthorOverride', 'url author override')
        try:
            data = orm.Author.get(orm.Author.url == url)
            return rd(data.url, data.author, data.override)
        except orm.Author.DoesNotExist:
            return False

    def get_images(self):
        images = {}
        im = namedtuple('Image', 'source data')
        for i in orm.Image.select():
            images[i.image_url] = im(i.image_source, i.image_data)
        return images

    def list_all_pages(self):
        count = orm.Page.select().count()
        for n in range(1, count // 50 + 2):
            query = orm.Page.select(
                orm.Page.url).order_by(
                orm.Page.url).paginate(n, 50)
            for i in query:
                yield Page(i.url)


class Page:

    """Scrape and store contents and metadata of a page."""

    sn = None   # Snapshot instance used to init the pages

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url=None):
        self.url = url

    ###########################################################################
    # Properties
    ###########################################################################

    @cached_property
    def html(self):
        return self.sn.get_page_html(self.url)

    @cached_property
    def _pageid(self):
        return self.sn.get_pageid(self.url)

    @cached_property
    def _thread_id(self):
        return self.sn.get_thread_id(self.url)

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
    def votes(self):
        data = self.sn.get_page_votes(self._pageid)
        vote = namedtuple('Vote', 'user value')
        votes = []
        for i in data:
            votes.append(vote(i['user'], i['vote']))
        return votes

    @cached_property
    def rating(self):
        return sum(vote.value for vote in self.votes
                   if vote.user != '(account deleted)')

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
        if self._raw_html is None:
            return []
        links = []
        soup = BeautifulSoup(self._raw_html)
        for a in soup.select("#page-content a"):
            if not a.has_attr("href") or a["href"][0] != "/":
                continue
            if a["href"][-4:] in [".png", ".jpg", ".gif"]:
                continue
            url = "http://www.scp-wiki.net{}".format(a["href"])
            url = url.rstrip("|")
            if url in links:
                continue
            links.append(url)
        return links

    @cached_property
    def children(self):
        if not hasattr(self, "tags"):
            return []
        if not any(i in self.tags for i in [
                'scp', 'hub', 'goi2014', 'splash']):
            return []
        lpages = []
        for url in self.links():
            try:
                p = Page(url)
                try:
                    p.chapters = self.chapters
                except AttributeError:
                    pass
            except orm.Page.DoesNotExist:
                continue
            if p.data is not None:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            mpages = [i for i in lpages if
                      any(k in i.tags for k in ["supplement", "splash"])]
            return mpages
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            mpages = [i for i in lpages if any(
                k in i.tags for k in ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in child.links():
                    return True
                soup = BeautifulSoup(child._raw_html)
                if soup.select("#breadcrumbs a"):
                    crumb = soup.select("#breadcrumbs a")[-1]
                    crumb = "http://www.scp-wiki.net{}".format(crumb["href"])
                    if self.url == crumb:
                        return True
                return False
            if any(backlinks(self, p) for p in mpages):
                return [p for p in mpages if backlinks(self, p)]
            else:
                return mpages
        return []

###############################################################################
# Main Methods
###############################################################################


def enable_logging():
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logger.addHandler(console)
    filelog = logging.FileHandler('crawler.log')
    filelog.setLevel(logging.WARNING)
    file_format = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
    file_formatter = logging.Formatter(file_format)
    filelog.setFormatter(file_formatter)
    logger.addHandler(filelog)


def main():
    #dbname = 'scp-wiki.{}.db'.format(arrow.now().format('YYYY-MM-DD'))
    #Snapshot(dbname).take()
    pass


if __name__ == "__main__":
    enable_logging()
    main()
