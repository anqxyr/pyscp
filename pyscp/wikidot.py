#!/usr/bin/env python3

"""
Wikidot access classes.

This module contains the classes that facilitate information extraction
and communication with the Wikidot-hosted sites.
"""

###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import functools
import itertools
import logging
import pyscp
import re
import requests

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

class Wiki(pyscp.core.Wiki):

    """
    Create a Wiki object.

    This class does not use any of the official Wikidot API, and instead
    relies on sending http post/get requests to internal Wikidot pages and
    parsing the returned data.
    """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site):
        super().__init__(site)
        self.req = InsistentRequest()

    def __repr__(self):
        return '{}.{}({})'.format(
            self.__module__,
            self.__class__.__name__,
            repr(self.site))

    ###########################################################################
    # Internal Methods
    ###########################################################################

    @pyscp.utils.morph(requests.RequestException, pyscp.core.ConnectorError)
    @pyscp.utils.log_errors(log.warning)
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

    def _list_pages_raw(self, **kwargs):
        """
        Call ListPages module.

        Wikidot's ListPages is an extremely versatile php module that can be
        used to retrieve all sorts of interesting informations, from urls of
        pages created by a given user, and up to full html contents of every
        page on the site.
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

    def _urls(self, **kwargs):
        pages = self._list_pages_raw(**kwargs)
        soups = (bs4.BeautifulSoup(p['body']) for p in pages)
        elems = (s.select('div.list-pages-item a') for s in soups)
        elems = itertools.chain.from_iterable(elems)
        yield from (self.site + e['href'] for e in elems)

    ###########################################################################
    # Public Methods
    ###########################################################################

    def auth(self, username, password):
        """Login to wikidot with the given username/password pair."""
        return self.req.post(
            'https://www.wikidot.com/default--flow/login__LoginPopupScreen',
            data=dict(
                login=username,
                password=password,
                action='Login2Action',
                event='login'))

    def list_categories(self):
        """Return forum categories."""
        data = self._module('forum/ForumStartModule')['body']
        soup = bs4.BeautifulSoup(data)
        for elem in [e.parent for e in soup(class_='name')]:
            cat_id = parse_element_id(elem.select('.title a')[0])
            title, description, size = [
                elem.find(class_=i).text.strip()
                for i in ('title', 'description', 'threads')]
            yield pyscp.core.ForumCategory(
                cat_id, title, description, int(size))

    def list_threads(self, category_id):
        """Return threads in the given category."""
        pages = self._pager(
            'forum/ForumViewCategoryModule', _key='p', c=category_id)
        soups = (bs4.BeautifulSoup(p['body']) for p in pages)
        elems = (s(class_='name') for s in soups)
        for elem in itertools.chain(*elems):
            thread_id = parse_element_id(elem.select('.title a')[0])
            title, description = [
                elem.find(class_=i).text.strip()
                for i in ('title', 'description')]
            yield pyscp.core.ForumThread(thread_id, title, description)

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    @functools.lru_cache(maxsize=1)
    @pyscp.utils.listify()
    def list_overrides(self):
        """
        List page ownership overrides.

        This method is exclusive to the scp-wiki, and is used to fine-tune
        the page ownership information beyond what is possible with Wikidot.
        This allows a single page to have an author different from the user
        who created the zeroth revision of the page, or even have multiple
        users attached to the page in various roles.
        """
        if 'scp-wiki' not in self.site:
            return None
        url = 'http://05command.wikidot.com/alexandra-rewrite'
        soup = bs4.BeautifulSoup(self.req.get(url).text)
        for row in [r('td') for r in soup('tr')[1:]]:
            url = '{}/{}'.format(self.site, row[0].text)
            user = row[1].text.split(':override:')[-1]
            if ':override:' in row[1].text:
                type = 'author'
            else:
                type = 'rewrite_author'
            yield pyscp.core.Override(url, user, type)

    @functools.lru_cache(maxsize=1)
    @pyscp.utils.listify()
    def list_images(self):
        if 'scp-wiki' not in self.site:
            return
        base = 'http://scpsandbox2.wikidot.com/image-review-{}'
        urls = [base.format(i) for i in range(1, 28)]
        pages = [self.req.get(u).text for u in urls]
        soups = [bs4.BeautifulSoup(p) for p in pages]
        elems = [s('tr') for s in soups]
        elems = itertools.chain(*elems)
        elems = [e('td') for e in elems]
        elems = [e for e in elems if e]
        for elem in elems:
            url = elem[0].img['src']
            source = elem[3].find('a')['href']
            status, notes = [elem[i].text for i in (4, 5)]
            status, notes = [i if i else None for i in (status, notes)]
            yield pyscp.core.Image(url, source, status, notes)


###############################################################################
# Internal Classes
###############################################################################

class Page(pyscp.core.Page):
    """
    Create Page object.
    """

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _module(self, *args, **kwargs):
        """Call Wikidot module."""
        return self._wiki._module(*args, page_id=self._id, **kwargs)

    def _action(self, event, **kwargs):
        """Execute WikiPageAction."""
        return self._module(
            'Empty', action='WikiPageAction', event=event, **kwargs)

    def _vote(self, value):
        """Vote on the page."""
        return self._action(
            'RateAction',
            event='ratePage' if value else 'cancelVote',
            points=value,
            force=True)

    def _flush(self, *names):
        if not hasattr(self, '_cache'):
            return
        self._cache = {k: v for k, v in self._cache.items() if k not in names}

    @pyscp.utils.cached_property
    def _pdata(self):
        data = self._wiki.req.get(self.url).text
        soup = bs4.BeautifulSoup(data)
        return (int(re.search('pageId = ([0-9]+);', data).group(1)),
                parse_element_id(soup.find(id='discuss-button')),
                str(soup.find(id='main-content')),
                {e.text for e in soup.select('.page-tags a')})

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def html(self):
        return self._pdata[2]

    @pyscp.utils.cached_property
    @pyscp.utils.listify()
    def history(self):
        """Return the revision history of the page."""
        data = self._module(
            'history/PageRevisionListModule', page=1, perpage=99999)['body']
        soup = bs4.BeautifulSoup(data)
        for row in reversed(soup('tr')[1:]):
            rev_id = int(row['id'].split('-')[-1])
            cells = row('td')
            number = int(cells[0].text.strip('.'))
            user = cells[4].text
            time = parse_element_time(cells[5])
            comment = cells[6].text if cells[6].text else None
            yield pyscp.core.Revision(rev_id, number, user, time, comment)

    @pyscp.utils.cached_property
    def votes(self):
        """Return all votes made on the page."""
        data = self._module('pagerate/WhoRatedPageModule')['body']
        soup = bs4.BeautifulSoup(data)
        spans = [i.text.strip() for i in soup('span')]
        pairs = zip(spans[::2], spans[1::2])
        return [pyscp.core.Vote(u, 1 if v == '+' else -1) for u, v in pairs]

    @property
    def tags(self):
        return self._pdata[3]

    @property
    def source(self):
        data = self._module('viewsource/ViewSourceModule')['body']
        soup = bs4.BeautifulSoup(data)
        return soup.text[11:].strip().replace(chr(160), ' ')

    ###########################################################################
    # Page-Modifying Methods
    ###########################################################################

    def edit(self, source, title=None, comment=None):
        """Overwrite the page with the new source and title."""
        if title is None:
            title = self._title
        self._flush('html', 'history', 'source')
        wiki_page = self.url.split('/')[-1]
        lock = self._module(
            'edit/PageEditModule',
            mode='page',
            wiki_page=wiki_page,
            force_lock=True)
        return self._action(
            'savePage',
            source=source,
            title=title,
            comments=comment,
            wiki_page=wiki_page,
            lock_id=lock['lock_id'],
            lock_secret=lock['lock_secret'],
            revision_id=lock.get('page_revision_id', None))

    def revert(self, rev_n):
        """Revert the page to a previous revision."""
        self._flush('html', 'history', 'source', 'tags')
        return self._action('revert', revisionId=self.history[rev_n].id)

    def set_tags(self, tags):
        """Replace the tags of the page."""
        res = self._action('saveTags', tags=' '.join(tags))
        self._flush('history', '_pdata')
        return res

    ###########################################################################
    # Voting Methods
    ###########################################################################

    def upvote(self):
        self._vote(1)
        self._flush('votes')

    def downvote(self):
        self._vote(-1)
        self._flush('votes')

    def cancel_vote(self):
        self._vote(0)
        self._flush('votes')


class Thread(pyscp.core.Thread):

    @pyscp.utils.cached_property
    @pyscp.utils.listify()
    def posts(self):
        pages = self._wiki._pager(
            'forum/ForumViewThreadPostsModule', _key='pageNo', t=self._id)
        pages = (bs4.BeautifulSoup(p['body']).body for p in pages)
        pages = (p for p in pages if p)
        posts = (p(class_='post-container', recursive=False) for p in pages)
        posts = itertools.chain.from_iterable(posts)
        for post, parent in crawl_posts(posts):
            post_id = int(post['id'].split('-')[1])
            title = post.find(class_='title').text.strip()
            title = title if title else None
            content = post.find(class_='content')
            content.attrs.clear()
            content = str(content)
            user = post.find(class_='printuser').text
            time = parse_element_time(post)
            yield pyscp.core.Post(post_id, title, content, user, time, parent)


Wiki.Page = Page
Wiki.Thread = Thread

###############################################################################


@pyscp.utils.ignore((IndexError, TypeError))
def parse_element_id(element):
    """Extract the id number from the link."""
    return int(element['href'].split('/')[2].split('-')[1])


def parse_element_time(element):
    """Extract and format time from an html element."""
    unixtime = element.find(class_='odate')['class'][1].split('_')[1]
    return arrow.get(unixtime).format('YYYY-MM-DD HH:mm:ss')


def crawl_posts(post_containers, parent=None):
    """
    Retrieve posts from the comment tree.

    For each post-container in the given list, returns a tuple of
    (post, parent). Then recurses onto all the post-container children
    of the current post-container.
    """
    for container in post_containers:
        yield container.find(class_='post'), parent
        yield from crawl_posts(
            container(class_='post-container', recursive=False),
            int(container['id'].split('-')[1]))
