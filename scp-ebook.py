#!/usr/bin/env python3

from ebooklib import epub
from urllib import urlopen
from bs4 import BeautifulSoup


def get_page(url):
    '''Scrape the contents of the given url.'''
    print("downloading " + url)
    page = BeautifulSoup(urlopen(url).read())
    title = str(page.select("#page-title")[0].text).strip()
    content = page.select("#page-content")[0]
    return {"title": title, "content": content, "part": "SCP Objects"}


def make_epub(title, pages):

    #this makes magic happen
    book = epub.EpubBook()
    book.set_title(title)
    style = epub_add_css(book)
    #do not for the love of god touch the toc
    toc = []
    section_list = {}
    n = 1    #counts the pages
    for page in pages:
        filename = "page_" + str(n).zfill(4) + ".xhtml"
        n += 1
        epub_page = epub.EpubHtml(page["title"], filename)
        #the above should also set the title, but apparently it doesn't, so setting it by hand below
        epub_page.title = page["title"]
        epub_page.content = page["content"]
        #each page should have the link to css in it, or the css won't work
        epub_page.add_item(style)
        book.add_item(epub_page)
        #building toc
        #ideally, all the pages belonging to the same section will be added in sequential order
        if "part" in page:
            part = page["part"]
            if not part in toc:
                toc.append(part)
                section_list[part] = []
            section_list[part].append(epub_page)
        else:
            #pages without a section are things like title page, introducion, etc.
            toc.append(epub_page)
    for item in toc:
        if type(item) == str:
            for page in section_list[item]:
                book.spine.append(page)
            index = toc.index(item)
            toc[index] = (epub.Section(item), tuple(section_list[item]))
        else:
            book.spine.append(item)
    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    return book


def epub_add_css(book):
    stylesheet = '''@namespace h "http://www.w3.org/1999/xhtml";
.title1 {
    text-align: center;
    }
.bold {
    font-style: bold;
    font-size: 200%;
    }
.italic {
    font-style: italic;
    }
.license {
    font-style: italic;
    text-align: justify;
    max-width: 80%;
    margin-left: 10%;
    margin-top: 40%;
    }
blockquote {
    border: 1px dashed #999;
    padding: 0 1em;
    background-color: #f4f4f4;
    }'''
    stylesheet_css = epub.EpubItem(uid="stylesheet", file_name="style/stylesheet.css", media_type="text/css", content=stylesheet)
    book.add_item(stylesheet_css)
    return stylesheet_css


def prettify(title, content):
    content.div.decompose()
    chapter = "<h2>" + str(title) + "</h2>" + str(content)
    return chapter


def main():
    url_list = ["http://www.scp-wiki.net/scp-1511",
        "http://www.scp-wiki.net/scp-1425",
        "http://www.scp-wiki.net/scp-9005-2",
        "http://www.scp-wiki.net/quiet-days",
        "http://www.scp-wiki.net/black-white-black-white-black-white-black-white-black-white"]
    pages = []
    titlepage = "<div class='title1'><h1 class='bold'>SCP Foundation</h1><p class='italic'>Ebook edition</p></div>"
    license_text = """<div class='license'><p>This book contains the collected works of the SCP Foundation,
    a collaborative fiction writing website. All contents are licensed under the CC-BY-SA 3.0 license.
    The stories comprising the book are available online at www.scp-wiki.net .</p></div>"""
    pages.append({"title": "Title Page", "content": titlepage})
    pages.append({"title": "License", "content": license_text})
    pages.append({"title": "Introduction", "content": "Some introduction text"})
    for url in url_list:
        page = get_page(url)
        page["content"] = prettify(page["title"], page["content"])
        pages.append(page)
    pages[5]["part"] = "Tales"
    pages[6]["part"] = "Tales"
    pages[7]["part"] = "Tales"
    pages.append({"title": "Appendix", "content": "Placeholder; list of article authors, image artists, etc, etc."})
    book = make_epub("SCP TEST Ebook", pages)
    epub.write_epub("test.epub", book, {})

main()