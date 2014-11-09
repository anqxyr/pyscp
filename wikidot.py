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
    headers = {'Content-Type': 'application/x-www-form-urlencoded;',
               'Cookie': 'wikidot_token7=123456;'}
    payload = {'page_id': pageid,
               'pageId': pageid,  # fuck wikidot
               'moduleName': name,
               'wikidot_token7': '123456'}
    for k, v in kwargs.items():
        payload[k] = v
    data = req.post('http://testwiki2.wikidot.com/ajax-module-connector.php',
                    data=payload, headers=headers)
    return data.json()


def auth():
    auth_url = 'http://urllogin.wikidot.com/login/code/2#{}:{}'
    user = 'anqxyr'
    pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    resp = req.get(auth_url.format(user, pasw))
    print(resp)


def edit_page(url, content):
    page_id = '24075979'
    lock = module('edit/PageEditModule', page_id)
    print(lock)
    exit()
    payload = {'source': 'it works!',
               'comments': 'yay'}
    post = module('Empty', page_id, **payload)
    print(post)

###############################################################################


def main():
    auth()
    edit_page(None, None)


if __name__ == "__main__":
    main()
