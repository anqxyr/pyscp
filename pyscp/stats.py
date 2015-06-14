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


def make_counter(key, pages, func):
    """Generic counter factory."""
    subgroups = collections.defaultdict(list)
    for p in pages:
        key_value = key(p)
        if key_value:
            subgroups[key_value].append(p)
    return collections.Counter({k: func(v) for k, v in subgroups.items()})


def counter_authors(pages, func):
    """Author counter."""
    return make_counter(lambda p: p.author, pages, func)

###############################################################################
# Filters
#
# These functions take a list of pages and return a list filtered based on
# some criteria. Some of these are basically shortcuts for list comprehensions,
# while others are more complicated.
###############################################################################


def filter_tag(pages, tag):
    """Pages with a given tag."""
    return [p for p in pages if tag in p.tags]


def filter_min_authored(pages, min_val=3):
    """Pages by authors who have at least min_val pages."""
    authors = counter_authors(pages, len)
    return [p for p in pages if authors[p.author] >= min_val]

###############################################################################
# Records
#
# Pretty-printing numbers for the 'SCP WORLD RECORDS' thread.
###############################################################################


def records(pages):
    pages = [p for p in pages if p.author != 'Unknown Author']
    pages = [p for p in pages if '_sys' not in p.tags]
    skips, tales, jokes, essays = [
        filter_tag(pages, tag) for tag in ('scp', 'tale', 'joke', 'essay')]
    messages = (
        'Users with Most Upvotes (General):',
        'Users with Most Upvotes (SCPs):',
        'Users with Most Upvotes (Tales):',
        'Most SCPs Written:',
        'Most Tales Written:',
        'Highest SCP Average (>=3):',
        'Highest Tale Average (>=3):',
        'Most -J Articles Written:',
        'Highest Joke Average (>=3):',
        'Most Essay Articles Written:',
        'Highest Essay Average (>=3):',)
    counters = (
        counter_authors(pages, upvotes),
        counter_authors(skips, upvotes),
        counter_authors(tales, upvotes),
        counter_authors(skips, len),
        counter_authors(tales, len),
        counter_authors(filter_min_authored(skips), average),
        counter_authors(filter_min_authored(tales), average),
        counter_authors(jokes, len),
        counter_authors(filter_min_authored(jokes), average),
        counter_authors(essays, len),
        counter_authors(filter_min_authored(essays), average),)
    for message, counter in zip(messages, counters):
        print(message)
        for k, v in counter.most_common(5):
            print(k.ljust(40), round(v, 2))


###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-13.db')
    pages = list(map(sn, sn.list_pages()))
    records(pages)
