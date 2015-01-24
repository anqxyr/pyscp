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


def _save_to_csv(filename, table):
    if not os.path.exists(CSV_OUT_PATH):
        os.mkdir(CSV_OUT_PATH)
    fullname = CSV_OUT_PATH + filename
    with open(fullname, 'w') as F:
        fields = table[0].keys()
        fields = [i.upper() for i in fields]
        writer = csv.DictWriter(F, fieldnames=fields)
        writer.writeheader()
        for row in table:
            formatted_row = {}
            for k, v in row.items():
                formatted_row[k.upper()] = v
            writer.writerow(formatted_row)
    logger.info('Updated statistics data in {}'.format(filename))


def t_authors():
    table = []
    for i in Page.list('author', distinct=True):
        try:
            user = User.get(User.name == i)
        except User.DoesNotExist:
            # deleted or anonymous
            continue
        row = collections.OrderedDict()
        row['user'] = i
        row['pages created'] = user.pages
        row['net rating'] = user.rating
        row['average rating'] = round(user.rating / user.pages, 2)
        if _days_on_the_site(i) is not None:
            row['rating per day'] = round(
                user.rating / _days_on_the_site(i),
                4)
        else:
            row['rating per day'] = None
        row['wordcount'] = user.wordcount
        row['average wordcount'] = round(user.wordcount / user.pages, 0)
        row['image count'] = Page.sum('images', Page.author == i)
        table.append(row)
    _save_to_csv('authors.csv', table)


def t_users():
    table = []
    for i in User.select():
        row = collections.OrderedDict()
        row['user'] = i.name
        row['revisions'] = i.edits
        row['total votes'] = i.upvoted + i.downvoted
        row['net vote rating'] = i.upvoted - i.downvoted
        row['upvotes'] = i.upvoted
        row['downvotes'] = i.downvoted
        row['upvote %'] = round(100 * i.upvoted / row['total votes'], 2)
        table.append(row)
    _save_to_csv('users.csv', table)


def t_tags_user():
    table = []
    for i in User.select():
        row = collections.OrderedDict()
        row['user'] = i.name
        cn = collections.Counter()
        for v in Vote.select().where(Vote.user == i.name):
            for t in Tag.list('tag', Tag.pageid == v.pageid):
                cn[t] += v.value
        for n, (k, v) in enumerate(cn.most_common(10)):
            row_key = 'favorite tag #{}'.format(n + 1)
            row[row_key] = '{} ({})'.format(k, v)
        for n, (k, v) in enumerate(cn.most_common()[:-6:-1]):
            row_key = 'unfavorite tag #{}'.format(n + 1)
            row[row_key] = '{} ({})'.format(k, v)
        table.append(row)
    _save_to_csv('tags_user.csv', table)


def t_tags_author():
    table = []
    for i in Page.list('author', distinct=True):
        row = collections.OrderedDict()
        row['user'] = i
        cn = collections.Counter()
        pageids = Page.list('pageid', Page.author == i)
        for t in Tag.list('tag', Tag.pageid << pageids):
            cn[t] += 1
        for n, (k, v) in enumerate(cn.most_common(10)):
            row_key = 'most used tag #{}'.format(n + 1)
            row[row_key] = '{} ({})'.format(k, v)
        table.append(row)
    _save_to_csv('tags_author.csv', table)


def t_yearly_votes():
    table = []
    for i in User.list('name'):
        row = collections.OrderedDict()
        row['user'] == i
        votes = collections.defaultdict(list)
        for v in Vote.select().where(Vote.user == i):
            year = Page.get(Page.pageid == v.pageid).created.year
            votes[year].append(v.value)
        for k, v in votes.items():
            row['{} total'.format(k)] = len(v)
            row['{} net'.format(k)] = sum(v)
        table.append(row)
    _save_to_csv('yearly_votes.csv', table)


