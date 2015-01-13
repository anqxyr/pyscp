#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

#import csv
#import matplotlib
#import re
import arrow
import bs4
import collections
import crawler
import logging
import re
#import numpy as np
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
        self.datadir = crawler.Snapshot.database_directory + 'stats/'

    ###########################################################################
    # Page Processors
    ###########################################################################

    ###########################################################################
    # Generator
    ###########################################################################

    def _generate_pages(self, frames, page):
        basic = ('url', 'title', 'rating', 'author', 'created', 'wordcount')
        for x in basic:
            frames['pages'][x][page._pageid] = getattr(page, x)
        lists = ('images', 'comments', 'history')
        for x in lists:
            frames['pages'][x][page._pageid] = len(getattr(page, x))
        for i in page.tags:
            index = len(frames['tags']['page'])
            frames['tags']['page'][index] = page._pageid
            frames['tags']['tag'][index] = i

    def _generate_votes(self, frames, page):
        for i in page.votes:
            index = len(frames['votes']['page'])
            for x in ('user', 'value'):
                frames['votes'][x][index] = getattr(i, x)
            frames['votes']['page'][index] = page._pageid

    def _generate_revisions(self, frames, page):
        for i in page.history:
            index = len(frames['revisions']['page'])
            for x in ('user', 'time'):
                frames['revisions'][x][index] = getattr(i, x)
            frames['revisions']['page'][index] = page._pageid

    def _generate_comments(self, frames, page):
        for i in page.comments:
            for x in ('user', 'time', 'title'):
                frames['comments'][x][i.post_id] = getattr(i, x)
            wc = len(re.findall(r"[\w'█_-]+",
                                bs4.BeautifulSoup(i.content).text))
            frames['comments']['wordcount'][i.post_id] = wc
            frames['comments']['page'][i.post_id] = page._pageid

    def generate(self):
        frames = collections.defaultdict(lambda: collections.defaultdict(dict))
        with crawler.Page.from_snapshot():
            logger.info('Generating DataFrame objects')
            for n, url in enumerate(crawler.Page.sn.list_all_pages()):
                logger.info('Processing page #{}'.format(n))
                p = crawler.Page(url)
                self._generate_pages(frames, p)
                self._generate_votes(frames, p)
                self._generate_revisions(frames, p)
                self._generate_comments(frames, p)
        for i in frames:
            frame = pd.DataFrame(frames[i])
            frame.to_csv(
                '{}_{}.csv'.format(self.datadir, i),
                index_label='index')
            setattr(self, i, frame)

    def load(self):
        for i in ('pages', 'votes', 'tags', 'revisions', 'comments'):
            frame = pd.read_csv(
                '{}_{}.csv'.format(self.datadir, i),
                index_col='index')
            setattr(self, i, frame)

    ###########################################################################
    # Output Methods
    ###########################################################################

    def print_basic(self):
        msgs = (
            '~ Pages',
            '~ Users',
            'Authors',
            'Voters',
            'Editors',
            '~ Votes',
            'Upvotes',
            'Downvotes',
            '~ Rating',
            'Average',
            'Mode',
            'Deviation',
            '~ Wordcount',
            'Average',
            '~ Comments',
            '~ Revisions',
            '~ Images')
        funcs = (
            lambda x: x.index.size,
            lambda x: len(
                set(x.author.unique()) |
                set(self.votes[self.votes.page.isin(x.index)].user.unique()) |
                set(self.revisions[
                    self.revisions.page.isin(x.index)].user.unique())),
            lambda x: x.author.nunique(),
            lambda x: self.votes[self.votes.page.isin(x.index)].user.nunique(),
            lambda x: self.revisions[
                self.revisions.page.isin(x.index)].user.nunique(),
            lambda x: self.votes[self.votes.page.isin(x.index)].index.size,
            lambda x: self.votes[
                (self.votes.page.isin(x.index)) &
                (self.votes.value == 1)].index.size,
            lambda x: self.votes[
                (self.votes.page.isin(x.index)) &
                (self.votes.value == -1)].index.size,
            lambda x: x.rating.sum(),
            lambda x: x.rating.mean(),
            lambda x: x.rating.mode()[0],
            lambda x: x.rating.std(),
            lambda x: x.wordcount.sum(),
            lambda x: x.wordcount.mean(),
            lambda x: x.comments.sum(),
            lambda x: x.history.sum(),
            lambda x: x.images.sum())
        skips = self.tags[self.tags.tag == 'scp'].page
        tales = self.tags[self.tags.tag == 'tale'].page
        header = '||~ {} ||~ {} ||~ {} ||~ {} ||'
        header = header.format('Field', 'Total', 'Skips', 'Tales')
        print(header)
        row = '||{} || {:.0f} || {:.0f} || {:.0f} ||'
        for msg, func in zip(msgs, funcs):
            print(row.format(
                msg,
                func(self.pages),
                func(self.pages[self.pages.index.isin(skips)]),
                func(self.pages[self.pages.index.isin(tales)])))

    def _days_on_the_site(self, user):
        print(user)
        com = self.comments[self.comments.user == user].time.dropna().min()
        rev = self.revisions[self.revisions.user == user].time.dropna().min()
        if pd.isnull(com) and pd.isnull(rev):
            return 999999 # this is a dirty hack :(
        elif pd.isnull(com) or pd.isnull(rev):
            act = com if pd.notnull(com) else rev
        else:
            act = min(com, rev)
        return (arrow.now() - arrow.get(act)).days

    def create_table_authors(self):
        authors = pf.author.dropna().unique()
        author_data = lambda x: self.pages[self.pages.author == x]
        columns['pages created'] = {i: au(i).index.size for i in aus}
        columns['net rating'] = {i: au(i).rating.sum() for i in aus}
        columns['average rating'] = {i: au(i).rating.mean().round(2) for i in aus}
        columns['rating per day'] = {}
        for i in aus:
            first_comment = cf[cf.user == i].time.dropna().min()
            first_revision = rf[rf.user == i].time.dropna().min()
            if pd.isnull(first_comment) and pd.isnull(first_revision):
                continue
            elif pd.isnull(first_comment):
                first_activity = arrow.get(first_revision)
            elif pd.isnull(first_revision):
                first_activity = arrow.get(first_comment)
            else:
                first_activity = min(
                    arrow.get(first_comment), arrow.get(first_revision))
            days_on_site = (arrow.now() - first_activity).days
            rating = au(i).rating.sum() / days_on_site
            columns['rating per day'][i] = rating
        columns['wordcount'] = {i: au(i).wordcount.sum() for i in aus}
        columns['average wordcount'] = {i: au(i).wordcount.mean() for i in aus}
        columns['image count'] = {i: au(i).images.sum() for i in aus}
        table_authors = pd.DataFrame(columns)
        table_authors.to_csv(self.dir + 'table_authors.csv', index_col='user')

    def create_table_ratings(self):
        ratings = collections.defaultdict(dict)
        contributors = self.pages.author.unique()
        newbies = [
            i for i in self.votes.user.unique()
            if self._days_on_the_site(i) < 180]
        staff = [
            'DrEverettMann', 'DrBright', 'DrClef', 'Drewbear',
            'Photosynthetic', 'Sorts', 'thedeadlymoose', 'TroyL', 'Crayne',
            'Dexanote', 'Eskobar', 'Gaffney', 'Pig_catapult', 'Roget',
            'Silberescher', 'Sophia', 'SoullessSingularity', 'Vivax', 'Zyn',
            'Accelerando', 'Doctor', 'anqxyr', 'pxdnbluesoul', 'Bouncl',
            'Faminepulse', 'FlameShirt', 'FortuneFavorsBold', 'Kalinin',
            'MisterFlames', 'murphy_slaw', 'Nioki', 'ProcyonLotor', 'Reject',
            'Riemann', 'Rumetzen', 'spikebrennan', 'thattallfellow', 'Tuomey',
            'Vincent_Redgrave', 'weizhong', 'Wogglebug', 'Blaroth', 'Chubert',
            'Devereaux', 'djkaktus', 'Fantem', 'Kate', 'LurkD', 'Pixeltasim']
        for n, (index, row) in enumerate(self.pages.iterrows()):
            print(n)
            ratings['full rating'][row['url']] = row['rating']
            ratings['contributor rating'][row['url']] = self.votes[
                (self.votes.user.isin(contributors)) &
                (self.votes.page == row.name)].value.sum()
            ratings['newbie rating'][row['url']] = self.votes[
                (self.votes.user.isin(newbies)) &
                (self.votes.page == row.name)].value.sum()
            ratings['staff rating'][row['url']] = self.votes[
                (self.votes.user.isin(staff)) &
                (self.votes.page == row.name)].value.sum()
        ratings = pd.DataFrame(ratings)
        ratings.to_csv(
            '{}table_ratings.csv'.format(self.datadir),
            index_label='page')

###############################################################################


def main():
    gen = StatGenerator()
    gen.load()
    gen.create_table_ratings()
    #gen.print_basic()
    #print(gen.basic_lists['unique authors'])
    #gen.print_basic()
    #print(gen.basic_lists['ratings'])
    pass

if __name__ == "__main__":
    crawler.enable_logging(logger)
    main()
