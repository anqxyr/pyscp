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
    if page.url in [i.url for i in pages]:
        return
    print("Processing {}".format(page.title))
    data = PageData()
    data.url = page.url
    data.charcount = len(page.data)
    data.wordcount = len(page.data.split(" "))
    data.rating = page.rating
    history_soup = BeautifulSoup(page.history)
    for row in reversed(history_soup.select("tr")):
        edit_au, edit_time, desc = (i.text for i in row.select("td")[4:7])
        data.time = arrow.get(edit_time, "DD MMM YYYY HH:mm").format("YYYY-MM")
        break
    data.tags = page.tags
    pages.append(data)
    for c in page.list_children():
        process_page(c)


def main():
    for page in scp_crawler.all_pages():
        process_page(page)


main()
