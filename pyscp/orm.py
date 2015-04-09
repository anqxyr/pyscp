#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import concurrent.futures
import logging
import os
import peewee
import queue

###############################################################################
# Global Constants And Variables
###############################################################################

DBPATH = None
log = logging.getLogger('scp.crawler.orm')
pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
queue = queue.Queue()

###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(None)


class BaseModel(peewee.Model):

    class Meta:
        database = db

    @classmethod
    def create(cls, **kwargs):
        queue.put({'func': super().create, 'kwargs': kwargs})
        pool.submit(async_write)

    @classmethod
    def create_table(cls):
        queue.put({'func': super().create_table})
        pool.submit(async_write)

    @classmethod
    def insert_many(cls, data):
        data = list(data)
        super_insert = super().insert_many
        insert = lambda x: super_insert(x).execute()
        for idx in range(0, len(data), 500):
            queue.put({'func': insert, 'args': (data[idx:idx + 500], )})
            pool.submit(async_write)


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
    name = peewee.CharField(index=True)


class PageTag(BaseModel):
    page = peewee.ForeignKeyField(Page, index=True)
    tag = peewee.ForeignKeyField(Tag, index=True)


class RewriteStatus(BaseModel):
    name = peewee.CharField(unique=True)


class Rewrite(BaseModel):
    page = peewee.ForeignKeyField(Page, to_field=Page.url, index=True)
    user = peewee.ForeignKeyField(User, index=True)
    status = peewee.ForeignKeyField(RewriteStatus, index=True)


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
            for item in buffer:
                try:
                    item['func'](
                        *item.get('args', ()), **item.get('kwargs', {}))
                except:
                    log.exception(
                        'Exception while processing queue item: {}'
                        .format(item))
                queue.task_done()
        buffer.clear()


def connect(dbpath, silent=False):
    global DBPATH
    DBPATH = dbpath
    if not silent:
        log.info('Connecting to the database at {}'.format(dbpath))
    db.init(dbpath)
    db.connect()


def purge():
    log.info('Purging the database.')
    os.remove(DBPATH)
    connect(DBPATH, silent=True)
