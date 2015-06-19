#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import collections
import logging
import pyscp
import re

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Scalars
#
# These functions receive a list of pages and return a single value.
# They're the smallest blocks on which the rest of the stats module is build.
###############################################################################

# builtin len is a scalar too


def upvotes(pages):
    """Upvotes."""
    return sum([v.value for v in p.votes].count(1) for p in pages)


def rating(pages):
    """Net rating."""
    return sum(p.rating for p in pages)


def average(pages):
    """Average rating."""
    return rating(pages) / len(pages)


def divided(pages):
    """Controversy score."""
    return sum(len(p.votes) / p.rating for p in pages)


def redactions(pages):
    """Redaction score."""
    return sum(
        p.text.count('█') +
        20 * sum(map(p.text.count, ('REDACTED', 'EXPUNGED')))
        for p in pages)

###############################################################################
# Counters
#
# These function receive a list of pages and a scalar function. They then
# split the pages based on some criteria, and apply the scalar to each
# subgroup. The results are returned as a collections.Counter object.
###############################################################################


def make_counter(pages, func, key):
    """Generic counter factory."""
    subgroups = collections.defaultdict(list)
    for p in pages:
        key_value = key(p)
        if key_value:
            subgroups[key_value].append(p)
    return collections.Counter({k: func(v) for k, v in subgroups.items()})


def counter_author(pages, func):
    """Group per page author."""
    return make_counter(pages, func, lambda p: p.author)


def counter_month(pages, func):
    """Group per month the page was posted on."""
    return make_counter(pages, func, lambda p: p.created[:7])


def counter_page(pages, func):
    """Each page into its own group."""
    return make_counter(pages, func, lambda p: p.url)