def t_ratings():
    table = []
    contributors = Page.list('author', distinct=True)
    is_newbie = lambda x: x is not None and x < 180
    newbies = [i for i in User.list('name') if is_newbie(_days_on_the_site(i))]
    with open('stafflist.txt') as f:
        staff = [i.strip() for i in f]
    for n, p in enumerate(Page.select()):
        logger.info('Processing page {}/{}'.format(n, Page.count()))
        row = collections.OrderedDict()
        row['url'] = p.url
        row['title'] = p.title
        row['full rating'] = p.rating
        row['contributor rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << contributors))
        row['newbie rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << newbies))
        row['staff rating'] = Vote.sum(
            'value',
            (Vote.pageid == p.pageid) &
            (Vote.user << staff))
        table.append(row)
    _save_to_csv('ratings.csv', table)

###############################################################################
# Plotting Functions
###############################################################################


def plot_user_activity(user):
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
    plot = pygal.Line(
        fill=True,
        style=pygal.style.NeonStyle,
        x_label_rotation=35,
        show_dots=False,
        title='User Activity: {}'.format(user))
    plot.x_labels = x_axis
    plot.x_labels_major = [i for i in x_axis if i[-2:] == '01']
    plot.width = max(50 * len(x_axis), 800)
    plot.add('Revisions', [rev_cn[i] for i in x_axis])
    plot.add('Comments', [post_cn[i] for i in x_axis])
    plot.add('Pages Authored', [page_cn[i] for i in x_axis])
    if not os.path.exists('plots/activity/'):
        os.mkdir('plots/activity/')
    plot.render_to_png('plots/activity/{}.png'.format(user))


def plot_active_users():
    data = collections.defaultdict(lambda: collections.defaultdict(set))
    count = User.count()
    for n, u in enumerate(User.select(User.name, User.first_activity)):
        logger.info('Processing user {}/{}'.format(n + 1, count))
        time_new = u.first_activity
        if time_new is not None:
            time_new = arrow.get(time_new).replace(months=+6).naive
        authored = Page.list('created', Page.author == u.name)
        time_contrib = min(authored) if authored else None
        for i in (Revision.list('time', Revision.user == u.name) +
                  ForumPost.list('time', ForumPost.user == u.name)):
            key = '{}-{:02}'.format(i.year, i.month)
            data['All Members'][key].add(u.name)
            if time_contrib is not None and i > time_contrib:
                data['Contributors'][key].add(u.name)
            if time_new is not None and i < time_new:
                data['Newbies'][key].add(u.name)
    for k, v in data.items():
        data[k] = {i: len(j) for i, j in v.items()}
    x_axis = sorted(data['All Members'])[:-1]
    plot = pygal.Line(
        fill=True,
        style=pygal.style.NeonStyle,
        x_label_rotation=35,
        show_dots=False,
        title='Active Site Members')
    plot.x_labels = x_axis
    plot.x_labels_major = [i for i in x_axis if i[-2:] == '01']
    plot.width = 50 * len(x_axis)
    for i in ('All Members', 'Newbies', 'Contributors'):
        plot.add(i, [data[i][j] for j in x_axis])
    plot.render_to_png('plots/active_users.png')


def plot_active_ratio():
    data = collections.defaultdict(
        lambda: collections.defaultdict(
            collections.Counter))
    count = User.count()
    for n, u in enumerate(User.select(User.name, User.first_activity)):
        if (n + 1) % 50 == 0:
            logger.info('Processing user {}/{}'.format(n + 1, count))
        first_activity = u.first_activity
        if first_activity is None:
            continue
        key = '{}-{:02}'.format(first_activity.year, first_activity.month)
        last_activity = first_activity
        for i in (Revision.list('time', Revision.user == u.name) +
                  ForumPost.list('time', ForumPost.user == u.name)):
            if i > last_activity:
                last_activity = i
        for i in (30, 180, 365):
            data[i][key]['total'] += 1
            if (last_activity - first_activity).days > i:
                data[i][key]['active'] += 1
    x_axis = sorted(data[30])[:-1]
    plot = pygal.Line(
        fill=True,
        style=pygal.style.NeonStyle,
        x_label_rotation=35,
        show_dots=False,
        title='Active Members Ratio')
    plot.x_labels = x_axis
    plot.x_labels_major = [i for i in x_axis if i[-2:] == '01']
    plot.width = 50 * len(x_axis)
    plot.range = (0, 1)
    plot.add(
        'After 30 Days',
        [data[30][i]['active'] / data[30][i]['total'] for i in x_axis])
    plot.add(
        'After 6 Months',
        [data[180][i]['active'] / data[180][i]['total'] for i in x_axis])
    plot.add(
        'After 1 Year',
        [data[365][i]['active'] / data[365][i]['total'] for i in x_axis])
    plot.render_to_png('plots/active_ratio.png')

###############################################################################


def main():
    #generate()
    t_yearly_votes()
    #print_basic()
    #plot_active_ratio()
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
