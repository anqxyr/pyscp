#!/usr/bin/env python3

from ebooklib import epub
from urllib import urlopen
from bs4 import BeautifulSoup


def get_page(url):
    '''Scrape the contents of the given url.'''
    print "downloading " + url
    page = BeautifulSoup(urlopen(url).read())
    title = str(page.select("#page-title")[0].text).strip()
    content = page.select("#page-content")[0]
    content.div.decompose()
    return {"title": str(title), "content": str(content)}


def make_epub(title, pages):
    book = epub.EpubBook()
    spine = []
    book.set_title(title)
    for p in pages:
        epub_page = epub.EpubHtml(title = p["title"], file_name = p["title"].lower().replace(" ", "_") + ".xhtml")
        epub_page.content = p["content"]
        book.add_item(epub_page)
        spine.append(epub_page)
    #book.toc = (p in spine) #???
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    return book

def prettify(title, content):
    chapter = "<h2>" + title + "</h2>" + content
    return chapter


def main():
    url_list = ["http://www.scp-wiki.net/scp-1511",
        "http://www.scp-wiki.net/scp-1425",
        "http://www.scp-wiki.net/scp-9005-2",
        "http://www.scp-wiki.net/quiet-days",
        "http://www.scp-wiki.net/black-white-black-white-black-white-black-white-black-white"]
    pages = []
    pages.append({"title": "Title Page", "content": "Placeholder Title Page"})
    pages.append({"title": "License", "content": "Placeholder Creative Commons disclaimer"})
    for url in url_list:
        page = get_page(url)
        page["content"] = prettify(page["title"], page["content"])
        pages.append(page)
    pages.append({"title": "Appendix", "content": "Placeholder; list of article authors, image artists, etc, etc."})
    book = make_epub("SCP TEST Ebook", pages)
    epub.write_epub("test.epub", book, {})

main()