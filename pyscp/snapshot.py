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
            repr(self.site),
            repr(self.dbpath))

    ###########################################################################
    # Internal Methods
    ###########################################################################

    @staticmethod
    def _filter_query_author(query, author):
        o = pyscp.orm
        filter_query = (
            o.Page.select(o.Page.url).join(o.Revision).join(o.User)
            .where(o.Revision.number == 0).where(o.User.name == author))
        return query & filter_query

    @staticmethod
    def _filter_query_tag(query, tag):
        o = pyscp.orm
        filter_query = (o.Page.select(o.Page.url)
                        .join(o.PageTag).join(o.Tag)
                        .where(o.Tag.name == tag))
        return query & filter_query

    def _urls(self, **kwargs):
        query = pyscp.orm.Page.select(pyscp.orm.Page.url)
        keys = ('author', 'tag')
        keys = [k for k in keys if k in kwargs]
        for k in keys:
            query = getattr(self, '_filter_query_' + k)(query, kwargs[k])
        if 'limit' in kwargs:
            query = query.limit(kwargs['limit'])
        for p in query:
            yield p.url

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    @functools.lru_cache(maxsize=1)
    def list_overrides(self):
        ov = pyscp.orm.Override
        ot = pyscp.orm.OverrideType
        us = pyscp.orm.User
        query = ov.select(ov, us.name, ot).join(us).switch(ov).join(ot)
        return [pyscp.core.Override(r._data['url'], r.user.name, r.type.name)
                for r in query]

    @functools.lru_cache()
    @pyscp.utils.listify()
    def images(self):
        for row in pyscp.orm.Image.select():
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

    def _query(self, ptable, stable='User'):
        """Generate SQL queries used to retrieve data."""
        pt, st = [getattr(pyscp.orm, i) for i in (ptable, stable)]
        return pt.select(pt, st.name).join(st).where(pt.page == self._id)

    @pyscp.utils.cached_property
    def _pdata(self):
        """
        Preload the ids and contents of the page.
        """
        pdata = pyscp.orm.Page.get(pyscp.orm.Page.url == self.url)
        return pdata.id, pdata._data['thread'], pdata.html

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

    @pyscp.utils.cached_property
    def votes(self):
        """Return all votes made on the page."""
        return [pyscp.core.Vote(v.user.name, v.value)
                for v in self._query('Vote')]

    @pyscp.utils.cached_property
    def tags(self):
        """Return the set of tags with which the page is tagged."""
        return {pt.tag.name for pt in self._query('PageTag', 'Tag')}


class Thread(pyscp.core.Thread):

    @pyscp.utils.cached_property
    def posts(self):
        fp = pyscp.orm.ForumPost
        us = pyscp.orm.User
        query = fp.select(fp, us.name).join(us).where(fp.thread == self._id)
        return [pyscp.core.Post(
                p.id, p.title, p.content, p.user.name,
                str(p.time), p._data['parent'])
                for p in query]


Wiki.Page = Page
Wiki.Thread = Thread
