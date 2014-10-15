#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import peewee
import re
import scp_crawler
import statistics

from bs4 import BeautifulSoup
from collections import Counter

###############################################################################
# Global Constants
###############################################################################

STATDB = '/home/anqxyr/heap/scp_stats.db'

###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(STATDB)


class BaseModel(peewee.Model):

    class Meta:
        database = db


class Page(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField(null=True)
    rewrite_author = peewee.CharField(null=True)
    created = peewee.DateTimeField(null=True)
    rating = peewee.IntegerField(null=True)
    comments = peewee.IntegerField(null=True)
    charcount = peewee.IntegerField(null=True)
    wordcount = peewee.IntegerField(null=True)
    images = peewee.IntegerField(null=True)
    revisions = peewee.IntegerField(null=True)


class Vote(BaseModel):
    url = peewee.CharField()
    user = peewee.CharField()
    vote = peewee.IntegerField()


class Word(BaseModel):
    url = peewee.CharField()
    word = peewee.CharField()
    count = peewee.IntegerField()


class Revision(BaseModel):
    url = peewee.CharField()
    number = peewee.IntegerField()
    user = peewee.CharField()
    time = peewee.CharField()
    comment = peewee.CharField()

class Tag(BaseModel):
    tag = peewee.CharField()
    url = peewee.CharField()


db.connect()
db.create_tables([Page, Vote, Word, Revision, Tag], safe=True)

###############################################################################


def fill_db():
    Page.delete().execute()
    Vote.delete().execute()
    Word.delete().execute()
    Tag.delete().execute()
    for page in scp_crawler.get_all():
        print("Processing {} ({})".format(page.title, page.url))
        gather_page_stats(page)
        gather_vote_stats(page)
        gather_word_stats(page)
        gather_tags(page)


def gather_page_stats(page):
    if page.history:
        time = page.history[0].time
        auth = page.authors[0].username
        try:
            rewr = page.authors[1].username
        except:
            rewr = None
    else:
        auth = rewr = time = None
    if page.data:
        text = BeautifulSoup(page.data).text
        charcount = len(text)
        wordcount = len(re.findall(r"[\w'█_-]+", text))
    else:
        charcount = wordcount = None
    Page.create(url=page.url,
                     author=auth,
                     rewrite_author=rewr,
                     created=time,
                     rating=page.rating,
                     comments=page.comments,
                     charcount=charcount,
                     wordcount=wordcount,
                     images=len(page.images),
                     revisions=len(page.history))


def gather_vote_stats(page):
    to_insert = []
    for i in page.votes:
        if i.vote == '+':
            vote = 1
        elif i.vote == '-':
            vote = -1
        data_dict = {'url': page.url, 'user': i.user, 'vote': vote}
        to_insert.append(data_dict)
    with db.transaction():
        for idx in range(0, len(to_insert), 500):
            Vote.insert_many(to_insert[idx:idx + 500]).execute()


def gather_word_stats(page):
    try:
        text = BeautifulSoup(page.data).text
    except:
        return
    text = text.replace('[DATA EXPUNGED]', 'DATA_EXPUNGED')
    text = text.replace('[DATA REDACTED]', 'DATA_REDACTED')
    text = text.replace('’', "'")
    text = re.sub(r'Site ([\d]+)', r'Site-\1', text)
    words = re.findall(r"[\w'█_-]+", text)
    words = [i.lower().strip("'") for i in words]
    cn = Counter(words)
    to_insert = []
    for k, v in cn.items():
        data_dict = {'url': page.url, 'word': k, 'count': v}
        to_insert.append(data_dict)
    with db.transaction():
        for idx in range(0, len(to_insert), 500):
            Word.insert_many(to_insert[idx:idx + 500]).execute()


def gather_tags(page):
    tags = page.tags
    new_tags = []
    for tag in tags:
        tag = tag.replace('-', '_')
        tag = tag.replace('&', '')
        tag = tag.replace('2000', '_2000')
        new_tags.append(tag)
    Tag.create(url=page.url, **{i: True for i in new_tags})

def main():
    #fill_db()
    exit()
    #cn = Counter()
    n = 0
    l = []
    #skips = [i.url for i in Tags.select().where(Tags.tale == True)]
    query = Page.select()#.where(PageStats.url << skips)
    for i in query:
        if i.revisions is not None:
            l.append(i.revisions)
    #l = list(reversed(sorted(l)))
    #print(l[:5])
    print(sum(l))
    print(statistics.mean(l))
    print(statistics.stdev(l))
    


main()
