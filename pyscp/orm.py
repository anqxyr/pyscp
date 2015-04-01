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


class Page(BaseModel):
    page_id = peewee.IntegerField(primary_key=True)
    url = peewee.CharField(unique=True)
    html = peewee.TextField()
    thread_id = peewee.IntegerField(null=True)


class Revision(BaseModel):
    revision_id = peewee.IntegerField(primary_key=True)
    page_id = peewee.IntegerField(index=True)
    number = peewee.IntegerField()
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()
    comment = peewee.CharField(null=True)


class Vote(BaseModel):
    page_id = peewee.IntegerField(index=True)
    user = peewee.CharField(index=True)
    value = peewee.IntegerField()


class ForumPost(BaseModel):
    post_id = peewee.IntegerField(primary_key=True)
    thread_id = peewee.IntegerField(index=True)
    title = peewee.CharField(null=True)
    content = peewee.TextField()
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()
    parent = peewee.IntegerField(null=True)


class ForumThread(BaseModel):
    thread_id = peewee.IntegerField(primary_key=True)
    title = peewee.CharField()
    description = peewee.TextField()
    category_id = peewee.IntegerField()


class ForumCategory(BaseModel):
    category_id = peewee.IntegerField(primary_key=True)
    title = peewee.CharField()
    description = peewee.TextField()


class Tag(BaseModel):
    page_id = peewee.CharField(index=True)
    tag = peewee.CharField(index=True)


class Rewrite(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    status = peewee.CharField()


class Image(BaseModel):
    url = peewee.CharField(unique=True)
    source = peewee.CharField()
    data = peewee.BlobField()
    status = peewee.CharField()
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
