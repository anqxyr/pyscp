#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import logging
import peewee
import concurrent.futures
import queue

###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.crawler.orm')
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
queue = queue.Queue()
buffer = []
buffer_index = 1

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
        executor.submit(async_write)

    @classmethod
    def create_table(cls):
        queue.put({'func': super().create_table})
        executor.submit(async_write)

    @classmethod
    def insert_many(cls, data):
        super_insert = super().insert_many
        insert = lambda x: super_insert(x).execute()
        for idx in range(0, len(data), 500):
            queue.put({'func': insert, 'args': (data[idx:idx + 500], )})
            executor.submit(async_write)


class Page(BaseModel):
    pageid = peewee.IntegerField(primary_key=True)
    url = peewee.CharField(unique=True)
    html = peewee.TextField()
    thread_id = peewee.IntegerField(null=True)


class Revision(BaseModel):
    pageid = peewee.IntegerField(index=True)
    number = peewee.IntegerField()
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()
    comment = peewee.CharField()


class Vote(BaseModel):
    pageid = peewee.IntegerField(index=True)
    user = peewee.CharField(index=True)
    vote = peewee.IntegerField()


class ForumPost(BaseModel):
    post_id = peewee.IntegerField(primary_key=True)
    thread_id = peewee.IntegerField(index=True)
    title = peewee.CharField()
    content = peewee.TextField()
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()
    parent = peewee.CharField(null=True)


class ForumThread(BaseModel):
    thread_id = peewee.IntegerField(primary_key=True)
    title = peewee.CharField()
    description = peewee.TextField()
    category_id = peewee.IntegerField()


class ForumCategory(BaseModel):
    category_id = peewee.IntegerField(primary_key=True)
    title = peewee.CharField()
    description = peewee.TextField()


class Image(BaseModel):
    url = peewee.CharField(unique=True)
    source = peewee.CharField()
    data = peewee.BlobField()
    # for future use:
    #status = peewee.CharField()


class Author(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    override = peewee.BooleanField()


class Tag(BaseModel):
    tag = peewee.CharField(index=True)
    url = peewee.CharField(index=True)

###############################################################################
# Helper Functions
###############################################################################


def async_write():
    item = queue.get()
    buffer.append(item)
    if len(buffer) > 500 or queue.empty():
        flush_buffer()


def flush_buffer():
    global buffer, buffer_index
    buffer_size = len(buffer)
    logger.debug(
        'Processing queue items #{}-{}'
        .format(buffer_index, buffer_index + buffer_size))
    buffer_index += buffer_size
    with db.transaction():
        for item in buffer:
            func = item['func']
            args = item.get('args', ())
            kwargs = item.get('kwargs', {})
            try:
                func(*args, **kwargs)
            except:
                logger.exception('Exception while processing queue item.')
            queue.task_done()
    buffer = []


def wait():
    if queue.qsize() > 500:
        logger.info('Queue full, pausing.')
        queue.join()


def connect(dbpath):
    logger.info('Connecting to the database at {}'.format(dbpath))
    db.init(dbpath)
    db.connect()


def purge():
    logger.info('Purging the database.')
    tables = [Page, Revision, Vote, ForumPost, ForumThread, ForumCategory,
              Image, Author, Tag]
    for i in tables:
        i.drop_table(fail_silently=True)
