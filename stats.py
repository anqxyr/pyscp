#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

#import csv
#import matplotlib
#import re
import crawler
import logging
import numpy as np
import pandas as pd


###############################################################################
# Global Constants And Variables
###############################################################################

logger = logging.getLogger('scp.stats')
logger.setLevel(logging.DEBUG)

###############################################################################
# Classes
###############################################################################


class StatGenerator:

    def __init__(self):
        self.basic = defaultdict(int)
        self.basic_lists = defaultdict(list)
        self.user = defaultdict(lambda: defaultdict(int))
        self.author = defaultdict(lambda: defaultdict(int))
        self.user_tags = defaultdict(lambda: defaultdict(int))
        self.author_tags = defaultdict(lambda: defaultdict(int))
        self.year_votes = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int)))

    ###########################################################################
    # Page Processors
    ###########################################################################

    def proc_basic(self, page, suffix=''):
        self.basic['page count' + suffix] += 1
        if page.rating is not None:
            self.basic_lists['ratings' + suffix].append(page.rating)
        self.basic['wordcounts' + suffix] += page.wordcount
        self.basic['revisions' + suffix] += len(page.history)
        self.basic['comments' + suffix] += len(page.comments)
        if (page.author not in self.basic_lists['unique authors' + suffix]
            and not page.author.startswith('Anonymous')
                and not page.author == '(account deleted)'):
            self.basic_lists['unique authors' + suffix].append(page.author)
        for i in page.votes:
            if i.user not in self.basic_lists['unique voters' + suffix]:
                self.basic_lists['unique voters' + suffix].append(i.user)
            if i.value == 1:
                self.basic['upvotes' + suffix] += 1
            else:
                self.basic['downvotes' + suffix] += 1
        if not suffix and 'scp' in page.tags:
            self.proc_basic(page, suffix=': skips')
        if not suffix and 'tale' in page.tags:
            self.proc_basic(page, suffix=': tales')

    def proc_user(self, page):
        for i in page.history:
            self.user[i.user]['revisions'] += 1
        for i in page.votes:
            if i.value == 1:
                self.user[i.user]['upvotes'] += 1
            else:
                self.user[i.user]['downvotes'] += 1

    def proc_author(self, page):
        self.author[page.author]['pages created'] += 1
        if page.rating is not None:
            self.author[page.author]['net rating'] += page.rating
        self.author[page.author]['wordcount'] += page.wordcount
        self.author[page.author]['image count'] += len(page.images)

    def proc_user_tags(self, page):
        for v in page.votes:
            for t in page.tags:
                self.user_tags[v.user][t] += v.value

    def proc_author_tags(self, page):
        for t in page.tags:
            self.author_tags[page.author][t] += 1

    def proc_year_votes(self, page):
        for v in page.votes:
            if v.value == 1:
                self.year_votes[v.user][
                    page.creation_time.year]['upvotes'] += 1
            else:
                self.year_votes[v.user][
                    page.creation_time.year]['downvotes'] += 1

    ###########################################################################
    # Generator
    ###########################################################################

    def generate(self):
        with crawler.Page.from_snapshot() as sn:
            for url in sn.list_all_pages():
                logger.info('Processing page: {}'.format(url))
                p = crawler.Page(url)
                self.proc_basic(p)
                self.proc_user(p)
                self.proc_author(p)
                self.proc_user_tags(p)
                self.proc_author_tags(p)
                self.proc_year_votes(p)

    ###########################################################################
    # Output Methods
    ###########################################################################

    def print_basic(self):
        pages = 'Pages on the site: {} [{}/{}]'
        pages = pages.format(
            self.basic['page count'],
            self.basic['page count: skips'],
            self.basic['page count: tales'])
        print(pages)
        authors = 'Unique authors: {} [{}/{}]'
        authors = authors.format(
            len(self.basic_lists['unique authors']),
            len(self.basic_lists['unique authors: skips']),
            len(self.basic_lists['unique authors: tales']))
        print(authors)
        voters = 'Unique voters: {} [{}/{}]'
        voters = voters.format(
            len(self.basic_lists['unique voters']),
            len(self.basic_lists['unique voters: skips']),
            len(self.basic_lists['unique voters: tales']))
        print(voters)
        votes = ('Total votes (upvotes/downvotes):'
                 ' {} ({}/{}) [{} ({}/{}) / {} ({}/{})]')
        votes = votes.format(
            self.basic['upvotes'] + self.basic['downvotes'],
            self.basic['upvotes'],
            self.basic['downvotes'],
            self.basic['upvotes: skips'] + self.basic['downvotes: skips'],
            self.basic['upvotes: skips'],
            self.basic['downvotes: skips'],
            self.basic['upvotes: tales'] + self.basic['downvotes: tales'],
            self.basic['upvotes: tales'],
            self.basic['downvotes: tales'])
        print(votes)
        ratings = ('Total rating (average/mode):'
                   ' {} ({:.0f}/{}) [{} ({:.0f}/{}) / {} ({:.0f}/{})]')
        ratings = ratings.format(
            sum(self.basic_lists['ratings']),
            statistics.mean(self.basic_lists['ratings']),
            statistics.mode(self.basic_lists['ratings']),
            sum(self.basic_lists['ratings: skips']),
            statistics.mean(self.basic_lists['ratings: skips']),
            statistics.mode(self.basic_lists['ratings: skips']),
            sum(self.basic_lists['ratings: tales']),
            statistics.mean(self.basic_lists['ratings: tales']),
            statistics.mode(self.basic_lists['ratings: tales']))
        print(ratings)

###############################################################################

###############################################################################


def main():
    gen = StatGenerator()
    gen.generate()
    #print(gen.basic_lists['unique authors'])
    gen.print_basic()
    #print(gen.basic_lists['ratings'])
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
