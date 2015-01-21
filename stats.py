#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import collections
import crawler
import csv
import logging
import os
import peewee
import pygal
import re

from statistics import mode, pstdev

###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.stats')
logger.setLevel(logging.DEBUG)
CSV_OUT_PATH = '/home/anqxyr/heap/_scp/csv_stats/'

###############################################################################
# Database ORM Classes
###############################################################################

DBPATH = '/home/anqxyr/heap/_scp/stats.db'
db = peewee.SqliteDatabase(DBPATH)


class BaseModel(peewee.Model):

    class Meta:
        database = db

    @classmethod
    def count(cls, expr=None, distinct=None):
        if distinct is None:
            query = cls.select(peewee.fn.Count())
        else:
            query = cls.select(peewee.fn.Count(peewee.fn.Distinct(distinct)))
        if expr is not None:
            query = query.where(expr)
        return query.scalar()

    @classmethod
    def sum(cls, attr, expr=None):
        query = cls.select(peewee.fn.Sum(getattr(cls, attr)))
        if expr is not None:
            query = query.where(expr)
        return query.scalar()

    @classmethod
    def mean(cls, attr, expr=None):
        query = cls.select(peewee.fn.Avg(getattr(cls, attr)))
        if expr is not None:
            query = query.where(expr)
        return query.scalar()

    @classmethod
    def list(cls, attr, expr=None, distinct=False):
        query = cls.select(getattr(cls, attr))
        if expr is not None:
            query = query.where(expr)
        if distinct:
            query = query.distinct()
        return [getattr(i, attr) for i in query
                if getattr(i, attr) is not None]


class Page(BaseModel):
    pageid = peewee.IntegerField(primary_key=True)
    url = peewee.CharField(unique=True)
    title = peewee.CharField()
    rating = peewee.IntegerField(null=True)
    author = peewee.CharField()
    created = peewee.DateTimeField()
    wordcount = peewee.IntegerField()
    revisions = peewee.IntegerField()
    comments = peewee.IntegerField()
    images = peewee.IntegerField()


class Revision(BaseModel):
    pageid = peewee.IntegerField(index=True)
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()


class Vote(BaseModel):
    pageid = peewee.IntegerField(index=True)
    user = peewee.CharField(index=True)
    value = peewee.IntegerField()


class ForumPost(BaseModel):
    pageid = peewee.IntegerField(index=True)
    title = peewee.CharField()
    wordcount = peewee.IntegerField()
    user = peewee.CharField(index=True)
    time = peewee.DateTimeField()


class Tag(BaseModel):
    pageid = peewee.IntegerField(index=True)
    tag = peewee.CharField(index=True)


class User(BaseModel):
    name = peewee.CharField(unique=True)
    pages = peewee.IntegerField()
    wordcount = peewee.IntegerField(null=True)
    comments = peewee.IntegerField()
    edits = peewee.IntegerField()
    first_activity = peewee.DateTimeField(null=True)
    rating = peewee.IntegerField(null=True)
    upvoted = peewee.IntegerField()
    downvoted = peewee.IntegerField()

###############################################################################
# DB Generating Functions
###############################################################################


def _process_page(url):
    p = crawler.Page(url)
    logger.info('Processing page: {}'.format(url))
    Page.create(
        pageid=p._pageid,
        url=p.url,
        title=p.title,
        rating=p.rating,
        author=p.author,
        created=p.created,
        wordcount=p.wordcount,
        revisions=len(p.history),
        comments=len(p.comments),
        images=len(p.images))
    for i in p.history:
        Revision.create(pageid=p._pageid, user=i.user, time=i.time)
    for i in p.votes:
        Vote.create(pageid=p._pageid, user=i.user, value=i.value)
    for i in p.comments:
        ForumPost.create(
            pageid=p._pageid,
            title=i.title,
            user=i.user,
            time=i.time,
            wordcount=len(re.findall(
                r"[\w'█_-]+",
                bs4.BeautifulSoup(i.content).text)))
    for i in p.tags:
        Tag.create(pageid=p._pageid, tag=i)


