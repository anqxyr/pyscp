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
import orm

from statistics import mode, pstdev, mean, median

###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.stats')
logger.setLevel(logging.DEBUG)
CSV_OUTPUT_PATH = '/home/anqxyr/heap/_scp/csv_stats/'
PLOT_OUTPUT_PATH = '/home/anqxyr/heap/_scp/plots/'

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
    post_id = peewee.IntegerField(primary_key=True)
    pageid = peewee.IntegerField(index=True, null=True)
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
    for i in p.tags:
        Tag.create(pageid=p._pageid, tag=i)
    for i in p.comments:
        ForumPost.create(
            post_id=i.post_id,
            pageid=p._pageid,
            title=i.title,
            user=i.user,
            time=i.time,
            wordcount=len(re.findall(
                r"[\w'█_-]+",
                bs4.BeautifulSoup(i.content).text)))


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
    data['first activity'] = min(activities) if activities else None
    data['rating'] = Page.sum('rating', Page.author == user)
    data['upvoted'] = Vote.count((Vote.user == user) & (Vote.value == 1))
    data['downvoted'] = Vote.count((Vote.user == user) & (Vote.value == -1))
    User.create(**data)


def _process_post(post):
    if ForumPost.select().where(ForumPost.post_id == post.post_id).exists():
        return
    ForumPost.create(
        post_id=post.post_id,
        pageid=None,
        title=post.title,
        user=post.user,
        time=post.time,
        wordcount=len(re.findall(
            r"[\w'█_-]+",
            bs4.BeautifulSoup(post.content).text)))


