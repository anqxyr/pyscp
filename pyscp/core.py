#!/usr/bin/env python3

"""
Abstract Base Classes.

pyscp builds most of its functionality on top of three large classes: Wiki,
Page, and Thread. This module contains the abstract base classes for those
three. The ABC-s define the abstact methods that each child must implement,
as well as some common functionality that builds on top of the abstract
methods.

Each class inheriting from the ABC-s must implement its own realization of
the abstract methods, and can also provide additional methods unique to it.

This module also defines the named tuples for simple containers used by the
three core classes, such as Revision or Vote.
"""


###############################################################################
# Module Imports
###############################################################################

import abc
import arrow
import bs4
import collections
import functools
import itertools
import re
import urllib.parse
import logging

import pyscp.utils

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Abstract Base Classes
###############################################################################


class Page(metaclass=abc.ABCMeta):
    """
    Page Abstract Base Class.

    Page object are wrappers around individual wiki-pages, and allow simple
    operations with them, such as retrieving the rating or the author.

    Each Page instance is attached to a specific instance of the Wiki class.
    The wiki may be used by the page to retrieve a list of titles or other
    similar wiki-wide information that may be used by the Page to, in turn,
    deduce some information about itself.

    Typically, the Page instances should not be created directly. Instead,
    calling an instance of a Wiki class will creating a Page instance
    attached to that wiki.
    """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, wiki, url):
        self.url = url
        self._wiki = wiki

    def __repr__(self):
        return '{}.{}({}, {})'.format(
            self.__module__, self.__class__.__name__,
            repr(self.url), repr(self._wiki))

    def __eq__(self, other):
        if not hasattr(other, 'url') or not hasattr(other, '_wiki'):
            return False
        return self.url == other.url and self._wiki is other._wiki

    ###########################################################################
    # Abstract Methods
    ###########################################################################

    @property
    @abc.abstractmethod
    def _pdata(self):
        """
        Commonly used data about the page.

        This method should return a tuple, the first three elements of which
        are the id number of the page; the id number of the page's comments
        thread; and the html contents of the page.

        Any additional elements of the tuple are left to the discretion
        of the individual Page implimentations.
        """
        pass

    @property
    @abc.abstractmethod
    def history(self):
        """
        Revision history of the page.

        Should return a sorted list of Revision named tuples.
        """
        pass

    @property
    @abc.abstractmethod
    def votes(self):
        """
        Page votes.

        Should return a list of Vote named tuples.
        """
        pass

    @property
    @abc.abstractmethod
    def tags(self):
        """
        Page tags.

        Should return a set of strings.
        """
        pass

    ###########################################################################
    # Internal Methods
    ###########################################################################

    @property
    def _id(self):
        """Unique ID number of the page."""
        return self._pdata[0]

    @pyscp.utils.cached_property
    def _thread(self):
        """Thread object corresponding to the page's comments thread."""
        return self._wiki.Thread(self._wiki, self._pdata[1])

    @property
    def _raw_title(self):
        """Title as displayed on the page."""
        title = self._soup.find(id='page-title')
        return title.text.strip() if title else ''

    @property
    def _raw_author(self):
        return self.history[0].user

    @property
    def _soup(self):
        """BeautifulSoup of the contents of the page."""
        return bs4.BeautifulSoup(self.html, 'lxml')

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def html(self):
        """HTML contents of the page."""
        return self._pdata[2]

    @property
    def posts(self):
        """List of the comments made on the page."""
        return self._thread.posts

    @property
    def comments(self):
        """Alias for Page.posts."""
        return self._thread.posts

    @property
    def text(self):
        """Plain text of the page."""
        return self._soup.find(id='page-content').text

    @property
    def wordcount(self):
        """Number of words encountered on the page."""
        return len(re.findall(r"[\w'█_-]+", self.text))

    @property
    def images(self):
        """Number of images dislayed on the page."""
        # TODO: needs more work.
        return [i['src'] for i in self._soup('img')]

    @property
    def name(self):
        return self.url.split('/')[-1]

    @property
    def title(self):
        """
        Title of the page.

        In case of SCP articles, will include the title from the 'series' page.
        """
        try:
            return '{}: {}'.format(
                self._raw_title, self._wiki.titles()[self.url])
        except KeyError:
            return self._raw_title

    @property
    def created(self):
        """When was the page created."""
        return self.history[0].time

    @property
    def metadata(self):
        """
        Return page metadata.

        Authors in this case includes all users related to the creation
        and subsequent maintenance of the page. The values of the dict
        describe the user's relationship to the page.
        """
        data = [i for i in self._wiki.metadata() if i.url == self.url]
        data = {i.user: i for i in data}

        if 'author' not in {i.role for i in data.values()}:
            meta = Metadata(self.url, self._raw_author, 'author', None)
            data[self._raw_author] = meta

        for k, v in data.items():
            if v.role == 'author' and not v.date:
                data[k] = v._replace(date=self.created)

        return data

    @property
    def rating(self):
        """Rating of the page, excluding deleted accounts."""
        return sum(
            v.value for v in self.votes if v.user != '(account deleted)')

    @property
    @pyscp.utils.listify()
    def links(self):
        """
        Other pages linked from this one.

        Returns an ordered list of unique urls. Off-site links or links to
        images are not included.
        """
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

    @property
    def parent(self):
        """Parent of the current page."""
        if not self.html:
            return None
        breadcrumb = self._soup.select('#breadcrumbs a')
        if breadcrumb:
            return self._wiki.site + breadcrumb[-1]['href']

    @property
    def is_mainlist(self):
        """
        Indicate whether the page is a mainlist scp article.

        This is an scp-wiki exclusive property.
        """
        if 'scp-wiki' not in self._wiki.site:
            return False
        if 'scp' not in self.tags:
            return False
        return bool(re.search(r'/scp-[0-9]{3,4}$', self.url))

    ###########################################################################
    # Methods
    ###########################################################################

    def build_attribution_string(
            self, templates=None, group_templates=None, separator=', ',
            user_formatter=None):
        """
        Create an attribution string based on the page's metadata.

        This is a commonly needed operation. The result should be a nicely
        formatted, human-readable description of who was and is involved with
        the page, and in what role.
        """
        roles = 'author rewrite translator maintainer'.split()

        if not templates:
            templates = {i: '{{user}} ({})'.format(i) for i in roles}

        items = list(self.metadata.values())
        items.sort(key=lambda x: [roles.index(x.role), x.date])

        # group users in the same role on the same date together
        itemdict = collections.OrderedDict()
        for i in items:
            user = user_formatter.format(i.user) if user_formatter else i.user
            key = (i.role, i.date)
            itemdict[key] = itemdict.get(key, []) + [user]

        output = []

        for (role, date), users in itemdict.items():

            hdate = arrow.get(date).humanize() if date else ''

            if group_templates and len(users) > 1:
                output.append(
                    group_templates[role].format(
                        date=date,
                        hdate=hdate,
                        users=', '.join(users[:-1]),
                        last_user=users[-1]))
            else:
                for user in users:
                    output.append(
                        templates[role].format(
                            date=date, hdate=hdate, user=user))

        return separator.join(output)


