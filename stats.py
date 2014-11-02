#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import csv
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

###############################################################################


def get_data(tag, method):
    # dates = defaultdict(list)
    # if tag is None:
    #     dquer = Page.select()
    # else:
    #     tagged = [i.url for i in Tag.select().where(Tag.tag == tag)]
    #     dquer = Page.select().where(Page.url << tagged)
    # for i in dquer:
    #     if i.created is not None:
    #         time = '{}-{:02d}'.format(i.created.year, i.created.month)
    #         if time != '2014-10':
    #             dates[time].append(i.url)
    query = Page.select()
    res = defaultdict(list)
    for i in query:
        if i.created is not None and i.rating is not None:
            res[i.created.weekday()].append(i.rating)
    return {k: statistics.mean(v) for k, v in res.items()}


def get_groups():
    users = [i.user for i in Vote.select(Vote.user).distinct()]
    authors = [i.author for i in Page.select(Page.author).distinct()]
    for i in authors:
        if i not in users:
            if not str(i).startswith('Anonymous'):
                users.append(i)
    groups = defaultdict(list)
    for i in users:
        n = Page.select().where(Page.author == i).count()
        gr_keys = {'0': [0], '1': [1], '2-3': [2, 3], '4-8': range(4, 9),
                   '9-20': range(9, 21)}
        for k, v in gr_keys.items():
            if n in v:
                groups[k].append(i)
                break
        else:
            groups['21+'].append(i)
    pr = namedtuple('PlotParameters', 'list style title')
    return [pr(groups['0'], 'k', '0 articles'),
            pr(groups['1'], 'b', '1 article'),
            pr(groups['2-3'], '#FF7F00', '2 to 3 articles'),
            pr(groups['4-8'], 'g', '4 to 8 articles'),
            pr(groups['9-20'], 'm', '9 to 20 articles'),
            pr(groups['21+'], 'r', 'more than 20 articles')]


