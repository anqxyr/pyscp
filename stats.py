#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import datetime
import peewee
import re
import scp_crawler
import statistics

from bs4 import BeautifulSoup
from collections import Counter, defaultdict, namedtuple
from matplotlib import pyplot, dates as mpdates

###############################################################################
# Global Constants
###############################################################################

STATDB = '/home/anqxyr/heap/_scp/stats.db'

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
    time = peewee.DateTimeField()
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
        gather_revisions(page)


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
    if page.tags == []:
        return
    to_insert = []
    for i in page.tags:
        data_dict = {'tag': i, 'url': page.url}
        to_insert.append(data_dict)
    Tag.insert_many(to_insert).execute()


def gather_revisions(page):
    if page.history == []:
        return
    to_insert = []
    for i in page.history:
        data_dict = {'url': page.url,
                     'number': i.number,
                     'user': i.user,
                     'time': i.time,
                     'comment': i.comment}
        to_insert.append(data_dict)
    with db.transaction():
        for idx in range(0, len(to_insert), 500):
            Revision.insert_many(to_insert[idx:idx + 500]).execute()


def get_data(tag=None):
    cls = Page
    attr = 'rating'
    if tag is not None:
        with_tag = [i.url for i in Tag.select().where(Tag.tag == tag)]
        query = cls.select().where(cls.url << with_tag)
    else:
        query = cls.select()
    res = defaultdict(list)
    for i in query:
        value = getattr(i, attr, None)
        if value is not None and i.created is not None:
            time = '{}-{:02d}'.format(i.created.year, i.created.month)
            res[time].append(value)
    return res


def make_plot():
    fig = pyplot.figure()
    pr = namedtuple('PlotParameters', 'tag style')
    groups = [pr(None, 'b-'), pr('scp', 'r-'), pr('tale', 'g-')]
    for i in groups:
        #pyplot.subplot(n)
        l = get_data(i.tag)
        dates = sorted(l.keys())
        converted_dates = [
            datetime.datetime.strptime(i, '%Y-%m') for i in dates]
        x_axis = (converted_dates)
        y_axis = [statistics.mean(v) for k, v in sorted(l.items())]
        pyplot.plot(x_axis, y_axis, i.style, linewidth=2)
    ax = pyplot.gcf().axes[0]
    ax.legend(['Pages', 'Skips', 'Tales'])
    ax.xaxis.set_label_text('Time')
    ax.yaxis.set_label_text('Rating (Average)')
    ax.xaxis.set_major_locator(mpdates.YearLocator())
    ax.xaxis.set_minor_locator(mpdates.MonthLocator())
    fig.autofmt_xdate()
    pyplot.show()


def main():
    #fill_db()
    #exit()
    make_plot()


main()
