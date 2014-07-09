#!/usr/bin/env python3

from ebooklib import epub
from urllib.request import urlopen
from bs4 import BeautifulSoup
import re

scp_index1 = {"url": "http://www.scp-wiki.net/scp-series"}
scp_index2 = {"url": "http://www.scp-wiki.net/scp-series-2"}
scp_index3 = {"url": "http://www.scp-wiki.net/scp-series-3"}


class Page():

    """placeholder docstring"""

    #containes the soup of all downloaded pages
    #to prevent unneeded traffic from crosslinking pages
    cauldron = {}

    def __init__(self, url=None):
        self.url = url
        if url is not None:
            self.scrape()
            self.cook()
            self.sect = "scp"
        else:
            self.soup = None
            self.title = None
            self.data = None
            self.sect = None

    def scrape(self):
        '''Scrape the contents of the given url.'''
        if not self.url in Page.cauldron:
            print("downloading " + self.url)
            soup = BeautifulSoup(urlopen(self.url).read())
            Page.cauldron[self.url] = soup
        else:
            print("found " + self.url + " in the cauldron")
            soup = Page.cauldron[self.url]
        self.soup = soup
        return self

    def cook(self):
        '''Cook the soup, retrieve title, data, and tags'''
        self.cook_title()
        self.cook_data()
        self.cook_meta()
        return self

    def cook_title(self):
        title = self.soup.select("#page-title")[0].text.strip()
        #if page["part"] == "scp":
        #    page["title"] = get_scp_title(page)
        self.title = title
        return self

    def cook_data(self):
        data = self.soup.select("#page-content")[0]
        #data.div.unwrap()
        for i in data.select("div.page-rate-widget-box"):
            i.decompose()    # remove the rating module
        #collapsibles
        for i in data.select("div.collapsible-block"):
            subtitle = i.select("a.collapsible-block-link")[0].text
            content = i.select("div.collapsible-block-content")[0]
            content["class"] = "col-content"
            col = self.soup.new_tag("div")
            col["class"] = "col"
            content = content.wrap(col)
            col_title = self.soup.new_tag("p")
            col_title["class"] = "col-title"
            col_title.string = subtitle
            content.div.insert_before(col_title)
            i.replace_with(content)
        #quote boxes
        for i in data.select("blockquote"):
            i.name = "div"
            i["class"] = "quote"
        #remove the image block
        for i in data.select("div.scp-image-block"):
            i.decompose()
        for i in data.select("table"):
            if i.select("img"):
                i.decompose()
         #add title to the page
        #if page["part"] == "scp":
        data = "<p class='scp-title'>" + self.title + "</p>" + str(data)
        #else:
        #  page["content"] = "<p class='tale-title'>" +
        #           str(page["title"]) + "</p>"
        #page["content"] += "".join([str(i) for i in soup.children])
        self.data = data
        return self

    def cook_meta(self):
        #this will in the future also retrieve the author, posting date, etc.
        tags = [a.string for a in self.soup.select("div.page-tags a")]
        self.tags = tags
        return self

    def append_supp(self):
        print("downloading subpages for " + self.url)
        for url in self.soup.select("#page-content a"):
            url = url["href"]
            if url == "javascript:;":
                continue
            if url[0] == "/":
                url = "http://www.scp-wiki.net" + url
            supp = Page(url)
            if "supplement" in supp.tags:
                self.data = (self.data +
                             "<hr\>" +
                             supp.data)
        return self

    def to_epub(self):
        epub_page = epub.EpubHtml(self.title, self.filename)
        #the above should also set the title, but apparently it doesn't,
        #so setting it by hand below
        epub_page.title = self.title
        epub_page.content = self.data
        return epub_page


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
    style = epub.EpubItem(uid="stylesheet", file_name="style/stylesheet.css",
                          media_type="text/css", content=stylesheet())
    book.add_item(style)
    #do not for the love of god touch the toc
    toc = []
    section_list = {}
    n = 1    # counts the pages
    for page in pages:
        page.filename = "page_" + str(n).zfill(4) + ".xhtml"
        n += 1
        epub_page = page.to_epub()
        #each page should have the link to css in it, or the css won't work
        epub_page.add_item(style)
        book.add_item(epub_page)
        #building toc
        #ideally, pages in the same section will be added in sequential order
        if page.sect is not None:
            sect = page.sect
            if not sect in toc:
                toc.append(sect)
                section_list[sect] = []
            section_list[sect].append(epub_page)
        else:
            #pages without a section are things like title page, introducion.
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
        }
    p {
        font-family: "HelveticaNeue-Light", "Helvetica Neue Light", "Helvetica Neue", Helvetica, Arial, "Lucida Grande", sans-serif; 
    }'''

    return stylesheet


def make_url_list():

    scp_base = "http://www.scp-wiki.net/system:page-tags/tag/scp"
    soup = BeautifulSoup(urlopen(scp_base).read())
    urls_all = ["http://www.scp-wiki.net" + a["href"] for a in soup.select(
                "div.pages-list div.pages-list-item div.title a")]
    urls_main = []
    for url in urls_all:
        if re.match(".*scp-[0-9]*$", url):
            urls_main.append(url)
    urls_main = sorted(urls_main, key=natural_key)
    return urls_main[:98]


def natural_key(s):
    re_natural = re.compile('[0-9]+|[^0-9]+')
    return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c
            in re_natural.findall(s)] + [s]


def main():
    pages = [Page(), Page(), Page()]
    pages[0].title = "Title Page"
    pages[0].data = """<div class='title1'><h1 class='title1-bold'>
                    SCP Foundation</h1><div class='italic'>
                    Ebook edition</div></div>"""
    pages[1].title = "License"
    pages[1].data = """<div class='license'><p>This book contains the collected
                    works of the SCP Foundation, a collaborative fiction
                    writing website. All contents are licensed under the
                    CC-BY-SA 3.0 license. The stories comprising the book
                    are available online at www.scp-wiki.net .</p></div>"""
    pages[2].title = "Introduction"
    pages[2].data = "Some introduction text"
    more_pages = [Page(url) for url in make_url_list()]
    for page in more_pages:
        page.append_supp()
    pages.extend(more_pages)
    pages.append(Page())
    pages[-1].title = "Appendix"
    pages[-1].data = "Placeholder; list of article authors, image artists, etc"
    book = make_epub("SCP Foundation", pages)
    epub.write_epub("test.epub", book, {})

main()
