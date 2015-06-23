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

import bs4
import collections
import functools
import logging
import re
import urllib.parse
import itertools

import pyscp.utils

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Public Classes
###############################################################################


class Wiki:
    """
    Wiki Abstract Base Class.
    """

    ###########################################################################
    # Class Attributes
    ###########################################################################

    # should point to the respective Page and Thread classes in each submodule.

    Page = None
    Thread = None

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site):
        parsed = urllib.parse.urlparse(site)
        netloc = parsed.netloc if parsed.netloc else parsed.path
        if '.' not in netloc:
            netloc += '.wikidot.com'
        self.site = urllib.parse.urlunparse(['http', netloc, '', '', '', ''])

    def __call__(self, url):
        return self.Page(self, url)

    ###########################################################################

    @functools.lru_cache(maxsize=1)
    def titles(self):
        """Return a dict of url/title pairs for scp articles."""
        pages = map(self, ('scp-series', 'scp-series-2', 'scp-series-3'))
        elems = [p._soup.select('ul > li') for p in pages]
        elems = itertools.chain(*elems)
        titles = {}
        splash = set(self.list_pages(tag='splash'))
        for elem in elems:
            if not re.search('[SCP]+-[0-9]+', elem.text):
                continue
            url = self.site + elem.a['href']
            try:
                skip, title = elem.text.split(' - ', maxsplit=1)
            except ValueError:
                skip, title = elem.text.split(', ', maxsplit=1)
            if url in splash:
                url = '{}/{}'.format(self.site, skip.lower())
            titles[url] = title
        return titles

    def list_pages(self, **kwargs):
        """
        Return pages matching the specified criteria.
        """
        urls = self._urls(**kwargs)
        author = kwargs.pop('author', None)
        if not author:
            # if 'author' isn't specified, there's no need to check rewrites
            yield from map(self, urls)
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
            yield from map(self, sorted(urls))
            return
        # otherwise, retrieve the list of urls without the author parameter
        # to check which urls we should return and in which order
        for url in self._urls(**kwargs):
            if url in urls:
                yield self(url)


class Page:

    """
    Page Abstract Base Class.

    Each submodule must implement its own Page class inheriting from
    this one. The Page classes in each submodule are responsible for
    retrieving the raw data, while this class provides several common
    methods to manipulate it.
    """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, wiki, url):
        if wiki.site not in url:
            url = '{}/{}'.format(wiki.site, url)
        self.url = url.lower()
        self._wiki = wiki

    def __repr__(self):
        return '{}.{}({}, {})'.format(
            self.__module__, self.__class__.__name__,
            repr(self.url), repr(self._wiki))

    ###########################################################################
    # Internal Methods
    ###########################################################################

    @property
    def _id(self):
        return self._pdata[0]

    @pyscp.utils.cached_property
    def _thread(self):
        return self._wiki.Thread(self._wiki, self._pdata[1])

    @property
    def _title(self):
        """Title as displayed on the page."""
        title = self._soup.find(id='page-title')
        return title.text.strip() if title else ''

    @property
    def _soup(self):
        return bs4.BeautifulSoup(self.html)

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def posts(self):
        return self._thread.posts

    @property
    def comments(self):
        return self._thread.posts

    @property
    def text(self):
        return self._soup.find(id='page-content').text

    @property
    def wordcount(self):
        return len(re.findall(r"[\w'█_-]+", self.text))

    @property
    def images(self):
        return [i['src'] for i in self._soup('img')]

    @property
    def title(self):
        if 'scp' in self.tags and re.search('[scp]+-[0-9]+$', self.url):
            return '{}: {}'.format(self._title, self._wiki.titles()[self.url])
        return self._title

    @property
    def created(self):
        return self.history[0].time

    @property
    def author(self):
        for over in self._wiki.list_overrides():
            if over.url == self.url and over.type == 'author':
                return over.user
        return self.history[0].user

    @property
    def rewrite_author(self):
        for over in self._wiki.list_overrides():
            if over.url == self.url and over.type == 'rewrite_author':
                return over.user

    @property
    def rating(self):
        return sum(
            v.value for v in self.votes if v.user != '(account deleted)')

    @property
    @pyscp.utils.listify()
    def links(self):
        unique = set()
        for element in self._soup.select('#page-content a'):
            href = element.get('href', None)
            if (not href or href[0] != '/' or  # bad or absolute link
                    href[-4:] in ('.png', '.jpg', '.gif')):
                continue
            url = self._wiki.site + href.rstrip('|')
            if url not in unique:
                unique.add(url)
                yield url


class Thread:

    def __init__(self, wiki, _id, title=None, description=None):
        self._wiki = wiki
        self._id, self.title, self.description = _id, title, description

###############################################################################
# Simple Containers
###############################################################################

nt = collections.namedtuple
Revision = nt('Revision', 'id number user time comment')
Vote = nt('Vote', 'user value')
Post = nt('Post', 'id title content user time parent')
Override = nt('Override', 'url user type')
Category = nt('Category', 'id title description size')
Image = nt('Image', 'url source status notes')
del nt