def counter_block(pages, func):
    """Group skips based on which 100-block they're in."""
    def key(page):
        if 'scp' not in page.tags:
            return
        match = re.search(r'[0-9]{3,4}$', page.url)
        if not match:
            return
        match = int(match.group())
        if match == 1:
            return
        return str((match // 100) * 100).zfill(3)
    return make_counter(pages, func, key)


def chain_counters(pages, func, *counters):
    """Apply counters one after another."""
    if len(counters) == 1:
        return counters[0](pages, func)
    results = collections.Counter()
    for key, val in counters[0](pages, lambda x: x).items():
        for ikey, ival in chain_counters(val, func, *counters[1:]).items():
            results['%s, %s' % (key, ikey)] = ival
    return results

###############################################################################
# Filters
#
# These functions take a list of pages and return a list filtered based on
# some criteria. Some of these are basically shortcuts for list comprehensions,
# while others are more complicated.
###############################################################################


def filter_tag(pages, tag):
    """Pages with a given tag."""
    if not tag:
        return pages
    return [p for p in pages if tag in p.tags]


# TODO: needs more indicative name.
def filter_authored(pages, min_val=3):
    """Pages by authors who have at least min_val pages."""
    authors = counter_author(pages, len)
    return [p for p in pages if authors[p.author] >= min_val]


def filter_not_migrated(pages):
    """Exclude pages that were moved from editthis wiki."""
    # this particular approach to it is rather crude
    return [p for p in pages if p.created[:7] != '2008-07']


def filter_rating(pages, min_val=20):
    """Pages with rating above min_val."""
    return [p for p in pages if p.rating > min_val]

###############################################################################
# Records
#
# Pretty-printing numbers for the 'SCP WORLD RECORDS' thread.
###############################################################################


def records(pages):
    pages = [p for p in pages if p.author != 'Unknown Author']
    pages = [p for p in pages if '_sys' not in p.tags]
    rec = collections.namedtuple('Record', 'template counter filter args tags')
    records = (
        rec(template='Users with Most Upvotes ({}s):',
            counter=counter_author,
            filter=None,
            args=upvotes,
            tags=('_all', 'scp', 'tale')),
        rec(template='Most {}s Written:',
            counter=counter_author,
            filter=None,
            args=len,
            tags=('scp', 'tale', 'joke', 'essay')),
        rec(template='Highest {} Average (>=3):',
            counter=counter_author,
            filter=filter_authored,
            args=average,
            tags=('scp', 'tale', 'joke', 'essay')),
        rec(template='Most Successful {}s posted in one Month:',
            counter=chain_counters,
            filter=filter_not_migrated,
            args=(len, counter_author, counter_month),
            tags=('_all', 'scp')),
        rec(template='Most Divided {} Vote (>+20):',
            counter=counter_page,
            filter=filter_rating,
            args=divided,
            tags='scp'),
        rec(template='Highest Redaction Score ({}s):',
            counter=counter_page,
            filter=None,
            args=redactions,
            tags=('scp', 'tale')),
        rec(template='Highest {} Block Average:',
            counter=counter_block,
            filter=None,
            args=average,
            tags='scp'))
    maybe_tuple = lambda x: x if isinstance(x, tuple) else (x,)
    for record, tag in [(r, t) for r in records for t in maybe_tuple(r.tags)]:
        fpages = pages if tag == '_all' else filter_tag(pages, tag)
        if record.filter:
            fpages = record.filter(fpages)
        insert = {'_all': 'Article', 'scp': 'SCP'}.get(tag, tag.capitalize())
        print(record.template.format(insert))
        args = maybe_tuple(record.args)
        for k, v in record.counter(fpages, *args).most_common(5):
            print(k.ljust(40 if len(k) < 40 else 80), round(v, 2))


###############################################################################
# Stats Wiki
#
# Collecting numbers for the stats wiki and posting them there.
###############################################################################


def ranking_source(counter):
    source = '||~ Rank||~ User||~ Score||\n'
    items = counter.items()
    items = sorted(items, key=lambda x: x[0].lower())
    items = sorted(items, key=lambda x: x[1], reverse=True)
    for idx, item in enumerate(items):
        source += '||{0}||[[[user:{1[0]}]]]||{1[1]}||\n'.format(idx + 1, item)
    return source


def update_users(pages, stwiki):
    """Update the stats wiki with the author stats."""
    #stwiki('ranking:pages-created').edit(
    #    ranking_source(counter_author(pages, len)))
    users = {p.author for p in pages}
    for user in pyscp.utils.pbar(users, 'POSTING STATS'):
        try:
            post_user(user, pages, stwiki)
        except KeyError as e:
            print(repr(e))
            print('oops:', user)


def post_page(stwiki, name, source, existing=[]):
    if not existing:
        existing.extend(stwiki.list_pages())
    p = stwiki(name)
    if p.url not in existing:
        res = p.create(source, name.split(':')[-1], force=True)
    else:
        res = p.edit(source, force=True)
    if res['status'] != 'ok':
        post_page(stwiki, name, source)


def post_user(user, pages, stwiki):
    authored = [p for p in pages if p.author == user]
    source = """
        ++ Authorship Statistics
        {{{{[[[ranking:Pages Created]]]:@@          @@**{}**}}}}
        {{{{Net Rating:@@             @@**{}**}}}}
        {{{{Average Rating:@@         @@**{}**}}}}
        {{{{Wordcount:@@              @@**{}**}}}}
        {{{{Average Wordcount:@@      @@**{}**}}}}
        """
    # remove extra indent
    source = '\n'.join(i.strip() for i in source.split('\n')).strip()
    pcount = len(authored)
    rating = sum(p.rating for p in authored)
    wcount = sum(p.wordcount for p in authored)
    source = source.format(
        pcount,
        rating,
        round(rating / pcount, 2),
        wcount,
        round(wcount / pcount, 2))
    post_page(stwiki, 'user:' + user, source)


###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-13.db')
    pages = list(map(sn, sn.list_pages()))
    stwiki = pyscp.core.WikidotConnector('scp-stats')
    stwiki.auth(
        'anqxyr',
        """3/?E:lqXJ.?L1Ga6W1"e.Cm5r+Nb%O6rxFXweR59=BT~!W'HEz?zYa]'.wp8rvtI""")
    update_users(pages, stwiki)
