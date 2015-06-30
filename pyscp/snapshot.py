#!/usr/bin/env python3

"""
Snapshot access classes.

This module contains the classes that facilitate information extraction
and communication with the sqlite Snapshots.
"""

###############################################################################
# Module Imports
###############################################################################

import bs4
import concurrent.futures
import functools
import itertools
import logging
import operator
import pathlib
import re
import requests

from pyscp import core, orm, utils

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################


class Page(core.Page):
    """
    Create Page object.
    """

    ###########################################################################
    # Internal Methods
    ###########################################################################

    def _query(self, ptable, stable='User'):
        """Generate SQL queries used to retrieve data."""
        pt, st = [getattr(orm, i) for i in (ptable, stable)]
        return pt.select(pt, st.name).join(st).where(pt.page == self._id)

    @utils.cached_property
    def _pdata(self):
        """
        Preload the ids and contents of the page.
        """
        pdata = orm.Page.get(orm.Page.url == self.url)
        return pdata.id, pdata._data['thread'], pdata.html

    ###########################################################################
    # Properties
    ###########################################################################

    @property
    def html(self):
        return self._pdata[2]

    @utils.cached_property
    def history(self):
        """Return the revisions of the page."""
        revs = self._query('Revision')
        revs = sorted(revs, key=lambda x: x.number)
        return [core.Revision(
                r.id, r.number, r.user.name, str(r.time), r.comment)
                for r in revs]

    @utils.cached_property
    def votes(self):
        """Return all votes made on the page."""
        return [core.Vote(v.user.name, v.value)
                for v in self._query('Vote')]

    @utils.cached_property
    def tags(self):
        """Return the set of tags with which the page is tagged."""
        return {pt.tag.name for pt in self._query('PageTag', 'Tag')}


class Thread(core.Thread):

    @utils.cached_property
    def posts(self):
        fp = orm.ForumPost
        us = orm.User
        query = fp.select(fp, us.name).join(us).where(fp.thread == self._id)
        return [core.Post(
                p.id, p.title, p.content, p.user.name,
                str(p.time), p._data['parent'])
                for p in query]


class Wiki(core.Wiki):

    """
    Create a Wiki object.
    """

    Page = Page
    Thread = Thread
    # Tautology = Tautology

    ###########################################################################
    # Special Methods
    ###########################################################################

    def __init__(self, site, dbpath):
        super().__init__(site)
        if not pathlib.Path(dbpath).exists():
            raise FileNotFoundError(dbpath)
        self.dbpath = dbpath
        orm.connect(dbpath)

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
    def _filter_author(author):
        return (orm.Page.select(orm.Page.url)
                .join(orm.Revision).join(orm.User)
                .where(orm.Revision.number == 0)
                .where(orm.User.name == author))

    @staticmethod
    def _filter_tag(tag):
        return (orm.Page.select(orm.Page.url)
                .join(orm.PageTag).join(orm.Tag)
                .where(orm.Tag.name == tag))

    @staticmethod
    def _get_operator(string):
        symbol, *values = re.split(r'(\d+)', string)
        opdict = {
            '>': 'gt', '<': 'lt', '>=': 'ge', '<=': 'le', '=': 'eq', '': 'eq'}
        if symbol not in opdict:
            raise ValueError
        return getattr(operator, opdict[symbol]), values

    def _filter_rating(self, rating):
        compare, values = self._get_operator(rating)
        rating = int(values[0])
        return (orm.Page.select(orm.Page.url)
                .join(orm.Vote).group_by(orm.Page.url)
                .having(compare(orm.peewee.fn.sum(orm.Vote.value), rating)))

    def _filter_created(self, created):
        compare, values = self._get_operator(created)
        date = '-'.join(values[::2])
        return (orm.Page.select(orm.Page.url)
                .join(orm.Revision).where(orm.Revision.number == 0)
                .group_by(orm.Page.url)
                .having(compare(
                    orm.peewee.fn.substr(orm.Revision.time, 1, len(date)),
                    date)))

    def _urls(self, **kwargs):
        query = orm.Page.select(orm.Page.url)
        keys = ('author', 'tag', 'rating', 'created')
        keys = [k for k in keys if k in kwargs]
        for k in keys:
            query = query & getattr(self, '_filter_' + k)(kwargs[k])
        if 'limit' in kwargs:
            query = query.limit(kwargs['limit'])
        for p in query:
            yield p.url

    ###########################################################################
    # SCP-Wiki Specific Methods
    ###########################################################################

    @functools.lru_cache(maxsize=1)
    def list_overrides(self):
        ov = orm.Override
        ot = orm.OverrideType
        us = orm.User
        query = ov.select(ov, us.name, ot).join(us).switch(ov).join(ot)
        return [core.Override(r._data['url'], r.user.name, r.type.name)
                for r in query]

    @functools.lru_cache()
    @utils.listify()
    def images(self):
        for row in orm.Image.select():
            yield dict(
                url=row.url, source=row.source, status=row.status.label,
                notes=row.notes, data=row.data)

