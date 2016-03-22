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
import string

###############################################################################

log = logging.getLogger('pyscp')

###############################################################################


class Updater:

    def __init__(self, wiki, pages):
        self.wiki = wiki
        self.pages = pages

    def format_author(self, author):
        if not author:
            return ''
        deleted = ['Wilt', 'Doctor Whiteface']
        if author in deleted:
            return author
        return '[[user {}]]'.format(author)

    def get_section(self, name, pages, header='', disp=None):
        if not disp:
            disp = name
        template = '\n'.join([
            '[[# {}]]', '[[div class="section"]]', '+++ {}', '[#top ⇑]',
            '{}', '{}', '[[/div]]', ''])
        if pages:
            body = '\n'.join(map(
                self.format_page, sorted(pages, key=self.sortfunc)))
        else:
            body = '||||||= **NO DATA AVAILABLE**||'
        return template.format(name, disp, header, body)

    def update(self, target_base, count=4):
        output = ['']
        for key in self.keys():
            section = self.get_section(
                key, [p for p in self.pages if self.keyfunc(p) == key])
            if len(output[-1]) + len(section) < 180000:
                output[-1] += section
            else:
                output.append(section)
        targets = (
            [target_base + str(i + 1) for i in range(count)]
            if count else [target_base])
        for idx, target in enumerate(targets):
            source = output[idx] if idx < len(output) else ''
            self.wiki(target).edit(source, comment='automated update')
            log.info('{} {}'.format(target, len(source)))


class TaleUpdater(Updater):

    def get_section(self, name, pages, disp=None):
        return super().get_section(
            name, pages, '||~ Title||~ Author||~ Created||', disp)

    def format_page(self, page=None):
        return '||[[[{}|{}]]]||{}||//{}//||\n||||||{}||'.format(
            page._body.name, page._body.title, self.format_author(page.author),
            page.created[:10], page._body.preview)


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


def update_tale_hubs():
    wiki = pyscp.wikidot.Wiki('scp-wiki')
    with open('pyscp_bot.pass') as file:
        wiki.auth('pyscp_bot', file.read())
    pages = list(wiki.list_pages(
        tags='tale -hub -_sys', body='title created_by created_at preview'))
    target = 'component:tales-by-{}-'
    pyscp.utils.default_logging()

    TalesByTitle(wiki, pages).update(target.format('title'))
    TalesByAuthor(wiki, pages).update(target.format('author'))
    TalesByDate(wiki, pages).update(target.format('date'))

###############################################################################

update_tale_hubs()
