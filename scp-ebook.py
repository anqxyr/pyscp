#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################


import arrow
import copy
import natsort
import os
import re
import requests
import shutil
import tempfile

from collections import defaultdict
from lxml import etree, html
from scp_crawler import Page

###############################################################################
# Global Constants
###############################################################################

SAVEPATH = '/home/anqxyr/heap/_scp/ebook/'

###############################################################################
# Primary Classes
###############################################################################


class Epub():

    """"""

    allpages_global = []

    def __init__(self, title):
        self.title = title
        self.dir = tempfile.TemporaryDirectory()
        self.templates = {}
        for i in os.listdir("templates"):
            self.templates[i.split(".")[0]] = etree.parse(
                "{}/templates/{}".format(os.getcwd(), i))
        self.allpages = []
        #pre-building toc
        self.toc = self.templates["toc"]
        self.toc.xpath("/*/*[2]/*")[0].text = title
        self.images = {}

    def add_page(self, page, node=None):
        #each page can only appear once in the book
        if page.url in Epub.allpages_global or page.data is None:
            return
        epub_page = copy.deepcopy(self.templates["page"])
        #XPath expressions are pre-generated with etree.getpath
        #I have no clue how they work
        epub_page.xpath("/*/*[1]/*[1]")[0].text = page.title
        epub_page.xpath("/*/*[2]")[0].append(html.fromstring(page.data))
        #write the page on disk
        uid = "page_{:0>4}".format(len(self.allpages))
        epub_page.write("{}/{}.xhtml".format(self.dir.name, uid))
        #add the images in the page to the list of images used in the book
        for i in page.images:
            self.images[i] = page.title
        #add the page to the list of all pages in the book
        self.allpages.append({
            "title": page.title, "id": uid, "authors": page.authors,
            "url": page.url})
        if page.url is not None:
            Epub.allpages_global.append(page.url)

        def add_to_toc(node, page, uid):
            if node is None:
                node = self.toc.xpath("/*/*[3]")[0]
            navpoint = etree.SubElement(node, "navPoint", id=uid, playOrder=
                                        str(len(self.allpages)))
            navlabel = etree.SubElement(navpoint, "navLabel")
            etree.SubElement(navlabel, "text").text = page.title
            etree.SubElement(navpoint, "content", src="{}.xhtml".format(uid))
            return navpoint
        new_node = add_to_toc(node, page, uid)
        [self.add_page(i, new_node) for i in page.list_children()]

    def save(self, filename):
        self.toc.write(
            "{}/toc.ncx".format(self.dir.name), xml_declaration=True,
            encoding="utf-8", pretty_print=True)
        #building the spine
        spine = self.templates["content"]
        self.allpages.sort(key=lambda k: k["id"])
        spine.xpath("/*/*[1]/*[1]")[0].text = arrow.utcnow().format(
            "YYYY-MM-DDTHH:mm:ss")
        spine.xpath("/*/*[1]/dc:title", namespaces={
            "dc": "http://purl.org/dc/elements/1.1/"})[0].text = self.title
        for i, k in enumerate(self.allpages):
            uid = "page_{:0>4}".format(i)
            etree.SubElement(spine.xpath("/*/*[2]")[0], "item", **{
                "media-type": "application/xhtml+xml", "href":
                k["id"] + ".xhtml", "id": uid})
            etree.SubElement(spine.xpath("/*/*[3]")[0], "itemref",
                             idref=uid)
        os.mkdir("{}/images/".format(self.dir.name))
        imagedir = "{}images/".format(datadir)
        if not os.path.exists(imagedir):
            os.mkdir(imagedir)
        for i in self.images:
            path = "_".join([i.split("/")[-2], i.split("/")[-1]])
            if not os.path.isfile(imagedir + path):
                print("downloading image: {}".format(i))
                with open(imagedir + path, "wb") as F:
                    shutil.copyfileobj(requests.get(i, stream=True).raw, F)
            shutil.copy(imagedir + path, "{}/images/".format(self.dir.name))
        spine.write(self.dir.name + "/content.opf", xml_declaration=True,
                    encoding="utf-8", pretty_print=True)
        #other necessary files
        container = self.templates["container"]
        os.mkdir(self.dir.name + "/META-INF/")
        container.write(self.dir.name + "/META-INF/container.xml",
                        xml_declaration=True, encoding="utf-8",
                        pretty_print=True)
        with open(self.dir.name + "/mimetype", "w") as F:
            F.write("application/epub+zip")
        shutil.copy("stylesheet.css", self.dir.name)
        shutil.copy("cover.png", self.dir.name)
        shutil.make_archive(filename, "zip", self.dir.name)
        shutil.move(filename + ".zip", filename + ".epub")

###############################################################################
# Page Retrieval Functions
###############################################################################


