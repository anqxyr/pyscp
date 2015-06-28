#!/usr/bin/env python3

"""
Stat Updater.

Calculate stats from one wiki and write it into another.
"""

###############################################################################
# Module Imports
###############################################################################

import logging

from pyscp import snapshot, wikidot, utils
from pyscp.stats import scalars, counters, filters

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)

###############################################################################


class Updater:

    scalars_author = (
        ('Pages Created', len),
        ('Net Rating', scalars.rating),
        ('Average Rating', scalars.rating_average),
        ('Wordcount', scalars.wordcount),
        ('Average Wordcount', scalars.wordcount_average))

    def __init__(self, source, target):
        self.pages = list(source.list_pages())
        self.target = target
        self.exist = [p.url for p in target.list_pages()]

    @staticmethod
    def source_counter(counter):
        """Build wikidot markup source for ranking pages."""
        source = ['||~ Rank||~ User||~ Score||']
        # sort by score, then alphabetically by user
        items = sorted(counter.items(), key=lambda x: x[0].lower())
        items = sorted(items, key=lambda x: x[1], reverse=True)
        template = '||{}||[[[user:{}]]]||{}||'
        for idx, (user, score) in enumerate(items):
            source.append(template.format(idx + 1, user, score))
        return '\n'.join(source)

    def source_author(self, user):
        """Build source code for the user's authorship stats."""
        pages = filters.user(self.pages, user)
        source = ['++ Authorship Statistics']
        if not pages:
            source.append('This user have not authored any pages.')
            return '\n'.join(source)
        for descr, func in self.scalars_author:
            text = '[[[ranking:{}]]]:@@{}@@**{}**'.format(
                descr, ' ' * (40 - len(descr)), round(func(pages), 2))
            source.append('{{%s}}' % text)
        return '\n'.join(source)

    def post(self, name, source):
        """Update if exists; create if not; retry if failed."""
        p = self.target(name)
        for _ in range(10):  # retry ten times max
            if p.url in self.exist:
                response = p.edit(source)
            else:
                title = name.split(':')
                response = p.create(source, title)
            if response['status'] == 'ok':
                return
        log.error('Failed to post: %s', name)

    def update_users(self):
        """Update the stats wiki with the author stats."""
        users = {p.author for p in self.pages}
        for user in utils.pbar(users, 'UPDATING USER STATS'):
            self.post('user:' + user, self.source_author(user))

    def update_rankings(self):
        for descr, func in utils.pbar(
                self.scalars_author, 'UPDATING RANKINGS'):
            value = self.source_counter(counters.author(self.pages, func))
            self.post('ranking:' + descr, round(value, 2))


###############################################################################

if __name__ == "__main__":
    source = snapshot.Wiki(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-06-23.db')
    target = wikidot.Wiki('scp-stats')
    target.auth('placeholder', 'placeholder')
    up = Updater(source, target)
    up.update_rankings()
    up.update_users()