def _process_user(user):
    if user == '(account deleted)' or user.startswith('Anonymous ('):
        return
    logger.info('Processing user: {}'.format(user))
    data = {'name': user}
    data['pages'] = Page.count(Page.author == user)
    data['wordcount'] = Page.sum('wordcount', Page.author == user)
    data['comments'] = ForumPost.count(ForumPost.user == user)
    data['edits'] = Revision.count(Revision.user == user)
    activities = [
        Revision.select(peewee.fn.Min(Revision.time))
        .where(Revision.user == user)
        .scalar(),
        ForumPost.select(peewee.fn.Min(ForumPost.time))
        .where(ForumPost.user == user)
        .scalar()]
    activities = [i for i in activities if i is not None]
    data['first_activity'] = min(activities) if activities else None
    data['rating'] = Page.sum('rating', Page.author == user)
    data['upvoted'] = Vote.count((Vote.user == user) & (Vote.value == 1))
    data['downvoted'] = Vote.count((Vote.user == user) & (Vote.value == -1))
    User.create(**data)


def _dbmap(func, data):
    block_size = 100
    buffer = []
    for i in data:
        buffer.append(i)
        if len(buffer) == block_size:
            with db.transaction():
                for j in buffer:
                    func(j)
            buffer = []
    with db.transaction():
        for i in buffer:
            func(i)