###############################################################################


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
        orm.connect(dbpath)
        self.wiki = wikidot.Wiki(site)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=20)

    def take_snapshot(self, forums=False):
        """Take new snapshot."""
        self._save_all_pages()
        if forums:
            self._save_forums()
        if 'scp-wiki' in self.wiki.site:
            self._save_meta()
        orm.queue.join()
        self._save_cache()
        orm.queue.join()
        log.info('Snapshot succesfully taken.')

    def auth(self, username, password):
        return self.wiki.auth(username, password)

    def _save_all_pages(self):
        """Iterate over the site pages, call _save_page for each."""
        orm.create_tables(
            'Page', 'Revision', 'Vote', 'ForumPost',
            'PageTag', 'ForumThread', 'User', 'Tag')
        count = self.wiki._list_pages_raw(body='%%total%%', limit=1)
        count = list(count)[0]['body']
        count = int(bs4.BeautifulSoup(count)('p')[0].text)
        bar = utils.ProgressBar('SAVING PAGES'.ljust(20), count)
        bar.start()
        for _ in self.pool.map(self._save_page, self.wiki.list_pages()):
            bar.value += 1
        bar.stop()

    @utils.ignore(requests.HTTPError)
    def _save_page(self, page):
        """Download contents, revisions, votes and discussion of the page."""
        orm.Page.create(
            id=page._id, url=page.url, thread=page._thread._id, html=page.html)
        history, votes = [map(vars, i) for i in (page.history, page.votes)]
        history, votes = map(orm.User.convert_to_id, (history, votes))
        tags = orm.Tag.convert_to_id(
            [{'tag': t} for t in page.tags], key='tag')
        for data, table in zip(
                (history, votes, tags), ('Revision', 'Vote', 'PageTag')):
            getattr(orm, table).insert_many(
                dict(i, page=page._id) for i in data)
        self._save_thread(page._thread)

    def _save_forums(self):
        """Download and save standalone forum threads."""
        orm.create_tables(
            'ForumPost', 'ForumThread', 'ForumCategory', 'User')
        cats = self.wiki.list_categories()
        cats = [i for i in cats if i.title != 'Per page discussions']
        orm.ForumCategory.insert_many(dict(
            id=c.id,
            title=c.title,
            description=c.description) for c in cats)
        total_size = sum(c.size for c in cats)
        bar = utils.ProgressBar('SAVING FORUM THREADS', total_size)
        bar.start()
        for cat in cats:
            threads = self.wiki.list_threads(cat.id)
            c_id = itertools.repeat(cat.id)
            for _ in self.pool.map(self._save_thread, threads, c_id):
                bar.value += 1
        bar.stop()

    def _save_thread(self, thread, c_id=None):
        orm.ForumThread.create(
            category=c_id, id=thread._id,
            title=thread.title, description=thread.description)
        posts = orm.User.convert_to_id(map(vars, thread.posts))
        orm.ForumPost.insert_many(
            dict(p, thread=thread._id) for p in posts)

    def _save_meta(self):
        orm.create_tables(
            'Image', 'ImageStatus', 'Override', 'OverrideType')
        licenses = {
            'PERMISSION GRANTED', 'BY-NC-SA CC', 'BY-SA CC', 'PUBLIC DOMAIN'}
        images = [i for i in self.wiki.list_images() if i.status in licenses]
        self.ibar = utils.ProgressBar(
            'SAVING IMAGES'.ljust(20), len(images))
        self.ibar.start()
        data = list(self.pool.map(self._save_image, images))
        self.ibar.stop()
        images = orm.ImageStatus.convert_to_id(
            map(vars, images), key='status')
        orm.Image.insert_many(
            dict(i, data=d) for i, d in zip(images, data) if d)
        overs = orm.User.convert_to_id(
            map(vars, self.wiki.list_overrides()))
        overs = orm.OverrideType.convert_to_id(overs, key='type')
        orm.Override.insert_many(overs)

    @utils.ignore(requests.RequestException)
    def _save_image(self, image):
        self.ibar.value += 1
        if not image.source:
            log.info('Image source not specified: ' + image.url)
            return
        return self.wiki.req.get(image.url, allow_redirects=True).content

    def _save_cache(self):
        for table in orm.User, orm.Tag, orm.OverrideType, orm.ImageStatus:
            if table.table_exists():
                table.write_ids('name')
