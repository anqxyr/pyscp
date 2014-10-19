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
    x_axis = 'wordcount'
    y_axis = 'rating'
    if tag is not None:
        with_tag = [i.url for i in Tag.select().where(Tag.tag == tag)]
        query = cls.select().where(cls.url << with_tag)
    else:
        query = cls.select()
    res = defaultdict(list)
    for i in query:
        xpoint = getattr(i, x_axis, None)
        if xpoint is not None:
            value = getattr(i, y_axis, None)
            if x_axis == 'created':
                xpoint = '{}-{:02d}'.format(xpoint.year, xpoint.month)
            if value is not None:
                res[xpoint].append(value)
    return res


def make_plot():
    fig = pyplot.figure()
    fig.set_size_inches(24, 16)
    pr = namedtuple('PlotParameters', 'tag style')
    all_dates = ['2008-07', '2008-08', '2008-09', '2008-10', '2008-11',
        '2008-12', '2009-01', '2009-02', '2009-03', '2009-04', '2009-05',
        '2009-06', '2009-07', '2009-08', '2009-09', '2009-10', '2009-11',
        '2009-12', '2010-01', '2010-02', '2010-03', '2010-04', '2010-05',
        '2010-06', '2010-07', '2010-08', '2010-09', '2010-10', '2010-11',
        '2010-12', '2011-01', '2011-02', '2011-03', '2011-04', '2011-05',
        '2011-06', '2011-07', '2011-08', '2011-09', '2011-10', '2011-11',
        '2011-12', '2012-01', '2012-02', '2012-03', '2012-04', '2012-05',
        '2012-06', '2012-07', '2012-08', '2012-09', '2012-10', '2012-11',
        '2012-12', '2013-01', '2013-02', '2013-03', '2013-04', '2013-05',
        '2013-06', '2013-07', '2013-08', '2013-09', '2013-10', '2013-11',
        '2013-12', '2014-01', '2014-02', '2014-03', '2014-04', '2014-05',
        '2014-06', '2014-07', '2014-08', '2014-09']
    over_time = False
    groups = [pr(None, 'b-'), pr('scp', 'r-'), pr('tale', 'g-')]
    #groups = [pr('scp', 'r-'), pr('tale', 'g-')]
    for i in groups:
        l = get_data(i.tag)
        if over_time:
            for j in all_dates:
                if j not in l.keys():
                    l[j] = [0]
            dates = sorted(l.keys())
            converted_dates = [
                datetime.datetime.strptime(i, '%Y-%m') for i in dates]
            x_axis = converted_dates
        else:
            for j in range(min(l.keys()), max(l.keys()), 5):
                if not j in l.keys():
                    l[j] = [0]
            x_axis = sorted(l.keys())
        y_axis = [statistics.mean(v) for k, v in sorted(l.items())]
        pyplot.plot(x_axis, y_axis, i.style, linewidth=2)
    ax = pyplot.gcf().axes[0]
    ax.legend(['Pages', 'Skips', 'Tales'])
    #ax.legend(['Skips', 'Tales'])
    ax.xaxis.set_label_text('Revisions')
    ax.yaxis.set_label_text('Word Count')
    if over_time:
        ax.xaxis.set_major_locator(mpdates.YearLocator())
        ax.xaxis.set_minor_locator(mpdates.MonthLocator())
        fig.autofmt_xdate()
    pyplot.savefig("/home/anqxyr/heap/figure_01.png",
                   dpi=100, bbox_inches='tight')


def main():
    #fill_db()
    #exit()
    make_plot()


main()
