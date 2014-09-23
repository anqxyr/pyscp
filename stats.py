#!/usr/bin/env python3

import arrow
import scp_crawler
from bs4 import BeautifulSoup


pages = []


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


def averages(pages):
    dates = []
    for page in pages:
        if page.time not in dates:
            dates.append(page.time)
    average_ratings = {}
    average_chars = {}
    average_words = {}
    for date in dates:
        pages_on_date = [p for p in pages if p.time == date]
        L = len(pages_on_date)
        average_ratings[date] = sum([int(p.rating) for p in pages_on_date]) / L
        average_chars[date] = sum([p.charcount for p in pages_on_date]) / L
        average_words[date] = sum([p.wordcount for p in pages_on_date]) / L
    return average_ratings, average_chars, average_words


def main():
    for page in scp_crawler.all_pages():
        process_page(page)
    print("Total pages: {}".format(len(pages)))
    print("Skips: {}".format(len([i for i in pages if "scp" in i.tags])))
    print("Tales: {}".format(len([i for i in pages if "tale" in i.tags])))
    gl_rat = sum([int(p.rating) for p in pages]) / len(pages)
    gl_w = sum([p.wordcount for p in pages]) / len(pages)
    print("Global average rating: {}".format(gl_rat))
    print("Global average wordcount: {}".format(gl_w))
    av_rat, av_c, av_w = averages(pages)
    av_rat_s, av_c_s, av_w_s = averages([i for i in pages if "scp" in i.tags])
    av_rat_t, av_c_t, av_w_t = averages([i for i in pages if "tale" in i.tags])
    print("Average ratings: {}".format(av_rat))
    print("Average wordcount: {}".format(av_w))
    print("Average skip ratings: {}".format(av_rat_s))
    print("Average skip wordcount: {}".format(av_w_s))
    print("Average tale ratings: {}".format(av_rat_t))
    print("Average tale wordcount: {}".format(av_w_t))

   

        


main()
