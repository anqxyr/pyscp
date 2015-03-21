#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

from pyscp.core import WikidotConnector, SnapshotConnector
import pytest
import random

###############################################################################

DBPATH = '/home/anqxyr/heap/_scp/scp-wiki.2015-03-16.db'
USERNAME = ''
PASSWORD = ("""""")


@pytest.mark.parametrize('cn', [
    WikidotConnector('www.scp-wiki.net'),
    SnapshotConnector('www.scp-wiki.net', DBPATH)])
class TestSCPWikiConnectors:

    def test_revision(self, cn):
        revision = cn('scp-1511').history[0]
        assert revision.revision_id == 39167223
        assert revision.page_id == 18578010
        assert revision.number == 0
        assert revision.user == 'anqxyr'
        assert revision.time == '2013-06-30 16:34:37'
        assert revision.comment == 'INITIATE HEAVEN SUBROUTINE'

    def test_post(self, cn):
        post = cn('SCP-1511').comments[0]
        assert post.post_id == 1806664
        assert post.thread_id == 666715
        assert post.parent is None
        assert post.title is None
        assert post.user == 'FlameShirt'
        assert post.time == '2013-06-30 16:47:22'
        assert post.wordcount == 26

    def test_list_pages(self, cn):
        pages = list(cn.list_pages(author='anqxyr', tag='crystalline'))
        assert pages == ['http://www.scp-wiki.net/scp-1511']

    def test_list_pages_rewrites(self, cn):
        pages = list(cn.list_pages(author='thedeadlymoose', tag='thermal'))
        assert 'http://www.scp-wiki.net/scp-003' in pages


class TestActiveMethods:

    @pytest.fixture
    def wiki(self, cache=[]):
        if cache:
            return cache[0]
        if not USERNAME or not PASSWORD:
            pytest.skip('need authentication data')
        wiki = WikidotConnector('testwiki2')
        wiki.auth(USERNAME, PASSWORD)
        cache.append(wiki)
        return wiki

    def test_edit_page(self, wiki):
        value = random.randint(0, 1000000)
        p = wiki('page1')
        p.edit(value, comment='automated test')
        assert p.source == str(value)

    def test_revert(self, wiki):
        p = wiki('page1')
        p.revert_to(24)
        assert p.source == 'no source here'

    def test_set_tags(self, wiki):
        value = random.randint(0, 1000000)
        p = wiki('page1')
        p.set_tags(p.tags + [str(value)])
        assert str(value) in p.tags


if __name__ == '__main__':
    pytest.main()
