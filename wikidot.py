#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import requests

###############################################################################
# Global connection session
###############################################################################


def get_req_session():
    req = requests.Session()
    req.mount('http://testwiki2.wikidot.com',
              requests.adapters.HTTPAdapter(max_retries=5))
    return req

req = get_req_session()

###############################################################################


def module(name, pageid, **kwargs):
    """Retrieve data from the specified wikidot module."""
    headers = {'Content-Type': 'application/x-www-form-urlencoded;'}
    payload = {'page_id': pageid,
               'pageId': pageid,  # fuck wikidot
               'moduleName': name,
               'wikidot_token7': '123456'}
    cookies = {'wikidot_token7': '123456'}
    for i in req.cookies:
        cookies[i.name] = i.value
    for k, v in kwargs.items():
        payload[k] = v
    data = req.post('http://testwiki2.wikidot.com/ajax-module-connector.php',
                    data=payload, headers=headers, cookies=cookies)
    return data.json()


def auth(username, password):
    payload = {'login': username,
               'password': password,
               'action': 'Login2Action',
               'event': 'login'}
    url = 'https://www.wikidot.com/default--flow/login__LoginPopupScreen'
    req.post(url, data=payload)


def get_meta(url):
    # TODO: actually write the method; add sql cache
    return '24075979'


def edit_page(url, content, comments=None, title=None):
    page_id, old_title = get_meta(url)
    if title is None:
        title = old_title
    lock = module('edit/PageEditModule', page_id, mode='page')
    params = {'source': content,
              'comments': comments,
              'title': title,
              'lock_id': lock['lock_id'],
              'lock_secret': lock['lock_secret'],
              'revision_id': lock['page_revision_id'],
              'action': 'WikiPageAction',
              'event': 'savePage',
              'wiki_page': url.split('/')[-1]}
    module('Empty', page_id, **params)

###############################################################################


def main():
    pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    auth(username='anqxyr',
         password=pasw)
    #x = module('viewsource/ViewSourceModule', '24075979')
    #print(x)
    edit_page(None, None)


if __name__ == "__main__":
    main()
