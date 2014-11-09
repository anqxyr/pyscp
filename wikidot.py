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
               'originSiteId': '699677',
               'action': 'Login2Action',
               'event': 'login'}
    url = 'https://www.wikidot.com/default--flow/login__LoginPopupScreen'
    req.post(url, data=payload)


def edit_page(url, content):
    page_id = '24075979'
    params = {'mode': 'page',
              'wiki_page': 'page1'}
    lock = module('edit/PageEditModule', page_id, **params)
    import pprint
    pprint.pprint(lock)
    print(lock['lock_id'])
    print(lock['lock_secret'])
    exit()
    payload = {'source': 'it works!',
               'comments': 'yay'}
    post = module('Empty', page_id, **payload)
    print(post)

###############################################################################


def main():
    pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    auth(username='anqxyr',
         password=pasw)
    edit_page(None, None)


if __name__ == "__main__":
    main()
