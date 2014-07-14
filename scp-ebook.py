#!/usr/bin/env python3

from ebooklib import epub
from urllib.request import urlopen
from bs4 import BeautifulSoup
import re


class Page():

    """placeholder docstring"""

    #containes the soup of all downloaded pages
    #to prevent unneeded traffic from crosslinking pages
    scp_index = {}
    cauldron = {}

    def __init__(self, url=None):
        self.url = url
        if url is not None:
            self.scrape()
            self.cook()
        self.children = []

    def scrape(self):
        '''Scrape the contents of the given url.'''
        if not self.url in Page.cauldron:
            print("downloading " + self.url)
            soup = BeautifulSoup(urlopen(self.url))
            Page.cauldron[self.url] = soup
        else:
            print("found " + self.url + " in the cauldron")
            soup = Page.cauldron[self.url]
        self.soup = soup
        return self

    def cook(self):
        '''Cook the soup, retrieve title, data, and tags'''
        self.cook_meta()    # must be cooked first
        self.cook_title()
        self.cook_data()
        return self

    def cook_title(self):
        title = self.soup.select("#page-title")[0].text.strip()
        # because 001 proposals don't have their own tag,
        # it's easier to check if the page is a mainlist skip
        # by regexping its url instead of looking at tags
        if "scp" in self.tags and re.match(".*scp-[0-9]{3,4}$", self.url):
            if Page.scp_index == {}:
                index_urls = ["http://www.scp-wiki.net/scp-series",
                              "http://www.scp-wiki.net/scp-series-2",
                              "http://www.scp-wiki.net/scp-series-3"]
                for u in index_urls:
                    s = BeautifulSoup(urlopen(u))
                    entries = s.select("ul li")
                    for e in entries:
                        if re.match(".*>SCP-[0-9]*<.*", str(e)):
                            i = e.text.split(" - ")
                            Page.scp_index[i[0]] = i[1]
            title = title + ": " + Page.scp_index[title]
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

    def get_children(self):
        for a in self.soup.select("#page-content a"):
            if not a.has_attr("href"):
                continue
            url = a["href"]
            #this should be taken care of in cook_data instead
            if url == "javascript:;":
                continue
            if url[0] == "/":
                url = "http://www.scp-wiki.net" + url
            if url[0] == "#":
                continue
            #off-site pages should not be included
            #will also break on absolute links to scp-wiki.wikidot.com
            #this is to be considered a good thing
            if not re.match("http://www\.scp-wiki\.net.*", url):
                continue
            if url in [c.url for c in self.children]:
                continue
            c = Page(url)
            if "scp" in self.tags and "supplement" in c.tags:
                self.children.append(c)
                c.get_children()
            if "hub" in self.tags and ("tale" in c.tags or
                                       "goi-format" in c.tags):
                self.children.append(c)
                c.get_children()
            if "splash" in self.tags and "supplement" in c.tags:
                self.children.append(c)
                c.get_children()
        return self


def make_epub(title, pages):

    #this makes magic happen
    book = epub.EpubBook()
    book.set_title(title)
    style = epub.EpubItem(uid="stylesheet", file_name="style/stylesheet.css",
                          media_type="text/css", content=stylesheet())
    book.add_item(style)
    for page in pages:
        add_page(book, page)
    book.add_item(epub.EpubNcx())
    #book.add_item(epub.EpubNav())
    return book


def add_page(book, page):
    n = len(book.items) - 1
    page.filename = "page_" + str(n).zfill(4) + ".xhtml"
    epage = epub.EpubHtml(page.title, page.filename)
    #the above should also set the title, but apparently it doesn't,
    #so setting it by hand below
    epage.title = page.title
    epage.content = page.data
    epage.add_item(book.get_item_with_id("stylesheet"))
    book.add_item(epage)
    book.toc.append(epage)
    book.spine.append(epage)
    for c in page.children:
        add_page(book, c)


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
        font-family: "HelveticaNeue-Light", "Helvetica Neue Light",
        "Helvetica Neue", Helvetica, Arial, "Lucida Grande", sans-serif;
    }'''

    return stylesheet


def collect_pages():
    skip_base = "http://www.scp-wiki.net/system:page-tags/tag/scp"
    skip_soup = BeautifulSoup(urlopen(skip_base))
    skip_urls = ["http://www.scp-wiki.net" + a["href"] for a in
                 skip_soup.select("""div.pages-list
                                  div.pages-list-item div.title a""")
                 if re.match(".*scp-[0-9]*$", a["href"])]
    skip_urls = sorted(skip_urls, key=natural_key)
    skips_by_block = [[u for u in skip_urls
                       if (n * 100 <=
                           int(re.search("[0-9]{3,4}$", u).group(0))
                           < (n + 1) * 100)]
                      for n in range(30)]
    pages = []
    skips = Page()
    skips.title = "SCP Database"
    skips.data = """<h1 class='title1'>SCP Object Database"""
    pages.append(skips)
    for b in skips_by_block[5:6]:
        block = Page()
        block.title = "Block " + str(skips_by_block.index(b)).zfill(2)
        block.data = ""
        skips.children.append(block)
        for url in b:
            p = Page(url)
            p.get_children()
            block.children.append(p)
    return pages


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
    pages.extend(collect_pages())
    pages.append(Page())
    pages[-1].title = "Appendix"
    pages[-1].data = "Placeholder; list of article authors, image artists, etc"
    book = make_epub("SCP Foundation", pages)
    epub.write_epub("test.epub", book, {})

main()
