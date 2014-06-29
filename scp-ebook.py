#!/usr/bin/env python3

from ebooklib import epub
from urllib import urlopen
from bs4 import BeautifulSoup
import re

scp_index1 = {"url": "http://www.scp-wiki.net/scp-series"}
scp_index2 = {"url": "http://www.scp-wiki.net/scp-series-2"}
scp_index3 = {"url": "http://www.scp-wiki.net/scp-series-3"}


def scrape(page):
    '''Scrape the contents of the given url.'''
    print("downloading " + page["url"])
    soup = BeautifulSoup(urlopen(page["url"]).read())
    page["title"] = str(soup.select("#page-title")[0].text).strip()
    if page["part"] == "scp":
        page["title"] = get_scp_title(page)
    page["content"] = str(soup.select("#page-content")[0])
    return page


def get_scp_title(page):
    n = int(page["title"][4:])
    if n < 1000:
        index = scp_index1
    elif n < 2000:
        index = scp_index2
    elif n < 3000:
        index = scp_index3
    if not "data" in index:
        index["data"] = []
        soup = BeautifulSoup(urlopen(index["url"]).read())
        entries = soup.select("ul li")
        for e in entries:
            if re.match(".*>SCP-[0-9]*<.*", str(e)):
                index["data"].append(e)
    for i in index["data"]:
        if page["title"] == i.a.string:
            return page["title"] + ": " + [s[3:] for s in i.strings][1]


def make_epub(title, pages):

    #this makes magic happen
    book = epub.EpubBook()
    book.set_title(title)
    style = epub.EpubItem(uid="stylesheet", file_name="style/stylesheet.css", media_type="text/css", content=stylesheet())
    book.add_item(style)
    #do not for the love of god touch the toc
    toc = []
    section_list = {}
    n = 1    # counts the pages
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


def stylesheet():
    stylesheet = '''@namespace h "http://www.w3.org/1999/xhtml";
    .title1 {
        text-align: center;
        }
    .title1-bold {
        font-weight: bold;
        font-size: 200%;
    }
    .bold {
        font-weight: bold;
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
    .quote {
        border: 1px dashed #999;
        padding: 0 1em;
        margin: 0.5em 5%;
        background-color: #f4f4f4;
        }
    .col {
        border: 1px solid #444;
        padding: 0 1em;
        margin: 0.5em 5%;
        background-color: #ECECEC;
        }
    .col-title {
        border-bottom: 1px solid #444;
        margin: 0 -1em;
        padding: 0.5em 1em;
        font-weight: bold;
        }
    .col .quote{
        background-color: #E0E0E0;
    }
    .scp-title {
        font-weight: bold;
        font-size: 120%;
        margin: 2em 0;
        }
    .tale-title {
        font-style: italic;
        text-align: center;
        font-size: 120%;
        margin: 2em 0;
        }'''

    return stylesheet


def prettify(page):
    soup = BeautifulSoup(page["content"])
    soup.body.div.unwrap()
    soup.body.div.decompose()    # remove the rating module
    #collapsibles
    for item in soup.body.select("div.collapsible-block"):
        subtitle = item.select("a.collapsible-block-link")[0].text
        content = item.select("div.collapsible-block-content")[0]
        content["class"] = "col-content"
        col = soup.new_tag("div")
        col["class"] = "col"
        content = content.wrap(col)
        col_title = soup.new_tag("p")
        col_title["class"] = "col-title"
        col_title.string = subtitle
        content.div.insert_before(col_title)
        item.replace_with(content)
    #quote boxes
    for item in soup.body.select("blockquote"):
        item.name = "div"
        item["class"] = "quote"
    #add title to the page
    if page["part"] == "scp":
        page["content"] = "<p class='scp-title'>" + str(page["title"]) + "</p>"
    else:
        page["content"] = "<p class='tale-title'>" + str(page["title"]) + "</p>"
    page["content"] += "".join([str(i) for i in soup.body.children])
    return page

def list_pages():
    pages = []
    scp_base = "http://www.scp-wiki.net/system:page-tags/tag/scp"
    soup = BeautifulSoup(urlopen(scp_base).read())
    scp_urls_all = ["http://www.scp-wiki.net" + a["href"] for a in soup.select("div.pages-list div.pages-list-item div.title a")]
    scp_urls_main = []
    for url in scp_urls_all:
        if re.match(".*scp-[0-9]*$", url):
            scp_urls_main.append(url)
    scp_urls_main = sorted(scp_urls_main, key=natural_key)
    for url in scp_urls_main:
        pages.append({"url": url, "part": "scp"})
    return pages[:3]


def natural_key(s):
    re_natural = re.compile('[0-9]+|[^0-9]+')
    return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c in re_natural.findall(s)] + [s]

def main():
    pages = []
    titlepage_text = "<div class='title1'><h1 class='title1-bold'>SCP Foundation</h1><p class='italic'>Ebook edition</p></div>"
    license_text = """<div class='license'><p>This book contains the collected works of the SCP Foundation,
    a collaborative fiction writing website. All contents are licensed under the CC-BY-SA 3.0 license.
    The stories comprising the book are available online at www.scp-wiki.net .</p></div>"""
    pages.append({"title": "Title Page", "content": titlepage_text})
    pages.append({"title": "License", "content": license_text})
    pages.append({"title": "Introduction", "content": "Some introduction text"})
    for page in list_pages():
        page = scrape(page)
        page = prettify(page)
        pages.append(page)
    pages.append({"title": "Appendix", "content": "Placeholder; list of article authors, image artists, etc, etc."})
    book = make_epub("SCP Foundation", pages)
    epub.write_epub("test.epub", book, {})

main()