#!/usr/bin/env python3

from ebooklib import epub
from urllib import urlopen
from bs4 import BeautifulSoup

def get_page(url):
    print "downloading " + url
    page = BeautifulSoup(urlopen(url).read())
    title = str(page.select("#page-title")[0].text).strip()
    content = page.select("#page-content")[0]
    content.div.decompose()
    return [title,content]


def main():
    url_list=["http://www.scp-wiki.net/scp-1511",
        "http://www.scp-wiki.net/scp-1425",
        "http://www.scp-wiki.net/scp-9005-2",
        "http://www.scp-wiki.net/quiet-days",
        "http://www.scp-wiki.net/black-white-black-white-black-white-black-white-black-white"]
    book = epub.EpubBook()
    spine = ["nav"]
    book.set_title("SCP Ebook test")
    book.set_language("en")
    cc_intro = epub.EpubHtml(title="", file_name="license.xhtml")
    cc_intro.content = "Placeholder Creative Commons disclaimer."
    book.add_item(cc_intro)
    spine.append(cc_intro)
    ch_n = 1
    for url in url_list:
        page = get_page(url)
        new_chapter = epub.EpubHtml(title=page[0], file_name=page[0].lower().replace(" ", "_") + ".xhtml")
        new_chapter.content = str(page[1])
        book.add_item(new_chapter)
        spine.append(new_chapter)
    attrib = epub.EpubHtml(title="Attributions", file_name="attributions.xhtml")
    attrib.content = "Placeholder; list of article authors, image artists, etc, etc."
    book.add_item(attrib)
    spine.append(attrib)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    epub.write_epub("test.epub", book, {})

main()