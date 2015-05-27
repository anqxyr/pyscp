#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import collections
import logging
import progress.bar
import pyscp


###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Accumulators
###############################################################################


def scan_pages(dbpath, *funcs):
    sn = pyscp.core.SnapshotConnector('www.scp-wiki.net', dbpath)
    pages = list(map(sn, sn.list_pages()))
    results = [func(pages[0]) for func in funcs]
    bar = progress.bar.IncrementalBar(
        'SCANNING PAGES', suffix='%(percent)d%% (%(elapsed_td)s)')
    for page in bar.iter(pages[1:]):
        results = [func(page, acc) for func, acc in zip(funcs, results)]
    return dict(zip([f.__name__ for f in funcs], results))


def pages(page, acc=0):
    return acc + 1


def upvotes(page, acc=0):
    return acc + sum(1 for i in page.votes if i.value == 1)


def rating(page, acc=0):
    return acc + page.rating

###############################################################################
# Aggregators
###############################################################################


def group_by(name, keygen, funcs):

    def grouped(page, acc=None):
        if acc is None:
            acc = collections.defaultdict(dict)
        key = keygen(page)
        if not key:
            return acc
        if isinstance(key, str) or not hasattr(key, '__iter__'):
            keys = [key]
        else:
            keys = key
        for key in keys:
            if key not in acc:
                acc[key] = {f.__name__: f(page) for f in funcs}
            else:
                acc[key] = {
                    f.__name__: f(page, acc[key][f.__name__]) for f in funcs}
        return acc

    grouped.__name__ = name
    return grouped


def group_by_tag(*funcs, tags=None):
    if not tags:
        keygen = lambda x: x.tags
    else:
        keygen = lambda x: x.tags & set(tags)
    return group_by('tags', keygen, funcs)


def group_by_user(*funcs):
    return group_by('users', lambda x: x.author, funcs)

###############################################################################
# Second-Level Statistics
###############################################################################


def top_users(data, key, count=5, tag=None):
    if tag is None:
        counter = {k: v[key] for k, v in data['users'].items()}
    else:
        counter = {
            k: v['tags'][tag][key] for k, v in data['users'].items()
            if tag in v['tags']}
    return collections.Counter(counter).most_common(count)

###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    tags = group_by_tags(pages, upvotes, tags=('scp', 'tale'))
    data = scan_pages(
        '/home/anqxyr/heap/_scp/scp-wiki.2015-05-16.db',
        group_by_user(pages, upvotes, tags),
        tags)
    for key in 'pages', 'upvotes':
        print(key.upper())
        print('####################')
        for tag in (None, 'scp', 'tale'):
            print(tag, ':', sep='')
            for user, value in top_users(data, key, tag=tag):
                print(user.ljust(30), value)
            print('--------------------')