def _dbmap(func, data):
    block_size = 500
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
        logger.info('Processing standalone posts')
        _dbmap(_process_post, orm.ForumPost.select())
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
        '~ Pages', '~ Users', 'Authors', 'Voters', 'Editors', 'Commenters',
        '~ Votes', 'Upvotes', 'Downvotes', '~ Rating', 'Average', 'Median',
        'Mode', 'Deviation', '~ Wordcount', 'Average', 'Median', '~ Comments',
        '~ Revisions', '~ Images')
    funcs = (
        lambda x: Page.count(Page.pageid << x),
        lambda x: len(set.union(
            set(Page.list('author', Page.pageid << x)),
            *[set(i.list('user', i.pageid << x))
              for i in (Vote, Revision, ForumPost)])),
        lambda x: Page.count(Page.pageid << x, distinct=Page.author),
        lambda x: Vote.count(Vote.pageid << x, distinct=Vote.user),
        lambda x: Revision.count(Revision.pageid << x, distinct=Revision.user),
        lambda x:
            ForumPost.count(ForumPost.pageid << x, distinct=ForumPost.user),
        lambda x: Vote.count(Vote.pageid << x),
        lambda x: Vote.count((Vote.pageid << x) & (Vote.value == 1)),
        lambda x: Vote.count((Vote.pageid << x) & (Vote.value == -1)),
        lambda x: Page.sum('rating', Page.pageid << x),
        lambda x: Page.mean('rating', Page.pageid << x),
        lambda x: median(Page.list('rating', Page.pageid << x)),
        lambda x: mode(Page.list('rating', Page.pageid << x)),
        lambda x: pstdev(Page.list('rating', Page.pageid << x)),
        lambda x: Page.sum('wordcount', Page.pageid << x),
        lambda x: Page.mean('wordcount', Page.pageid << x),
        lambda x: median(Page.list('wordcount', Page.pageid << x)),
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


def print_longest_posts(number_of_posts):
    cn = collections.Counter()
    for i in ForumPost.select().where(ForumPost.wordcount > 1000):
        cn[i.post_id] = i.wordcount
    with crawler.Page.from_snapshot():
        for post_id, wordcount in cn.most_common(number_of_posts):
            p = ForumPost.get(ForumPost.post_id == post_id)
            op = orm.ForumPost.get(orm.ForumPost.post_id == post_id)
            link = 'http://www.scp-wiki.net/forum/t-{}/#post-{}'
            link = link.format(op.thread_id, post_id)
            print('[{} "{}"], {}, {} words.'.format(
                link, p.title, p.user, p.wordcount))


def _days_on_the_site(user):
    user = User.get(User.name == user)
    if user.first_activity is None:
        return None
    return (arrow.now() - arrow.get(user.first_activity)).days


def _save_to_csv(filename, table):
    if not os.path.exists(CSV_OUTPUT_PATH):
        os.mkdir(CSV_OUTPUT_PATH)
    fullname = CSV_OUTPUT_PATH + filename
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
        if user.rating is not None:
            row['average rating'] = round(user.rating / user.pages, 2)
        else:
            row['average rating'] = None
        if _days_on_the_site(i) is not None and user.rating is not None:
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
        row['first_activity'] = i.first_activity
        row['total votes'] = i.upvoted + i.downvoted
        row['net vote rating'] = i.upvoted - i.downvoted
        row['upvotes'] = i.upvoted
        row['downvotes'] = i.downvoted
        if row['total votes'] != 0:
            row['upvote %'] = round(100 * i.upvoted / row['total votes'], 2)
        else:
            row['upvote %'] = None
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
        if i == '(account deleted)' or i.startswith('Anonymous ('):
            continue
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
        row['user'] = i
        votes = collections.defaultdict(list)
        for v in Vote.select().where(Vote.user == i):
            year = Page.get(Page.pageid == v.pageid).created.year
            votes[year].append(v.value)
        for i in range(2008, 2016):
            if i in votes:
                row['{} total'.format(i)] = len(votes[i])
                row['{} net'.format(i)] = sum(votes[i])
            else:
                row['{} total'.format(i)] = None
                row['{} net'.format(i)] = None
        table.append(row)
    _save_to_csv('yearly_votes.csv', table)


def t_posts():
    table = []
    for i in User.list('name'):
        row = collections.OrderedDict()
        row['user'] = i
        row['total posts'] = ForumPost.count(ForumPost.user == i)
        post_wc_avg = ForumPost.mean('wordcount', ForumPost.user == i)
        if post_wc_avg is not None:
            row['average post wordcount'] = round(post_wc_avg, 2)
        else:
            row['average post wordcount'] = None
        wordcounts = ForumPost.list('wordcount', ForumPost.user == i)
        row['highest post wordcount'] = max(wordcounts) if wordcounts else None
        post_times = ForumPost.list('time', ForumPost.user == i)
        time_deltas = []
        for x, y in zip(post_times[1:], post_times[:-1]):
            time = x - y
            time = time.days * 86400 + time.seconds
            time_deltas.append(time)
        if not time_deltas:
            row['average time between posts'] = None
        else:
            days, remainder = divmod(int(mean(time_deltas)), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            row['average time between posts'] = (
                '{:04d} days, {:02d}:{:02d}:{:02d}'
                .format(days, hours, minutes, seconds))
        table.append(row)
    _save_to_csv('posts.csv', table)


def t_ratings():
    table = []
    contributors = Page.list('author', distinct=True)
    is_newbie = lambda x: x is not None and x < 180
    newbies = [i for i in User.list('name') if is_newbie(_days_on_the_site(i))]
    with open('stafflist.txt') as f:
        staff = [i.strip() for i in f]
    for n, p in enumerate(Page.select()):
        #logger.info('Processing page {}/{}'.format(n, Page.count()))
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


def make_tables():
    tables = (
        t_authors, t_users, t_tags_author, t_tags_user, t_yearly_votes,
        t_posts, t_ratings)
    for n, i in enumerate(tables):
        logger.info('Generating table {}/{}'.format(n, len(tables)))
        i()
    logger.info('Finished.')


###############################################################################
# Plotting Functions
###############################################################################

def create_plot(title, x_axis, labels, lines, **kwargs):
    if kwargs.get('plot_type', False):
        plot_type = kwargs['plot_type']
    else:
        plot_type = pygal.Line
    plot = plot_type(
        fill=True,
        style=pygal.style.NeonStyle,
        show_dots=False,
        truncate_legend=25,
        truncate_label=25,
        width=1800,
        include_x_axis=True,
        title=title,
        x_labels=x_axis)
    plot.x_label_rotation = 35
    if kwargs.get('timeline', False):
        plot.x_labels_major = [i for i in x_axis if i[-2:] == '01']
        plot.show_minor_x_labels = False
        plot.x_label_rotation = 35
    if kwargs.get('x_labels_major', False):
        plot.x_labels_major = kwargs['x_labels_major']
        plot.show_minor_x_labels = False
    if kwargs.get('range', False):
        plot.range = kwargs['range']
    for label, line in zip(labels, lines):
        plot.add(label, line)
    plot.render_to_png('{}{}.png'.format(
        PLOT_OUTPUT_PATH,
        title.lower().replace(' ', '_').replace(':', '')))
    logger.info('Plot created: {}'.format(title))


def plot_user_activity(user):
    data = collections.defaultdict(collections.Counter)
    key = lambda x: '{}-{:02}'.format(x.year, x.month)
    for i in Revision.list('time', Revision.user == user):
        data['Revisions'][key(i)] += 1
    for i in ForumPost.list('time', ForumPost.user == user):
        data['Forum Posts'][key(i)] += 1
    for i in Page.list('created', Page.author == user):
        data['Pages (x10)'][key(i)] += 10
    dates = set.union(*map(set, data.values()))
    if not dates:
        logger.warning('User activity is empty: {}'.format(user))
        return
    start = arrow.get(min(dates), 'YYYY-MM')
    end = arrow.get(max(dates), 'YYYY-MM')
    x_axis = [key(i) for i, _ in arrow.Arrow.span_range('month', start, end)]
    labels = ('Forum Posts', 'Revisions', 'Pages (x10)')
    for i in labels:
        for j in x_axis:
            if j not in data[i]:
                data[i][j] = 0
    create_plot('User Activity: {}'.format(user), x_axis, labels,
                [data[i] for i in labels], timeline=len(x_axis) > 24)


def _user_contributor_since(user):
    pages = Page.list('created', Page.author == user)
    if pages:
        return min(pages)


def _user_newbie_until(user):
    first_activity = User.get(User.name == user).first_activity
    if first_activity is not None:
        return arrow.get(first_activity).replace(months=+6).naive


def _user_only_forums_until(user):
    revisions = Revision.list('time', Revision.user == user)
    first = min(revisions) if revisions else None
    for i in ForumPost.select().where(ForumPost.user == user):
        if i.pageid is not None and (first is None or i.time < first):
            first = i.time
    return first


def plot_active_users():
    data = collections.defaultdict(lambda: collections.defaultdict(set))
    key = lambda x: '{}-{:02}'.format(x.year, x.month)
    for user in User.list('name'):
        contrib = _user_contributor_since(user)
        newbie = _user_newbie_until(user)
        forums = _user_only_forums_until(user)
        for i in (Revision.list('time', Revision.user == user) +
                  ForumPost.list('time', ForumPost.user == user)):
            data['All Members'][key(i)].add(user)
            if contrib is not None and i > contrib:
                data['Contributors'][key(i)].add(user)
            if i < newbie:
                data['Newbies'][key(i)].add(user)
            if forums is None or i < forums:
                data['Forums Only'][key(i)].add(user)
    x_axis = sorted(data['All Members'])
    labels = ('All Members', 'Newbies', 'Contributors', 'Forums Only')
    for i in labels:
        for j in x_axis:
            data[i][j] = len(data[i][j])
    create_plot('Active Users', x_axis, labels,
                [data[i] for i in labels], timeline=True)


def plot_posts_per_capita():
    posts = collections.defaultdict(collections.Counter)
    users = collections.defaultdict(lambda: collections.defaultdict(set))
    key = lambda x: '{}-{:02}'.format(x.year, x.month)
    for user in User.list('name'):
        contrib = _user_contributor_since(user)
        newbie = _user_newbie_until(user)
        for i in ForumPost.list('time', ForumPost.user == user):
            posts['All Members'][key(i)] += 1
            users['All Members'][key(i)].add(user)
            if contrib is not None and i > contrib:
                posts['Contributors'][key(i)] += 1
                users['Contributors'][key(i)].add(user)
            if newbie is not None and i < newbie:
                posts['Newbies'][key(i)] += 1
                users['Newbies'][key(i)].add(user)
    x_axis = sorted(posts['All Members'])
    labels = ('Contributors', 'All Members', 'Newbies')
    create_plot(
        'Posts Per Capita', x_axis, labels,
        [[(posts[i][j] / len(users[i][j])) for j in x_axis] for i in labels],
        timeline=True)


def plot_site_activity(timerange='total'):
    timerange_values = ('total', 'yearly', 'monthly', 'weekly', 'daily')
    keys = (
        lambda x: '{}-{:02}'.format(x.year, x.month),
        lambda x: arrow.get(x).format('MMMM'),
        lambda x: arrow.get(x).format('DD'),
        lambda x: arrow.get(x).format('dddd'),
        lambda x: '{:02}'.format(x.hour))
    for value, func in zip(timerange_values, keys):
        if timerange == value:
            key = func
            break
    data = collections.defaultdict(collections.Counter)
    for i in Revision.list('time'):
        data['Revisions'][key(i)] += 1
    for i in ForumPost.list('time'):
        data['Forum Posts'][key(i)] += 1
    for i in Page.list('created'):
        data['Pages (x10)'][key(i)] += 10
    x_axis = sorted(data['Revisions'])
    if timerange == 'yearly':
        x_axis = [arrow.get(str(i), 'M').format('MMMM') for i in range(1, 13)]
    if timerange == 'weekly':
        x_axis = [
            arrow.locales.get_locale('en').day_name(i) for i in range(1, 8)]
    labels = ('Forum Posts', 'Revisions', 'Pages (x10)')
    create_plot('Site Activity: {}'.format(timerange.title()), x_axis,
                labels, [data[i] for i in labels],
                timeline=(timerange == 'total'))


def plot_users_still_active(relative=False):
    data = collections.defaultdict(lambda: collections.defaultdict(set))
    for user in User.select(User.name, User.first_activity):
        if user.first_activity is None:
            continue
        key = '{}-{:02}'.format(
            user.first_activity.year, user.first_activity.month)
        data['Control'][key].add(user.name)
        posts = ForumPost.list('time', ForumPost.user == user.name)
        edits = Revision.list('time', Revision.user == user.name)
        last_post = max(posts) if posts else None
        last_edit = max(edits) if edits else None
        last_activity = [i for i in (last_post, last_edit) if i is not None]
        if last_activity:
            last_activity = max(last_activity)
        else:
            continue
        days = (31, 90, 180, 365)
        labels = ('Last Month', 'Three Months', 'Six Months', 'A Year')
        for i, j in zip(days, labels):
            if (arrow.now().naive - last_activity).days <= i:
                data[j][key].add(user.name)
    x_axis = sorted(data['Control'])
    for i in labels:
        for j in x_axis:
            if not relative:
                data[i][j] = len(data[i][j])
            else:
                data[i][j] = len(data[i][j]) / len(data['Control'][j])
    title = 'Users Still Active'
    if relative:
        title += ' (Relative)'
    labels = list(reversed(labels))
    create_plot(title, x_axis, labels, [data[i] for i in labels],
                timeline=True)


def plot_post_distribution(over_time=False):
    data = collections.defaultdict(collections.Counter)
    skips = Tag.list('pageid', Tag.tag == 'scp')
    tales = Tag.list('pageid', Tag.tag == 'tale')
    for u in User.select(User.name, User.first_activity):
        if over_time:
            key = lambda x: '{}-{:02}'.format(x.year, x.month)
        else:
            key = lambda x: str((x - u.first_activity).days // 30 * 30)
        for i in (
                ForumPost.select(ForumPost.time, ForumPost.pageid)
                .where(ForumPost.user == u.name)):
            data['Total'][key(i.time)] += 1
            if i.pageid is None:
                data['Forums'][key(i.time)] += 1
            elif i.pageid in skips:
                data['Skips'][key(i.time)] += 1
            elif i.pageid in tales:
                data['Tales'][key(i.time)] += 1
            else:
                data['Other'][key(i.time)] += 1
    plot_config = {'plot_type': pygal.StackedLine}
    labels = ('Skips', 'Tales', 'Forums', 'Other')
    if over_time:
        x_axis = sorted(data['Total'])
        title = 'Post Distribution Over Time'
        plot_config['timeline'] = True
    else:
        x_axis = list(map(str, sorted(map(int, data['Total']))))
        title = 'Post Distribution Per Account Age'
        plot_config['x_labels_major'] = x_axis[::12]
    for i in labels:
        for j in x_axis:
            data[i][j] = data[i][j] / data['Total'][j]
    create_plot(title, x_axis, labels,
                [data[i] for i in labels],
                **plot_config)


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
    output_path = PLOT_OUTPUT_PATH + 'active_ratio.png'
    plot.render_to_png(output_path)

###############################################################################


def main():
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
