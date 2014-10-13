#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import peewee
import scp_crawler

from bs4 import BeautifulSoup

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

###############################################################################


def process_page(page):
    print("Processing {}".format(page.title))
    gather_page_stats(page)
    gather_vote_stats(page)
    gather_word_stats(page)


def gather_page_stats(page):
    rewr = page.authors[1]
    text = BeautifulSoup(page.data).text
    charcount = len(text)
    wordcount = len(text.split(' '))
    PageStats.create(url=page.url,
                     author=page.authors[0],
                     rewrite_author=rewr,
                     created=page.history[0].time,
                     rating=page.rating
                     comments=page.comments
                     charcount=charcount,
                     wordcount=wordcount,
                     images=len(page.images),
                     revisions=len(page.history))


def main():
    for page in scp_crawler.all_pages():
        process_page(page)


main()
