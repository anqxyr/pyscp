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

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Per-Author Counters
###############################################################################


def a_upvotes(pages):
    counter = collections.Counter()
    for p in pages:
        counter[p.author] += [v.value for v in p.votes].count(1)
    return counter


def a_rating(pages):
    counter = collections.Counter()
    for p in pages:
        counter[p.author] += p.rating
    return counter


def a_pages(pages):
    counter = collections.Counter()
    for p in pages:
        counter[p.author] += 1
    return counter


def a_average(pages):
    r = a_rating(pages)
    c = a_pages(pages)
    return collections.Counter({k: r[k] / c[k] for k in c})

###############################################################################
# Records
###############################################################################


def print_record(pages, func, tag=None):
    print('{} ({}):'.format(func.__name__, tag))
    group = pages if not tag else [p for p in pages if tag in p.tags]
    for k, v in func(group).most_common(5):
        print(k.ljust(40), v)


def records(pages):
    pages = [p for p in pages if p.author != 'Unknown Author']
    print_record(pages, a_upvotes)
    print_record(pages, a_upvotes, 'scp')
    print_record(pages, a_upvotes, 'tale')
    print_record(pages, a_pages, 'scp')
    print_record(pages, a_pages, 'tale')
    print_record(pages, a_average, 'scp')
    print_record(pages, a_average, 'tale')


###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-13.db')
    pages = list(map(sn, sn.list_pages()))
    records(pages)
