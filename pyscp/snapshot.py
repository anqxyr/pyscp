#!/usr/bin/env python3

"""
Snapshot access classes.

This module contains the classes that facilitate information extraction
and communication with the sqlite Snapshots.
"""

###############################################################################
# Module Imports
###############################################################################

import functools
import logging
import pathlib

import pyscp.core
import pyscp.orm
import pyscp.utils

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Public Classes
###############################################################################


class Wiki(pyscp.core.Wiki):

    """
    Create a Wiki object.
    """

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site, dbpath):
        super().__init__(site)
        if not pathlib.Path(dbpath).exists():
            raise FileNotFoundError(dbpath)
        self.dbpath = dbpath
        pyscp.orm.connect(dbpath)

    def __repr__(self):
        return '{}.{}({}, {})'.format(
            self.__module__,
            self.__class__.__qualname__,
            repr(self.site.replace('http://', '')),
            repr(self.dbpath))

    ###########################################################################
    # Internal Methods
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

    ###########################################################################
    # Public Methods
    ###########################################################################

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

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    @functools.lru_cache()
    @pyscp.utils.listify()
    def list_overrides(self):
        for row in (
                orm.Override
                .select(orm.Override, orm.User.name, orm.OverrideType.name)
                .join(orm.User).switch(orm.Override).join(orm.OverrideType)):
            yield Override(row._data['url'], row.user.name, row.type.name)

    @functools.lru_cache()
    @pyscp.utils.listify()
    def images(self):
        for row in orm.Image.select():
            yield dict(
                url=row.url, source=row.source, status=row.status.label,
                notes=row.notes, data=row.data)

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

    def _query(self, ptable, stable='User', key=None):
        """Generate SQL queries used to retrieve data."""
        if key is None:
            key = lambda x: x.page == self._id
        pt, st = [getattr(pyscp.orm, i) for i in (ptable, stable)]
        return pt.select(pt, st.name).join(st).where(key(pt)).execute()

    @pyscp.utils.cached_property
    def _pdata(self):
        """
        Preload the ids and contents of the page.
        """
        pdata = pyscp.orm.Page.get(pyscp.orm.Page.url == self.url)
        return pdata.id, pdata._data['thread'], pdata.html

    @property
    def _id(self):
        return self._pdata[0]

    @pyscp.utils.cached_property
    def _thread(self):
        return Thread(self._wiki, self._pdata[1])

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def html(self):
        return self._pdata[2]

    @pyscp.utils.cached_property
    def history(self):
        """Return the revisions of the page."""
        revs = self._query('Revision')
        revs = sorted(revs, key=lambda x: x.number)
        return [pyscp.core.Revision(
                r.id, r.number, r.user.name, str(r.time), r.comment)
                for r in revs]


class Thread(pyscp.core.Thread):
    pass


Wiki.Page = Page
Wiki.Thread = Thread