def get_skips():
    tagged_as_scp = Page.sn.tag("scp")
    mainlist = [i for i in tagged_as_scp if re.search("scp-[0-9]*$", i)]
    skips = natsort.natsorted(mainlist, signed=False)
    scp_blocks = defaultdict(list)
    for url in skips:
        num = int(url.split("-")[-1])
        block = num // 100      # should range from 0 to 29
        scp_blocks[block].append(url)
    for block in (scp_blocks[i] for i in range(10, 30)):
        first = block[0].split("-")[-1]
        last = block[-1].split("-")[-1]
        block_name = "SCP Database/Articles {}-{}".format(first, last)
        for url in block:
            p = Page(url)
            p.chapter = block_name
            yield p


def get_extra_categories():
    baseurl = "http://www.scp-wiki.net/proposals-for-scp-001"
    proposals_hub = Page(baseurl)
    categories = {
        "SCP Database/001 Proposals": proposals_hub.links(),
        "SCP Database/Explained Phenomena": Page.sn.tag("explained"),
        "SCP Database/Joke Articles": Page.sn.tag("joke")}
    for k, v in categories.items():
        for url in v:
            p = Page(url)
            p.chapter = k
            yield p


def get_hubs():
    hubhubs = ["http://www.scp-wiki.net/canon-hub",
               "http://www.scp-wiki.net/goi-contest-2014",
               "http://www.scp-wiki.net/acidverse"]
    nested_hubs = [i.url for k in hubhubs for i in Page(k).children()]
    hubs = [i for i in Page.sn.tag("hub") if i in Page.sn.tag("tale")
            or i in Page.sn.tag("goi2014")]
    for url in hubs:
        if url not in nested_hubs:
            p = Page(url)
            p.chapter = "Canons and Series"
            yield p


def get_tales():
    for url in Page.sn.tag("tale"):
        p = Page(url)
        p.chapter = "Assorted Tales"
        yield p


def get_all_in_order():
    #yield from get_skips()
    #yield from get_extra_categories()
    #yield from get_hubs()
    #yield from get_tales()
    pass

###############################################################################


def add_attributions(book):
    attrib = Page()
    attrib.title = "Acknowledgments and Attributions"
    attrib.data = "<div class='attrib'>"
    for i in sorted(book.allpages, key=lambda k: k["id"]):
        def add_one(attrib, title, url, authors):
            attrib.data += \
                "<p><b>{}</b> ({}) was written by <b>{}</b>".format(
                    title, url, " ".join(
                        k for k, v in authors.items() if v == "original"))
            for au in (k for k, v in authors.items() if v == "rewrite"):
                attrib.data += ", rewritten by <b>{}</b>".format(au)
            attrib.data += ".</p>"
        if i["url"] is None:
            continue
        add_one(attrib, i["title"], i["url"], i["authors"])
    for i in book.images:
        if scp_crawler.images[i] != "PUBLIC DOMAIN":
            attrib.data += (
                "<p>The image {}_{}, which appears on the page <b>{}</b>, "
                "is a CC image available at <u>{}</u>.</p>".format(
                    i.split("/")[-2], i.split("/")[-1], book.images[i],
                    scp_crawler.images[i]))
    attrib.data += "</div>"
    book.add_page(attrib)


def make_new_book(title):
    book = Epub(title)
    static_pages = []
    for xf in [i for i in sorted(os.listdir(os.getcwd() + "/pages"))]:
        p = Page()
        p.title = xf[3:-6]
        with open(os.path.join(os.getcwd() + "/pages", xf)) as F:
            p.data = F.read()
        static_pages.append(p)
    #map(book.add_page, static_pages)
    [book.add_page(k) for k in static_pages]
    book.chapters = []
    return book


def goes_in_book(previous_book, page):
    #return previous_book.title

    def increment_title(old_title):
        n = old_title[-1:]
        n = str(int(n) + 1)
        return old_title[:-1] + n
    if ("scp" in page.tags and
            page.chapter.split("/")[-1] in previous_book.chapters):
        return previous_book.title
    elif ((page.chapter == "Canons and Series" or
           page.chapter == "Assorted Tales") and
          page.chapter not in previous_book.chapters):
            return increment_title(previous_book.title)
    elif len(previous_book.allpages) < 500:
            return previous_book.title
    else:
            return increment_title(previous_book.title)


def node_with_text(book, text):
    if text is None:
        return None
    return book.toc.xpath('.//navPoint[child::navLabel[child::text[text()='
                          '"{}"]]]'.format(text))[0]


def pick_and_add(books, page):
    pass


def main():
    books = []
    for page in get_all_in_order():
        pick_and_add(books, page)
        # book_name = goes_in_book(book, i)
        # if book.title != book_name:
        #     add_attributions(book)
        #     book.save("/home/anqxyr/heap/_ebook/" + book.title)
        #     book = make_new_book(book_name)
        # previous_chapter = None
        # for c in i.chapter.split("/"):
        #     if not c in [i["title"] for i in book.allpages]:
        #         print(c)
        #         p = scp_crawler.Page()
        #         p.title = c
        #         p.data = "<div class='title2'>{}</div>".format(c)
        #         book.add_page(p, node_with_text(book, previous_chapter))
        #         book.chapters.append(c)
        #     previous_chapter = c
        # book.add_page(i, node_with_text(book, previous_chapter))
    for book in books:
        add_attributions(book)
        book.save(os.path.join(SAVEPATH, book.title))
    print("done")


main()
