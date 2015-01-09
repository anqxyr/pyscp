#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

#import csv
#import matplotlib
#import re
import collections
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
        pass

    ###########################################################################
    # Page Processors
    ###########################################################################

    ###########################################################################
    # Generator
    ###########################################################################

    def _gen_pageframe(self):
        col_extractors = {
            'url': lambda x: x.url,
            'title': lambda x: x.title,
            'rating': lambda x: x.rating,
            'upvotes': lambda x: len([v for v in x.votes if v.value == 1]),
            'downvotes': lambda x: len([v for v in x.votes if v.value == -1]),
            'author': lambda x: x.author,
            'scp': lambda x: 'scp' in x.tags,
            'tale': lambda x: 'tale' in x.tags,
            'wordcount': lambda x: x.wordcount,
            'comments': lambda x: len(x.comments),
            'revisions': lambda x: len(x.history),
            'images': lambda x: len(x.images),
        }
        columns = collections.defaultdict(dict)
        for n, url in enumerate(crawler.Page.sn.list_all_pages()):
            logger.info('Processing page #{}'.format(n))
            p = crawler.Page(url)
            for label in col_extractors:
                func = col_extractors[label]
                columns[label][p._pageid] = func(p)
        pageframe = pd.DataFrame(columns)
        return pageframe

    def generate(self):
        with crawler.Page.from_snapshot():
            logger.info('Generating page list')
            pageframe = self._gen_pageframe()
            pageframe.to_csv('pageframe.csv', index_label='index')
            self.pageframe = pageframe

    def load(self):
        self.pageframe = pd.read_csv('pageframe.csv', index_col='index')

    ###########################################################################
    # Output Methods
    ###########################################################################

    def print_basic(self):
        pf = self.pageframe
        template_text = '| {:<33} | {:<8} | {:<8} | {:<8} |'
        template_float = '| {:<33} | {:<8.0f} | {:<8.0f} | {:<8.0f} |'
        print('-' * 70)
        print(template_text.format(
            'Field Name',
            'total',
            'skips',
            'tales'))
        print('-' * 70)
        print(template_float.format(
            'Number of pages on the site:',
            pf.index.size,
            pf[pf.scp].index.size,
            pf[pf.tale].index.size))
        print(template_float.format(
            'Number of unique authors:',
            pf.author.nunique(),
            pf[pf.scp].author.nunique(),
            pf[pf.tale].author.nunique()))
        print(template_float.format(
            'Total number of votes:',
            pf.upvotes.sum() + pf.downvotes.sum(),
            pf[pf.scp].upvotes.sum() + pf[pf.scp].downvotes.sum(),
            pf[pf.tale].upvotes.sum() + pf[pf.tale].downvotes.sum()))
        print(template_float.format(
            '    Upvotes:',
            pf.upvotes.sum(),
            pf[pf.scp].upvotes.sum(),
            pf[pf.tale].upvotes.sum()))
        print(template_float.format(
            '    Downvotes:',
            pf.downvotes.sum(),
            pf[pf.scp].downvotes.sum(),
            pf[pf.tale].downvotes.sum()))
        print('-' * 70)
        print(template_float.format(
            'Total Net Rating:',
            pf.rating.sum(),
            pf[pf.scp].rating.sum(),
            pf[pf.tale].rating.sum()))
        print(template_float.format(
            '    Average:',
            pf.rating.mean(),
            pf[pf.scp].rating.mean(),
            pf[pf.tale].rating.mean()))
        print(template_float.format(
            '    Mode:',
            pf.rating.mode()[0],
            pf[pf.scp].rating.mode()[0],
            pf[pf.tale].rating.mode()[0]))
        print(template_float.format(
            '    Deviation:',
            pf.rating.std(),
            pf[pf.scp].rating.std(),
            pf[pf.tale].rating.std()))
        print('-' * 70)
        print(template_float.format(
            'Total Wordcount:',
            pf.wordcount.sum(),
            pf[pf.scp].wordcount.sum(),
            pf[pf.tale].wordcount.sum()))
        print(template_float.format(
            '    Average:',
            pf.wordcount.mean(),
            pf[pf.scp].wordcount.mean(),
            pf[pf.tale].wordcount.mean()))
        print(template_float.format(
            'Total Comments:',
            pf.comments.sum(),
            pf[pf.scp].comments.sum(),
            pf[pf.tale].comments.sum()))
        print(template_float.format(
            '    Average:',
            pf.comments.mean(),
            pf[pf.scp].comments.mean(),
            pf[pf.tale].comments.mean()))
        print(template_float.format(
            'Total Revisions:',
            pf.revisions.sum(),
            pf[pf.scp].revisions.sum(),
            pf[pf.tale].revisions.sum()))
        print(template_float.format(
            '    Average:',
            pf.revisions.mean(),
            pf[pf.scp].revisions.mean(),
            pf[pf.tale].revisions.mean()))
        print(template_float.format(
            'Total Images:',
            pf.images.sum(),
            pf[pf.scp].images.sum(),
            pf[pf.tale].images.sum()))
        print('-' * 70)


###############################################################################


def main():
    gen = StatGenerator()
    gen.load()
    gen.print_basic()
    #print(gen.basic_lists['unique authors'])
    #gen.print_basic()
    #print(gen.basic_lists['ratings'])
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
