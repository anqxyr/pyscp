#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import concurrent.futures
import logging
import peewee
import queue

from itertools import islice

###############################################################################
# Global Constants And Variables
###############################################################################

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
    def create_table(cls):
        if not hasattr(cls, '_id_cache'):
            cls._id_cache = []
        queue_execution(fn=super().create_table, args=(True,))

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
    def convert_to_id(cls, data, key='user'):
        for row in data:
            if row[key] not in cls._id_cache:
                cls._id_cache.append(row[key])
            row[key] = cls._id_cache.index(row[key]) + 1
            yield row

    @classmethod
    def write_ids(cls, field_name):
        cls.insert_many([
            {'id': cls._id_cache.index(value) + 1, field_name: value}
            for value in set(cls._id_cache)])
        cls._id_cache.clear()


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


class OverrideType(BaseModel):
    name = peewee.CharField(unique=True)


class Override(BaseModel):
    url = peewee.ForeignKeyField(Page, to_field=Page.url, index=True)
    user = peewee.ForeignKeyField(User, index=True)
    type = peewee.ForeignKeyField(OverrideType)


class ImageStatus(BaseModel):
    name = peewee.CharField(unique=True)


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


def create_tables(*tables):
    for table in tables:
        eval(table).create_table()


def connect(dbpath):
    log.info('Connecting to the database at {}'.format(dbpath))
    db.initialize(peewee.SqliteDatabase(dbpath))
    db.connect()


###############################################################################
# Macros
###############################################################################


def votes_by_user(user):
    up, down = [], []
    for vote in (Vote.select().join(User).where(User.name == user)):
        if vote.value == 1:
            up.append(vote.page.url)
        else:
            down.append(vote.page.url)
    return {'+': up, '-': down}
