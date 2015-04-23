#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import concurrent.futures
import logging
import os
import peewee
import queue

from itertools import islice

###############################################################################
# Global Constants And Variables
###############################################################################

DBPATH = None
log = logging.getLogger('pyscp.orm')
pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
queue = queue.Queue()


def queue_execution(fn, args=(), kw={}):
    queue.put(dict(fn=fn, args=args, kw=kw))
    pool.submit(async_write)

###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.Proxy()


class BaseModel(peewee.Model):

    class Meta:
        database = db

    @classmethod
    def create(cls, **kw):
        queue_execution(fn=super().create, kw=kw)

    @classmethod
    def create_table(cls, safe=False):
        if not safe or not cls.table_exists():
            cls._id_cache = []
            queue_execution(fn=super().create_table)

    @classmethod
    def insert_many(cls, data):
        data_iter = iter(data)
        chunk = list(islice(data_iter, 500))
        while chunk:
            queue_execution(
                fn=lambda x: super(BaseModel, cls).insert_many(x).execute(),
                args=(chunk, ))
            chunk = list(islice(data_iter, 500))

    @classmethod
    def get_id(cls, value):
        if value not in cls._id_cache:
            # possible race condition, shouldn't harm anything even if occurs
            cls._id_cache.append(value)
        return cls._id_cache.index(value) + 1

    @classmethod
    def write_ids(cls, field_name):
        cls.insert_many([
            {'id': cls._id_cache.index(value) + 1, field_name: value}
            for value in set(cls._id_cache)])


class ForumCategory(BaseModel):
    title = peewee.CharField()
    description = peewee.TextField()


class ForumThread(BaseModel):
    category = peewee.ForeignKeyField(ForumCategory, null=True)
    title = peewee.CharField(null=True)
    description = peewee.TextField(null=True)


class Page(BaseModel):
    url = peewee.CharField(unique=True)
    html = peewee.TextField()
    thread = peewee.ForeignKeyField(
        ForumThread, related_name='page', null=True)


class User(BaseModel):
    name = peewee.CharField(unique=True)


class Revision(BaseModel):
    page = peewee.ForeignKeyField(Page, related_name='revisions', index=True)
    user = peewee.ForeignKeyField(User, related_name='revisions', index=True)
    number = peewee.IntegerField()
    time = peewee.DateTimeField()
    comment = peewee.CharField(null=True)


class Vote(BaseModel):
    page = peewee.ForeignKeyField(Page, related_name='votes', index=True)
    user = peewee.ForeignKeyField(User, related_name='votes', index=True)
    value = peewee.IntegerField()


class ForumPost(BaseModel):
    thread = peewee.ForeignKeyField(
        ForumThread, related_name='posts', index=True)
    user = peewee.ForeignKeyField(User, related_name='posts', index=True)
    parent = peewee.ForeignKeyField('self', null=True)
    title = peewee.CharField(null=True)
    time = peewee.DateTimeField()
    content = peewee.TextField()


class Tag(BaseModel):
    name = peewee.CharField(unique=True)


class PageTag(BaseModel):
    page = peewee.ForeignKeyField(Page, related_name='tags', index=True)
    tag = peewee.ForeignKeyField(Tag, related_name='pages', index=True)


class RewriteStatus(BaseModel):
    label = peewee.CharField(unique=True)


class Rewrite(BaseModel):
    page = peewee.ForeignKeyField(Page, to_field=Page.url, index=True)
    user = peewee.ForeignKeyField(User, index=True)
    status = peewee.ForeignKeyField(RewriteStatus)


class ImageStatus(BaseModel):
    label = peewee.CharField(unique=True)


class Image(BaseModel):
    url = peewee.CharField(unique=True)
    source = peewee.CharField()
    data = peewee.BlobField()
    status = peewee.ForeignKeyField(ImageStatus)
    notes = peewee.TextField(null=True)

###############################################################################
# Helper Functions
###############################################################################


def async_write(buffer=[]):
    item = queue.get()
    buffer.append(item)
    if len(buffer) > 500 or queue.empty():
        log.debug('Processing {} queue items.'.format(len(buffer)))
        with db.transaction():
            write_buffer(buffer)
        buffer.clear()


def write_buffer(buffer):
    for item in buffer:
        try:
            item['fn'](*item.get('args', ()), **item.get('kw', {}))
        except:
            log.exception(
                'Exception while processing queue item: {}'
                .format(item))
        queue.task_done()


def connect(dbpath, silent=False):
    global DBPATH
    DBPATH = dbpath
    if not silent:
        log.info('Connecting to the database at {}'.format(dbpath))
    db.initialize(peewee.SqliteDatabase(dbpath))
    db.connect()


def purge():
    log.info('Purging the database.')
    os.remove(DBPATH)
    connect(DBPATH, silent=True)
