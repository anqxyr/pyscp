#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import collections
import logging
import pyscp
import csv
import json

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################
# Accumulators
###############################################################################


def scan_pages(sn, *funcs):
    pages = list(map(sn, sn.list_urls()))
    results = [func(pages[0]) for func in funcs]
    for page in pyscp.utils.pbar(pages[1:], "SCANNING PAGES"):
        results = [func(page, acc) for func, acc in zip(funcs, results)]
    return dict(zip([f.__name__ for f in funcs], results))


def count(page, acc=0):
    return acc + 1


def upvotes(page, acc=0):
    return acc + sum(1 for i in page.votes if i.value == 1)


def rating(page, acc=0):
    return acc + page.rating


def wordcount(page, acc=0):
    return acc + page.wordcount


def redactions(page, acc=0):
    score = page.text.count('█')
    score += 20 * page.text.count('REDACTED')
    score += 20 * page.text.count('EXPUNGED')
    return acc + score


def divided(page, acc=0):
    return acc + len(page.votes) / page.rating


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


def group_by_tags(*funcs, tags=None):
    if not tags:
        keygen = lambda x: x.tags
    else:
        keygen = lambda x: x.tags & set(tags)
    return group_by('tags', keygen, funcs)


def group_by_authors(*funcs):
    return group_by('authors', lambda x: x.author, funcs)


def group_by_votes(value, *funcs):
    name = 'upvoted' if value == 1 else 'downvoted'
    keygen = lambda x: [v.user for v in x.votes if v.value == value]
    return group_by(name, keygen, funcs)


def group_by_date(*funcs):
    return group_by('date', lambda x: x.created[:7], funcs)


def top_urls(*funcs, num=5):
    def top(page, acc=None):
        if acc is None:
            acc = collections.defaultdict(dict)
        for func in funcs:
            value = func(page)
            if len(acc[func.__name__]) < num:
                acc[func.__name__][page.url] = value
                break
            for k, v in acc[func.__name__].items():
                if value > v:
                    del acc[func.__name__][k]
                    acc[func.__name__][page.url] = value
                    break
        return acc
    return top

###############################################################################
# CSV Tables
###############################################################################


def save_table(table, filename):
    """Save the table into a .csv file with the given filename."""
    with open(filename, 'w') as file:
        writer = csv.writer(file)
        for row in table:
            writer.writerow(row)


def table_authors(data):
    """
    Create per-author statistics.

    data = scan_pages(group_by_authors(count, rating, wordcount))
    """
    yield (
        'USER', 'PAGES CREATED', 'NET RATING', 'AVERAGE RATING',
        'WORDCOUNT', 'AVERAGE WORDCOUNT')
    for key, val in sorted(data['authors'].items()):
        yield (
            key, val['count'], val['rating'],
            round(val['rating'] / val['count'], 2),
            val['wordcount'],
            round(val['wordcount'] / val['count'], 2))

###############################################################################
# Records
###############################################################################


def get_subtree(data, key, tag=None):
    if tag is None:
        return {k: v[key] for k, v in data['authors'].items()}
    return {k: v['tags'][tag][key] for k, v in data['authors'].items()
            if tag in v['tags']}


def top_authors(data, key, count=5, tag=None):
    """
    Top <count> authors, based on the key.

    data = scan_pages(group_by_authors(funcs, group_by_tags(funcs)))
    """
    counter = get_subtree(data, key, tag)
    return collections.Counter(counter).most_common(count)


