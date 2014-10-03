#!/usr/bin/env python3

import arrow
import scp_crawler
import sqlite3
from bs4 import BeautifulSoup


conn = sqlite3.connect()


class PageData():
    pass


def process_page(page):
    if page.url in [i.url for i in pages]:
        return
    print("Processing {}".format(page.title))
    data = PageData()
    data.url = page.url
    data.charcount = len(page.data)
    data.wordcount = len(page.data.split(" "))
    data.rating = page.rating
    history_soup = BeautifulSoup(page.history)
    for row in reversed(history_soup.select("tr")):
        edit_au, edit_time, desc = (i.text for i in row.select("td")[4:7])
        data.time = arrow.get(edit_time, "DD MMM YYYY HH:mm").format("YYYY-MM")
        break
    data.tags = page.tags
    pages.append(data)
    for c in page.list_children():
        process_page(c)


def main():
    for page in scp_crawler.all_pages():
        process_page(page)


main()
