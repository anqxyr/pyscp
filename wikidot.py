#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import requests

from collections import namedtuple

###############################################################################


class WikidotConnector:

    def __init__(self, site):
        if site[-1] != '/':
            site += '/'
        self.site = site
        req = requests.Session()
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req

    def module(self, name, pageid, **kwargs):
        """Retrieve data from the specified wikidot module."""
        headers = {'Content-Type': 'application/x-www-form-urlencoded;'}
        payload = {
            'page_id': pageid,
            'pageId': pageid,  # fuck wikidot
            'moduleName': name,
            'wikidot_token7': '123456'}
        cookies = {'wikidot_token7': '123456'}
        for i in self.req.cookies:
            cookies[i.name] = i.value
        for k, v in kwargs.items():
            payload[k] = v
        data = self.req.post(self.site + 'ajax-module-connector.php',
                             data=payload, headers=headers, cookies=cookies)
        return data.json()

    def auth(self, username, password):
        payload = {
            'login': username,
            'password': password,
            'action': 'Login2Action',
            'event': 'login'}
        url = 'https://www.wikidot.com/default--flow/login__LoginPopupScreen'
        self.req.post(url, data=payload)

    def edit_page(self, page_id, wiki_page, data):
        lock = self.module('edit/PageEditModule', page_id, mode='page')
        params = {
            'source': data.source,
            'comments': data.comments,
            'title': data.title,
            'lock_id': lock['lock_id'],
            'lock_secret': lock['lock_secret'],
            'revision_id': lock['page_revision_id'],
            'action': 'WikiPageAction',
            'event': 'savePage',
            'wiki_page': wiki_page}
        self.module('Empty', page_id, **params)

###############################################################################


def main():
    wiki = WikidotConnector('http://testwiki2.wikidot.com')
    pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    wiki.auth(username='anqxyr', password=pasw)
    edit = namedtuple('PageEditData', 'title source comments')
    e = edit('I am the Title, █████', 'no source here', None)
    wiki.edit_page('24075979', 'page1', e)


if __name__ == "__main__":
    main()