def print_records(sn):
    funcs = count, rating, upvotes, group_by_date(count)
    tags = ['scp', 'tale', 'joke', 'essay']
    data = scan_pages(
        sn,
        group_by_authors(group_by_tags(*funcs, tags=tags), *funcs),
        top_urls(redactions))
    save_json(data)
    ###########################################################################
    print('Users with Most Upvotes (General):')
    for au, val in top_authors(data, 'upvotes'):
            print(au.ljust(40), val)
    print('Users with Most Upvotes (SCPs):')
    for au, val in top_authors(data, 'upvotes', tag='scp'):
        print(au.ljust(40), val)
    print('Users with Most Upvotes (Tales):')
    for au, val in top_authors(data, 'upvotes', tag='tale'):
        print(au.ljust(40), val)
    print('------------------------------------------------------------------')
    ###########################################################################
    print('Most SCPs Written:')
    for au, val in top_authors(data, 'count', tag='scp'):
        print(au.ljust(40), val)
    print('Most Tales Written:')
    for au, val in top_authors(data, 'count', tag='tale'):
        print(au.ljust(40), val)
    print('------------------------------------------------------------------')
    ###########################################################################
    print('Highest SCP Average (>=3):')
    for au, val in collections.Counter({
            k: v['tags']['scp']['rating'] / v['tags']['scp']['count']
            for k, v in data['authors'].items()
            if 'scp' in v['tags'] and
            v['tags']['scp']['count'] >= 3}).most_common(5):
        print(au.ljust(40), round(val, 2))
    print('Highest Tale Average (>=3):')
    for au, val in collections.Counter({
            k: v['tags']['tale']['rating'] / v['tags']['tale']['count']
            for k, v in data['authors'].items()
            if 'tale' in v['tags'] and
            v['tags']['tale']['count'] >= 3}).most_common(5):
        print(au.ljust(40), round(val, 2))
    print('------------------------------------------------------------------')
    ###########################################################################
    print('Most -J Articles Written:')
    for au, val in top_authors(data, 'count', tag='joke'):
        print(au.ljust(40), val)
    print('Highest Joke Average (>=3):')
    for au, val in collections.Counter({
            k: v['tags']['joke']['rating'] / v['tags']['joke']['count']
            for k, v in data['authors'].items()
            if 'joke' in v['tags'] and
            v['tags']['joke']['count'] >= 3}).most_common(5):
        print(au.ljust(40), round(val, 2))
    print('------------------------------------------------------------------')
    ###########################################################################
    print('Most Essay Articles Written:')
    for au, val in top_authors(data, 'count', tag='essay'):
        print(au.ljust(40), val)
    print('Highest Essay Average (>=3):')
    for au, val in collections.Counter({
            k: v['tags']['essay']['rating'] / v['tags']['essay']['count']
            for k, v in data['authors'].items()
            if 'essay' in v['tags'] and
            v['tags']['essay']['count'] >= 3}).most_common(5):
        print(au.ljust(40), round(val, 2))
    print('------------------------------------------------------------------')
    ###########################################################################
    print('Most Successful SCPs posted in 1 Month:')
    prep = {
        k: {i: j['count'] for i, j in v['tags']['scp']['date'].items()}
        for k, v in data['authors'].items()
        if 'scp' in v['tags']}
    prep = {k: max(v.items(), key=lambda x: x[1]) for k, v in prep.items()}
    for au, (date, num) in list(reversed(sorted(
            prep.items(), key=lambda x: x[1][1])))[:5]:
        print(au.ljust(40), num, date)
    print('------------------------------------------------------------------')
    ###########################################################################
    'Most Divided SCP Vote (>+20):'

    #    print('Most pages in a month ({}):'.format(description))
    #    monthly = {
    #        k: max(
    #            [(i, v[i]['count']) for i in v],
    #            key=lambda x: x[1])
    #        for k, v in get_subtree(data, 'date', tag).items()}
    #    for author, _ in collections.Counter(
    #            {k: v[1] for k, v in monthly.items()}).most_common(5):
    #        print('{0:40} {2} ({1})'.format(author + ':', *monthly[author]))


def save_json(data):
    with open('stats.json', 'w') as file:
        json.dump(data, file, sort_keys=True, indent=4)


def load_json():
    with open('stats.json', 'r') as file:
        return json.load(file)

###############################################################################

if __name__ == "__main__":
    pyscp.utils.default_logging()
    sn = pyscp.core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-01.db')
    print_records(sn)
