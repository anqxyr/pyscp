#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import peewee
import re
import scp_crawler

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


class PageStats(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    rewrite_author = peewee.CharField(null=True)
    created = peewee.DateTimeField()
    rating = peewee.IntegerField()
    comments = peewee.IntegerField()
    charcount = peewee.IntegerField()
    wordcount = peewee.IntegerField()
    images = peewee.IntegerField()
    revisions = peewee.IntegerField()


class VoteStats(BaseModel):
    url = peewee.CharField()
    user = peewee.CharField()
    vote = peewee.IntegerField()


class WordStats(BaseModel):
    url = peewee.CharField()
    word = peewee.CharField()
    count = peewee.IntegerField()


db.connect()
db.create_tables([PageStats, VoteStats, WordStats], safe=True)

###############################################################################


def fill_db():
    PageStats.delete().execute()
    VoteStats.delete().execute()
    WordStats.delete().execute()
    for page in [scp_crawler.Page('http://www.scp-wiki.net/scp-478')]:
        print("Processing {}".format(page.title))
        gather_page_stats(page)
        gather_vote_stats(page)
        gather_word_stats(page)
        exit()


def gather_page_stats(page):
    try:
        rewr = page.authors[1]
    except IndexError:
        rewr = None
    text = BeautifulSoup(page.data).text
    charcount = len(text)
    wordcount = len(text.split(' '))
    PageStats.create(url=page.url,
                     author=page.authors[0],
                     rewrite_author=rewr,
                     created=page.history[0].time,
                     rating=page.rating,
                     comments=page.comments,
                     charcount=charcount,
                     wordcount=wordcount,
                     images=len(page.images),
                     revisions=len(page.history))


def gather_vote_stats(page):
    for i in page.votes:
        if i.vote == '+':
            vote = 1
        elif i.vote == '-':
            vote = -1
        VoteStats.create(url=page.url, user=i.user, vote=vote)


def gather_word_stats(page):
    text = BeautifulSoup(page.data).text
    text = text.replace('[DATA EXPUNGED]', 'DATA_EXPUNGED')
    text = text.replace('[DATA REDACTED]', 'DATA_REDACTED')
    text = text.replace('’', "'")
    text = re.sub(r'Site ([\d]+)', r'Site-\1', text)
    words = re.findall(r"[\w'█_-]+", text)
    words = [i.lower() for i in words]
    cn = Counter(words)
    import pprint
    pprint.pprint(cn)    

def main():
    fill_db()


main()