def generate():
    time_start = arrow.now()
    logger.info('Purging tables.')
    for i in (Page, Revision, Vote, ForumPost, Tag, User):
        i.drop_table(fail_silently=True)
        i.create_table()
    with crawler.Page.from_snapshot() as sn:
        _dbmap(_process_page, sn.list_all_pages())
    users = set()
    for i in (Revision, Vote, ForumPost):
        users = users.union(set(i.list('user', distinct=True)))
    _dbmap(_process_user, sorted(users))
    time_taken = (arrow.now() - time_start)
    hours, remainder = divmod(time_taken.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    msg = 'Finished generating statistics. [{:02d}:{:02d}:{:02d}]'
    msg = msg.format(hours, minutes, seconds)
    logger.info(msg)

###############################################################################
# Output Functions
###############################################################################


def print_basic():
    msgs = (
        '~ Pages', '~ Users', 'Authors', 'Voters', 'Editors', '~ Votes',
        'Upvotes', 'Downvotes', '~ Rating', 'Average', 'Mode', 'Deviation',
        '~ Wordcount', 'Average', '~ Comments', '~ Revisions', '~ Images')
    funcs = (
        lambda x: Page.count(Page.pageid << x),
        lambda x: len(set.union(
            set(Page.list('author', Page.pageid << x)),
            *[set(i.list('user', i.pageid << x))
              for i in (Vote, Revision, ForumPost)])),
        lambda x: Page.count(Page.pageid << x, distinct=Page.author),
        lambda x: Vote.count(Vote.pageid << x, distinct=Vote.user),
        lambda x: Revision.count(Revision.pageid << x, distinct=Revision.user),
        lambda x: Vote.count(Vote.pageid << x),
        lambda x: Vote.count((Vote.pageid << x) & (Vote.value == 1)),
        lambda x: Vote.count((Vote.pageid << x) & (Vote.value == -1)),
        lambda x: Page.sum('rating', Page.pageid << x),
        lambda x: Page.mean('rating', Page.pageid << x),
        lambda x: mode(Page.list('rating', Page.pageid << x)),
        lambda x: pstdev(Page.list('rating', Page.pageid << x)),
        lambda x: Page.sum('wordcount', Page.pageid << x),
        lambda x: Page.mean('wordcount', Page.pageid << x),
        lambda x: Page.sum('comments', Page.pageid << x),
        lambda x: Page.sum('revisions', Page.pageid << x),
        lambda x: Page.sum('images', Page.pageid << x))
    pages = Page.list('pageid')
    skips = Tag.list('pageid', Tag.tag == 'scp')
    tales = Tag.list('pageid', Tag.tag == 'tale')
    header = '||~ {} ||~ {} ||~ {} ||~ {} ||'
    header = header.format('Field', 'Total', 'Skips', 'Tales')
    print(header)
    row = '||{} || {:.0f} || {:.0f} || {:.0f} ||'
    for msg, func in zip(msgs, funcs):
        print(row.format(msg, func(pages), func(skips), func(tales)))


def _days_on_the_site(user):
    user = User.get(User.name == user)
    if user.first_activity is None:
        return None
    return (arrow.now() - arrow.get(user.first_activity)).days


def _dict_to_csv(filename, data):
    if not os.path.exists(CSV_OUT_PATH):
        os.mkdir(CSV_OUT_PATH)
    fullname = CSV_OUT_PATH + filename
    with open(fullname, 'w') as F:
        fields = data[0].keys()
        fields = [i.upper() for i in fields]
        writer = csv.DictWriter(F, fieldnames=fields)
        writer.writeheader()
        for row in data:
            formatted_row = {}
            for k, v in row.items():
                formatted_row[k.upper()] = v
            writer.writerow(formatted_row)
    logger.info('Updated statistics data in {}'.format(filename))


def create_table_authors():
    data = []
    for i in Page.list('author', distinct=True):
        try:
            user = User.get(User.name == i)
        except User.DoesNotExist:
            # deleted or anonymous
            continue
        user_dict = collections.OrderedDict()
        user_dict['user'] = i
        user_dict['pages created'] = user.pages
        user_dict['net rating'] = user.rating
        user_dict['average rating'] = round(user.rating / user.pages, 2)
        if _days_on_the_site(i) is not None:
            user_dict['rating per day'] = round(
                user.rating / _days_on_the_site(i),
                4)
        else:
            user_dict['rating per day'] = None
        user_dict['wordcount'] = user.wordcount
        user_dict['average wordcount'] = round(user.wordcount / user.pages, 0)
        user_dict['image count'] = Page.sum('images', Page.author == i)
        data.append(user_dict)
    _dict_to_csv('authors.csv', data)


def create_table_ratings():
    data = []
    contributors = Page.list('author', distinct=True)
    is_newbie = lambda x: x is not None and x < 180
    newbies = [i for i in User.list('name') if is_newbie(_days_on_the_site(i))]
    with open('stafflist.txt') as f:
        staff = [i.strip() for i in f]
    for n, p in enumerate(Page.select()):
        logger.info('Processing page {}/{}'.format(n, Page.count()))
        page_dict = collections.OrderedDict()
        page_dict['url'] = p.url
        page_dict['title'] = p.title
        page_dict['full rating'] = p.rating
        page_dict['contributor rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << contributors))
        page_dict['newbie rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << newbies))
        page_dict['staff rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << staff))
        data.append(page_dict)
    _dict_to_csv('ratings.csv', data)

###############################################################################
# Plotting Functions
###############################################################################


def plot_user_activity(user):
    plot = pygal.Line(
        fill=True,
        style=pygal.style.NeonStyle,
        x_label_rotation=35,
        show_dots=False,
        title='User Activity: {}'.format(user))
    rev_cn = collections.Counter()
    for rev in Revision.select().where(Revision.user == user):
        key = '{}-{:02}'.format(rev.time.year, rev.time.month)
        rev_cn[key] += 1
    post_cn = collections.Counter()
    for post in ForumPost.select().where(ForumPost.user == user):
        key = '{}-{:02}'.format(post.time.year, post.time.month)
        post_cn[key] += 1
    page_cn = collections.Counter()
    for page in Page.select().where(Page.author == user):
        key = '{}-{:02}'.format(page.created.year, page.created.month)
        page_cn[key] += 20
    dates = set.union(*map(set, (rev_cn, post_cn, page_cn)))
    if not dates:
        print('ERROR: {}'.format(user))
        return
    start = arrow.get(min(dates), 'YYYY-MM')
    end = arrow.get(max(dates), 'YYYY-MM')
    x_axis = [
        '{}-{:02}'.format(i.year, i.month)
        for i, _ in arrow.Arrow.span_range('month', start, end)]
    # the data from last month is usually only partial, discard it
    x_axis = x_axis[:-1]
    plot.x_labels = x_axis
    plot.x_labels_major = [i for i in x_axis if i[-2:] == '01']
    plot.width = max(50 * len(x_axis), 800)
    plot.add('Revisions', [rev_cn[i] for i in x_axis])
    plot.add('Comments', [post_cn[i] for i in x_axis])
    plot.add('Pages Authored', [page_cn[i] for i in x_axis])
    if not os.path.exists('plots/activity/'):
        os.mkdir('plots/activity/')
    plot.render_to_png('plots/activity/{}.png'.format(user))

###############################################################################


def main():
    #generate()
    #create_table_ratings()
    #print_basic()
    plot_user_activity('Aelanna')
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
