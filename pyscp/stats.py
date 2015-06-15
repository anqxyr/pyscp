#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import collections
import csv
import json
import logging
import pyscp
import re
import itertools
import functools

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


def cr_author(pages, func):
    """Group per page author."""
    return make_counter(pages, func, lambda p: p.author)


def cr_month(pages, func):
    """Group per month the page was posted on."""
    return make_counter(pages, func, lambda p: p.created[:7])


def cr_page(pages, func):
    """Each page into its own group."""
    return make_counter(pages, func, lambda p: p.url)


def cr_block(pages, func):
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


def chain_crs(pages, func, *counters):
    """Apply counters one after another."""
    if len(counters) == 1:
        return counters[0](pages, func)
    results = collections.Counter()
    for key, val in counters[0](pages, lambda x: x).items():
        for ikey, ival in chain_crs(val, func, *counters[1:]).items():
            results['%s, %s' % (key, ikey)] = ival
    return results

###############################################################################
# Filters
#
# These functions take a list of pages and return a list filtered based on
# some criteria. Some of these are basically shortcuts for list comprehensions,
# while others are more complicated.
###############################################################################


def fl_tag(pages, tag):
    """Pages with a given tag."""
    if tag is None:
        return pages
    return [p for p in pages if tag in p.tags]


# TODO: needs more indicative name.
def fl_authored(pages, min_val=3):
    """Pages by authors who have at least min_val pages."""
    authors = cr_author(pages, len)
    return [p for p in pages if authors[p.author] >= min_val]


def fl_not_migrated(pages):
    """Exclude pages that were moved from editthis wiki."""
    # this particular approach to it is rather crude
    return [p for p in pages if p.created[:7] != '2008-07']


def fl_rating(pages, min_val=20):
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
    templates = (
        'Users with Most Upvotes ({}s):',
        'Most {}s Written:',
        'Highest {} Average (>=3):',
        'Most Successful {}s posted in 1 Month:',
        'Most Divided {} Vote (>+20):',
        'Highest Redaction Score ({}s):',
        'Highest {} Block Average:')
    template_funcs = (  # (counter, filter, *args_for_counter)
        (cr_author, None, upvotes),
        (cr_author, None, len),
        (cr_author, fl_authored, average),
        (chain_crs, fl_not_migrated, len, cr_author, cr_month),
        (cr_page, fl_rating, divided),
        (cr_page, None, redactions),
        (cr_block, None, average))
    template_tags = (  # which tags to apply to each template
        (None, 'scp', 'tale'),
        ('scp', 'tale', 'joke', 'essay'),
        ('scp', 'tale', 'joke', 'essay'),
        (None, 'scp'),
        ('scp', ),
        ('scp', 'tale'),
        ('scp', ))
    for template, funcs, tags in zip(templates, template_funcs, template_tags):
        for tag in tags:
            subgr = fl_tag(pages, tag)
            subgr = subgr if funcs[1] is None else funcs[1](subgr)
            name = 'Article' if tag is None else (
                'SCP' if tag == 'scp' else tag.capitalize())
            print(template.format(name))
            for k, v in funcs[0](subgr, *funcs[2:]).most_common(5):
                print(k.ljust(40 if len(k) < 40 else 80), round(v, 2))


###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-13.db')
    pages = list(map(sn, sn.list_pages()))
    records(pages)