def make_plot():
    fig = pyplot.figure()
    fig.set_size_inches(24, 16)
    all_dates = [
        '2008-07', '2008-08', '2008-09', '2008-10', '2008-11', '2008-12',
        '2009-01', '2009-02', '2009-03', '2009-04', '2009-05', '2009-06',
        '2009-07', '2009-08', '2009-09', '2009-10', '2009-11', '2009-12',
        '2010-01', '2010-02', '2010-03', '2010-04', '2010-05', '2010-06',
        '2010-07', '2010-08', '2010-09', '2010-10', '2010-11', '2010-12',
        '2011-01', '2011-02', '2011-03', '2011-04', '2011-05', '2011-06',
        '2011-07', '2011-08', '2011-09', '2011-10', '2011-11', '2011-12',
        '2012-01', '2012-02', '2012-03', '2012-04', '2012-05', '2012-06',
        '2012-07', '2012-08', '2012-09', '2012-10', '2012-11', '2012-12',
        '2013-01', '2013-02', '2013-03', '2013-04', '2013-05', '2013-06',
        '2013-07', '2013-08', '2013-09', '2013-10', '2013-11', '2013-12',
        '2014-01', '2014-02', '2014-03', '2014-04', '2014-05', '2014-06',
        '2014-07', '2014-08', '2014-09']
    over_time = False
    pr = namedtuple('PlotParameters', 'tag method style title')
    groups = [pr(None, False, 'c-', 'Pages (net)')]
    #groups = get_groups()
    for i in groups:
        l = get_data(i.tag, i.method)
        if over_time:
            for j in all_dates:
                if j not in l.keys():
                    l[j] = 0
            dates = sorted(l.keys())
            converted_dates = [
                datetime.datetime.strptime(i, '%Y-%m') for i in dates]
            x_axis = converted_dates
        else:
            # for j in range(min(l.keys()), max(l.keys()), 100):
            #     if not j in l.keys():
            #         l[j] = 0
            x_axis = sorted(l.keys())
        #x_axis = range(len(l.keys()))
        y_axis = [v for k, v in sorted(l.items())]
        pyplot.plot(x_axis, y_axis, i.style, linewidth=2)
    #pyplot.plot(converted_dates, [0] * len(all_dates), 'k:', linewidth=.5)
    #pyplot.plot(converted_dates, [100] * len(all_dates), 'k:', linewidth=.5)
    ax = pyplot.gcf().axes[0]
    #ax.legend([i.title for i in groups])
    ax.set_xticklabels(['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                        'Friday', 'Saturday', 'Sunday'])
    #ax.set_xlim(0, 23)
    #ax.xaxis.set_major_locator(pyplot.MultipleLocator(4))
    #ax.xaxis.set_minor_locator(pyplot.MultipleLocator(1))
    ax.xaxis.set_label_text('Day of the Week')
    ax.yaxis.set_label_text('Average Rating')
    #ax.set_xscale('log')
    #ax.set_yscale('log')
    if over_time:
        ax.xaxis.set_major_locator(mpdates.YearLocator())
        ax.xaxis.set_minor_locator(mpdates.MonthLocator())
        fig.autofmt_xdate()
    #pyplot.show()
    pyplot.savefig("/home/anqxyr/heap/figure_01.png",
                   dpi=100, bbox_inches='tight')


def make_user_tables(func, only_authors=False):
    authors = [i.author for i in Page.select(Page.author).distinct()]
    authors = [i for i in authors
               if i is not None
               and not i.startswith('Anonymous')]
    if not only_authors:
        users = [i.user for i in Vote.select(Vote.user).distinct()]
        for i in authors:
            if i not in users:
                users.append(i)
    else:
        users = authors
    filename = '/home/anqxyr/heap/_scp/{}.csv'.format(func.__name__)
    with open(filename, 'w') as F:
        writer = csv.writer(F)
        writer.writerow(func())
        N = len(users)
        for n, i in enumerate(users):
            print('{}/{}: {}'.format(n, N, i))
            writer.writerow(func(i))


def t_user_gen(user=None):
    if user is None:
        return ('USER',
                'REVISIONS MADE',
                'TOTAL VOTES',
                'NET VOTE RATING',
                'UPVOTES',
                'DOWNVOTES',
                'UPVOTES PERCENT')
    query = Vote.select().where(Vote.user == user)
    upvotes = query.where(Vote.vote == 1).count()
    downvotes = query.where(Vote.vote == -1).count()
    revisions_made = Revision.select().where(Revision.user == user).count()
    total_votes = upvotes + downvotes
    net_vote_rating = upvotes - downvotes
    if total_votes != 0:
        upvotes_percent = '{:.2f}%'.format(100 * upvotes / total_votes)
    else:
        upvotes_percent = '0.00%'
    return (user,
            revisions_made,
            total_votes,
            net_vote_rating,
            upvotes,
            downvotes,
            upvotes_percent)


def t_author_gen(user=None):
    if user is None:
        return ('USER',
                'PAGES CREATED',
                'NET RATING',
                'AV. RATING',
                'WORD COUNT',
                'AV. WORD COUNT',
                'IMAGE COUNT')
    query = Page.select().where(Page.author == user)
    pages_created = query.count()
    net_author_rating = 0
    word_count = 0
    image_count = 0
    for j in query:
        word_count += j.wordcount if j.wordcount is not None else 0
        image_count += j.images if j.images is not None else 0
        net_author_rating += j.rating if j.rating is not None else 0
    average_rating = '{:.2f}'.format(net_author_rating / pages_created)
    average_word_count = '{:.2f}'.format(word_count / pages_created)
    return (user,
            pages_created,
            net_author_rating,
            average_rating,
            word_count,
            average_word_count,
            image_count)


def t_user_tags(user=None):
    tags = [i.tag for i in Tag.select(Tag.tag).distinct()]
    tags.sort()
    if user is None:
        return ('USER',
                'MOST FAVORITE TAG 1',
                'MOST FAVORITE TAG 2',
                'MOST FAVORITE TAG 3',
                'MOST FAVORITE TAG 4',
                'MOST FAVORITE TAG 5',
                'MOST FAVORITE TAG 6',
                'MOST FAVORITE TAG 7',
                'MOST FAVORITE TAG 8',
                'MOST FAVORITE TAG 9',
                'MOST FAVORITE TAG 10',
                'LEAST FAVORITE TAG 1',
                'LEAST FAVORITE TAG 2',
                'LEAST FAVORITE TAG 3',
                'LEAST FAVORITE TAG 4',
                'LEAST FAVORITE TAG 5')
    votes = {i.url: i.vote for i in Vote.select().where(Vote.user == user)}
    tmp = Tag.select().where(Tag.url << list(votes.keys()))
    tagged_as = defaultdict(list)
    for i in tmp:
        tagged_as[i.url].append(i.tag)
    res = Counter()
    for k, v in votes.items():
        for j in tagged_as[k]:
            res[j] += v
    tup = (user, )
    for k, v in res.most_common(10):
        tup += ('{} ({})'.format(k, v), )
    for k, v in res.most_common()[:-6:-1]:
        tup += ('{} ({})'.format(k, v), )
    return tup


def t_author_tags(user=None):
    if user is None:
        return ('USER',
                'MOST FAVORITE TAG 1',
                'MOST FAVORITE TAG 2',
                'MOST FAVORITE TAG 3',
                'MOST FAVORITE TAG 4',
                'MOST FAVORITE TAG 5',
                'MOST FAVORITE TAG 6',
                'MOST FAVORITE TAG 7',
                'MOST FAVORITE TAG 8',
                'MOST FAVORITE TAG 9',
                'MOST FAVORITE TAG 10')
    tags = [i.tag for i in Tag.select(Tag.tag).distinct()]
    tags.sort()
    res = Counter()
    for i in Page.select().where(Page.author == user):
        for j in Tag.select().where(Tag.url == i.url):
            res[j.tag] += 1
    tup = (user, )
    n = Page.select().where(Page.author == user).count()
    for k, v in res.most_common(10):
        tup += ('{} ({} - {:.2f}%)'.format(k, v, 100 * v / n), )
    return tup


def t_votes_per_year(user=None):
    if user is None:
        return ('USER',
                '2008 TOTAL',
                '2008 NET',
                '2009 TOTAL',
                '2009 NET',
                '2010 TOTAL',
                '2010 NET',
                '2011 TOTAL',
                '2011 NET',
                '2012 TOTAL',
                '2012 NET',
                '2013 TOTAL',
                '2013 NET',
                '2014 TOTAL',
                '2014 NET',)
    res = defaultdict(list)
    dates = {i.url: i.created for i in Page.select()}
    for i in Vote.select().where(Vote.user == user):
        year = dates[i.url].year
        res[year].append(i.vote)
    tup = (user, )
    for k, v in sorted(res.items()):
        tup += (len(v), sum(v))
    return tup


WORDFR = Counter()


def get_word_freq():
    query = Word.select()
    count = query.count()
    l = count // 100000 + 2
    for i in range(1, l):
        print('Page {} out of {}'.format(i, l))
        for j in query.paginate(i, 100000):
            WORDFR[j.word] += 100 * j.count / count


def t_author_words(user=None):
    if user is None:
        return ('USER',
                'MOST USED WORD 1',
                'MOST USED WORD 2',
                'MOST USED WORD 3',
                'MOST USED WORD 4',
                'MOST USED WORD 5',
                'MOST USED WORD 6',
                'MOST USED WORD 7',
                'MOST USED WORD 8',
                'MOST USED WORD 9',
                'MOST USED WORD 10')
    if not WORDFR:
        get_word_freq()
    pages = [i.url for i in Page.select().where(Page.author == user)]
    cn = Counter()
    for i in Word.select().where(Word.url << pages):
        cn[i.word] += i.count
    n = sum(cn.values())
    for k, v in cn.items():
        cn[k] = (100 * v / n) - WORDFR[k]
    tup = (user, )
    for k, v in cn.most_common(10):
        tup += ('{} ({:+.2f}Δ)'.format(k, v), )
    return tup


def count_words():
    cn = Counter()
    query = Word.select().where(Word.word.contains('amnesia')
                                | Word.word.contains('amnes'))
    l = query.count() // 100000 + 2
    for i in range(1, l):
        print('Page {} out of {}'.format(i, l))
        for j in query.paginate(i, 100000):
            cn[j.word] += j.count
    for k, v in cn.most_common():
        print(k, v)
    print('------')


def rev_stats():
    pages = {}
    for i in Page.select():
        pages[i.url] = i.created
    n = 0
    for i in Revision.select():
        if not i.comment:
            n += 1
    print(n)


def main():
    #fill_db()
    #make_plot()
    #make_user_tables(t_author_words, only_authors=True)
    #count_words()
    #rev_stats()
    for i in Word.select().where(Word.word.regexp('.{100,1000}')):
        print('{} ({})'.format(i.word, i.url))


if __name__ == "__main__":
    main()
