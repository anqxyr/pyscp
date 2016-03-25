#!/usr/bin/env python3

"""
Update wiki pages.

This script is used to update scp-wiki tale hubs and other such pages.
"""

###############################################################################
# Module Imports
###############################################################################

import arrow
import logging
import pyscp
import re
import string

###############################################################################

log = logging.getLogger('pyscp')

###############################################################################


class Updater:

    def __init__(self, wiki, pages):
        self.wiki = wiki
        self.pages = pages

    def get_author(self, page):
        author = self.format_author(page.author)
        if page.rewrite_author:
            if author != '-':
                author += ' (original author) _\n'
            author += '{} (rewrite author)'.format(
                self.format_author(page.rewrite_author))
        if 'co-authored' in page.tags:
            author = '{} (co-author)'.format(author)
        return author

    def format_author(self, author):
        if not author:
            return '-'
        deleted = [
            'Wilt', 'Doctor Whiteface', 'Epic Phail Spy',
            'Amuness Creeps', 'Amuness Creeeps']
        if author in deleted:
            return author
        return '[[user {}]]'.format(author)

    def get_section(self, name, pages, disp=None):
        if not disp:
            disp = name
        template = '\n'.join([
            '[[# {}]]', '[[div class="section"]]', '+++ {}', '[#top ⇑]',
            '{}', '{}', '[[/div]]', ''])
        if pages:
            body = '\n'.join(map(
                self.format_page, sorted(pages, key=self.sortfunc)))
        else:
            body = self.NODATA
        return template.format(name, disp, self.HEADER, body)

    def update(self, *targets):
        output = ['']
        for key in self.keys():
            section = self.get_section(
                key, [p for p in self.pages if self.keyfunc(p) == key])
            if len(output[-1]) + len(section) < 180000:
                output[-1] += section
            else:
                output.append(section)
        for idx, target in enumerate(targets):
            source = output[idx] if idx < len(output) else ''
            self.wiki(target).edit(source, comment='automated update')
            log.info('{} {}'.format(target, len(source)))

###############################################################################


class TaleUpdater(Updater):

    HEADER = '||~ Title||~ Author||~ Created||'
    NODATA = '||||||= **NO DATA AVAILABLE**||'

    def format_page(self, page=None):
        return '||[[[{}|]]]||{}||//{}//||\n||||||{}||'.format(
            page._body.name, self.get_author(page),
            page.created[:10], page._body.preview)

    def update(self, target):
        targets = [
            'component:tales-by-{}-{}'.format(target, i + 1) for i in range(4)]
        super().update(*targets)


class TalesByTitle(TaleUpdater):

    def keys(self):
        return list(string.ascii_uppercase) + ['misc']

    def keyfunc(self, page):
        l = page._body.title[0]
        return l.upper() if l.isalpha() else 'misc'

    def sortfunc(self, page):
        return page._body.title


class TalesByAuthor(TaleUpdater):

    def keys(self):
        return sorted(list(string.ascii_uppercase) + ['Dr', 'misc'])

    def keyfunc(self, page):
        if not page.author:
            return 'misc'
        l = page.author[0]
        return l.upper() if l.isalpha() else 'misc'

    def sortfunc(self, page):
        return page.author if page.author else ''


class TalesByDate(TaleUpdater):

    def get_section(self, name, pages):
        return super().get_section(
            name, pages, arrow.get(name, 'YYYY-MM').format('MMM YYYY'))

    def keys(self):
        return [i.format('YYYY-MM') for i in
                arrow.Arrow.range('month', arrow.get('2008-07'), arrow.now())]

    def keyfunc(self, page=None):
        return page.created[:7]

    def sortfunc(self, page):
        return page.created


def update_tale_hubs(wiki):
    pages = list(wiki.list_pages(
        tags='tale -hub -_sys',
        body='title created_by created_at preview tags'))
    TalesByTitle(wiki, pages).update('title')
    TalesByAuthor(wiki, pages).update('author')
    TalesByDate(wiki, pages).update('date')

###############################################################################


class CreditUpdater(Updater):

    HEADER = ''
    NODATA = '||||= **NO DATA AVAILABLE**||'

    def format_page(self, page):
        return '||[[[{}|{}]]]||{}||'.format(
            page._body.name, page.title.replace('[', '').replace(']', ''),
            self.get_author(page))

    def update(self, target):
        super().update('component:credits-' + target)


class SeriesCredits(CreditUpdater):

    def __init__(self, wiki, pages, series):
        super().__init__(wiki, pages)
        self.series = (series - 1) * 1000

    def keys(self):
        return ['{:03}-{:03}'.format(i or 2, i + 99)
                for i in range(self.series, self.series + 999, 100)]

    def keyfunc(self, page):
        num = re.search('[scp]+-([0-9]+)$', page._body.name)
        if not num:
            return
        num = (int(num.group(1)) // 100) * 100
        return '{:03}-{:03}'.format(num or 2, num + 99)

    def sortfunc(self, page):
        return page._body.title


def update_credit_hubs(wiki):
    pages = list(wiki.list_pages(
        tag='scp', body='title created_by tags'))
    wiki = pyscp.wikidot.Wiki('scpsandbox2')
    with open('pyscp_bot.pass') as file:
        wiki.auth('pyscp_bot', file.read())

    SeriesCredits(wiki, pages, 1).update('series1')
    SeriesCredits(wiki, pages, 2).update('series2')
    SeriesCredits(wiki, pages, 3).update('series3')

###############################################################################

wiki = pyscp.wikidot.Wiki('scp-wiki')
#with open('pyscp_bot.pass') as file:
#    wiki.auth('pyscp_bot', file.read())

pyscp.utils.default_logging()
update_credit_hubs(wiki)

#update_tale_hubs(wiki)