class Thread(metaclass=abc.ABCMeta):
    """
    Thread Abstract Base Class.

    Thread objects represent individual forum threads. Most pages have a
    corresponding comments thread, accessible via Page._thread.
    """

    def __init__(self, wiki, _id, title=None, description=None):
        self._wiki = wiki
        self._id, self.title, self.description = _id, title, description

    @abc.abstractmethod
    def posts(self):
        """Posts in this thread."""
        pass


class Wiki(metaclass=abc.ABCMeta):
    """
    Wiki Abstract Base Class.

    Wiki objects provide wiki-wide functionality not limited to individual
    pages or threads.
    """

    ###########################################################################
    # Class Attributes
    ###########################################################################

    # should point to the respective Page and Thread classes in each submodule.

    Page = Page
    Thread = Thread

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site):
        parsed = urllib.parse.urlparse(site)
        netloc = parsed.netloc if parsed.netloc else parsed.path
        if '.' not in netloc:
            netloc += '.wikidot.com'
        self.site = urllib.parse.urlunparse(['http', netloc, '', '', '', ''])
        self._title_data = {}

    def __call__(self, name):
        url = name if self.site in name else '{}/{}'.format(self.site, name)
        url = url.replace(' ', '-').replace('_', '-').lower()
        return self.Page(self, url)

    ###########################################################################

    @functools.lru_cache(maxsize=1)
    def metadata(self):
        """
        List page ownership metadata.

        This method is exclusive to the scp-wiki, and is used to fine-tune
        the page ownership information beyond what is possible with Wikidot.
        This allows a single page to have an author different from the user
        who created the zeroth revision of the page, or even have multiple
        users attached to the page in various roles.
        """
        if 'scp-wiki' not in self.site:
            return []
        soup = self('attribution-metadata')._soup
        results = []
        for row in soup('tr')[1:]:
            name, user, type_, date = [i.text.strip() for i in row('td')]
            name = name.lower()
            url = '{}/{}'.format(self.site, name)
            results.append(pyscp.core.Metadata(url, user, type_, date))
        return results

    def _update_titles(self):
        for name in (
                'scp-series', 'scp-series-2', 'scp-series-3', 'scp-series-4', 'scp-series-5',
                'joke-scps', 'scp-ex', 'archived-scps'):
            page = self(name)
            try:
                soup = page._soup
            except:
                continue
            self._title_data[name] = soup

    @functools.lru_cache(maxsize=1)
    @pyscp.utils.ignore(value={})
    @pyscp.utils.log_errors(logger=log.error)
    def titles(self):
        """Dict of url/title pairs for scp articles."""
        if 'scp-wiki' not in self.site:
            return {}

        self._update_titles()

        elems = [i.select('ul > li') for i in self._title_data.values()]
        elems = list(itertools.chain(*elems))
        try:
            elems += list(self('scp-001')._soup(class_='series')[1]('p'))
        except:
            pass

        titles = {}
        for elem in elems:

            sep = ' - ' if ' - ' in elem.text else ', '
            try:
                url1 = self.site + elem.a['href']
                skip, title = elem.text.split(sep, maxsplit=1)
            except (ValueError, TypeError):
                continue

            if title != '[ACCESS DENIED]':
                url2 = self.site + '/' + skip.lower()
                titles[url1] = titles[url2] = title

        return titles

    def list_pages(self, **kwargs):
        """Return pages matching the specified criteria."""
        pages = self._list_pages_parsed(**kwargs)
        author = kwargs.pop('author', None)
        if not author:
            # if 'author' isn't specified, there's no need to check rewrites
            return pages
        include, exclude = set(), set()
        for meta in self.metadata():
            if meta.user == author:
                # if username matches, include regardless of type
                include.add(meta.url)
            elif meta.role == 'author':
                # exclude only if override type is author.
                # if url has author and rewrite author,
                # it will appear in list_pages for both.
                exclude.add(meta.url)
        urls = {p.url for p in pages} | include - exclude
        # if no other options beside author were specified,
        # just return everything we can
        if not kwargs:
            return map(self, sorted(urls))
        # otherwise, retrieve the list of urls without the author parameter
        # to check which urls we should return and in which order
        pages = self._list_pages_parsed(**kwargs)
        return [p for p in pages if p.url in urls]

###############################################################################
# Named Tuple Containers
###############################################################################

nt = collections.namedtuple
Revision = nt('Revision', 'id number user time comment')
Vote = nt('Vote', 'user value')
Post = nt('Post', 'id title content user time parent')
File = nt('File', 'url name filetype size')
Metadata = nt('Metadata', 'url user role date')
Category = nt('Category', 'id title description size')
Image = nt('Image', 'url source status notes data')
del nt
