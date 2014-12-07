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

from collections import defaultdict, namedtuple, OrderedDict
from lxml import etree, html
from crawler import Page

###############################################################################
# Global Constants
###############################################################################

SAVEPATH = '/home/anqxyr/heap/_scp/ebook/'
STATICDATA = os.path.dirname(os.path.abspath(__file__))
# pick from 'COMPLETE', 'TOMES', and 'DIGEST'
BOOKTYPE = 'DIGEST'
DIGESTMONTH = '2014-11'

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
        self.pageinfo = []
        #pre-building toc
        self.toc = self.templates["toc"]
        self.toc.xpath("/*/*[2]/*")[0].text = title
        self.images = {}

    def add_page(self, page, parent=None, node=None):
        #each page can only appear once in the book
        duplicate = page.url in Epub.allpages_global
        empty = page.data is None
        negative = page.rating is not None and int(page.rating) < 0
        if duplicate or empty or negative:
            return
        epub_page = copy.deepcopy(self.templates["page"])
        #XPath expressions are pre-generated with etree.getpath
        #I have no clue how they work
        epub_page.xpath("/*/*[1]/*[1]")[0].text = page.title
        epub_page.xpath("/*/*[2]")[0].append(html.fromstring(page.data))
        #write the page on disk
        uid = "page_{:0>4}".format(len(self.pageinfo))
        epub_page.write("{}/{}.xhtml".format(self.dir.name, uid))
        #add the images in the page to the list of images used in the book
        for i in page.images:
            self.images[i] = page.title
        #add the page to the list of all pages in the book
        pi = namedtuple('PageInfo', 'url title id authors chapter')
        try:
            chap = page.chapters[0]
        except:
            chap = None
        if chap in ['SCP Database', 'Assorted Tales']:
            chap = page.chapters[1]
        self.pageinfo.append(pi(page.url,
                                page.title,
                                uid,
                                page.authors,
                                chap))
        if page.url is not None:
            self.allpages_global.append(page.url)
        if parent is None and node is None:
            node = self.toc.xpath("/*/*[3]")[0]
        elif node is None:
            node = self.toc.xpath(
                './/navPoint[child::navLabel[child::text[text()="{}"]]]'
                .format(parent))[0]
        new_node = self.add_to_toc(node, page, uid)
        for i in page.children():
            self.add_page(i, node=new_node)

    def add_to_toc(self, node, page, uid):
        navpoint = etree.SubElement(node, "navPoint", id=uid, playOrder=
                                    str(len(self.pageinfo)))
        navlabel = etree.SubElement(navpoint, "navLabel")
        etree.SubElement(navlabel, "text").text = page.title
        etree.SubElement(navpoint, "content", src="{}.xhtml".format(uid))
        return navpoint

    def save(self, filename):
        self.toc.write(
            "{}/toc.ncx".format(self.dir.name), xml_declaration=True,
            encoding="utf-8", pretty_print=True)
        #building the spine
        spine = self.templates["content"]
        self.pageinfo.sort(key=lambda k: k.id)
        spine.xpath("/*/*[1]/*[1]")[0].text = arrow.utcnow().format(
            "YYYY-MM-DDTHH:mm:ss")
        spine.xpath("/*/*[1]/dc:title", namespaces={
            "dc": "http://purl.org/dc/elements/1.1/"})[0].text = self.title
        for i, k in enumerate(self.pageinfo):
            uid = "page_{:0>4}".format(i)
            etree.SubElement(spine.xpath("/*/*[2]")[0], "item", **{
                "media-type": "application/xhtml+xml", "href":
                k.id + ".xhtml", "id": uid})
            etree.SubElement(spine.xpath("/*/*[3]")[0], "itemref",
                             idref=uid)
        imagedir = os.path.join(self.dir.name, 'images')
        os.mkdir(imagedir)
        for i in self.images:
            path = "_".join([i.split("/")[-2], i.split("/")[-1]])
            print("downloading image: {}".format(i))
            with open(os.path.join(imagedir, path), "wb") as F:
                F.write(Page.sn.images()[i].data)
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


class EbookPage(Page):

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url=None):
        self.url = url
        self.data = None
        self.rating = None
        self.images = []
        self.history = []
        self.authors = []
        self.votes = []

        if url is not None:
            pd = self.sn.pagedata(url)
            self._parse_html(pd.html)
            self._raw_html = pd.html
            if pd.history is not None:
                self._parse_history(pd.history)
                self.authors = self._meta_authors()
            if pd.votes is not None:
                self._parse_votes(pd.votes)
        self._override()


    ###########################################################################
    # Misc. Methods
    ###########################################################################

    def _override(self):
        _inrange = lambda x: [Page("{}-{}".format(self.url, n)) for n in x]
        _except = lambda x: [p for p in self.children()
                             if p.url != "http://www.scp-wiki.net/" + x]
        ov_data = [("scp-1047-j", None)]
        ov_children = [
            ("scp-2998", _inrange, range(2, 11)),
            ("wills-and-ways-hub", _except, "marshall-carter-and-dark-hub"),
            ("serpent-s-hand-hub", _except, "black-queen-hub"),
            ("chicago-spirit-hub", list, "")]
        for partial_url, data in ov_data:
            if self.url == "http://www.scp-wiki.net/" + partial_url:
                self.data = data
        for partial_url, func, args in ov_children:
            if self.url == "http://www.scp-wiki.net/" + partial_url:
                new_children = func(args)
                self.children = lambda: new_children

    ###########################################################################
    # Parsing Methods
    ###########################################################################

    def _parse_html(self, raw_html):
        '''Retrieve title, data, and tags'''
        soup = BeautifulSoup(raw_html)
        rating_el = soup.select("#pagerate-button span")
        if rating_el:
            self.rating = rating_el[0].text
        try:
            comments = soup.select('#discuss-button')[0].text
            comments = re.search('[0-9]+', comments).group()
            self.comments = comments
        except:
            self.comments = 0
        self._parse_body(soup)
        self.tags = [a.string for a in soup.select("div.page-tags a")]
        self._parse_title(soup)
        if "scp" in self.tags:
            title_insert = "<p class='scp-title'>{}</p>{}"
        else:
            title_insert = "<p class='tale-title'>{}</p>{}"
        self.data = title_insert.format(self.title, self.data)

    def _parse_history(self, raw_history):
        soup = BeautifulSoup(raw_history)
        history = []
        Revision = namedtuple('Revision', 'number user time comment')
        for i in soup.select('tr')[1:]:
            rev_data = i.select('td')
            number = int(rev_data[0].text.strip('.'))
            user = rev_data[4].text
            time = arrow.get(rev_data[5].text, 'DD MMM YYYY HH:mm')
            time = time.format('YYYY-MM-DD HH:mm:ss')
            comment = rev_data[6].text
            history.append(Revision(number, user, time, comment))
        self.history = list(reversed(history))

    def _parse_votes(self, raw_votes):
        soup = BeautifulSoup(raw_votes)
        votes = []
        VoteData = namedtuple('VoteData', 'user vote')
        for i in soup.select('span.printuser'):
            user = i.text
            vote = i.next_sibling.next_sibling.text.strip()
            votes.append(VoteData(user, vote))
        self.votes = votes

    def _parse_body(self, soup):
        if not soup.select("#page-content"):
            self.data = None
            return
        data = soup.select("#page-content")[0]
        for i in data.select("div.page-rate-widget-box"):
            i.decompose()
        data = self._parse_tabviews(data)
        data = self._parse_collapsibles(data)
        data = self._parse_footnotes(data)
        data = self._parse_links(data)
        data = self._parse_quotes(data)
        data = self._parse_images(data)
        self.data = str(data)

    def _parse_title(self, soup):
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        if "scp" in self.tags and re.search("[scp]+-[0-9]+$", self.url):
            title = "{}: {}".format(title, self.sn.title(self.url))
        self.title = title

    def _parse_images(self, data):
        images = self.sn.images()
        for i in data.select('img'):
            if i.name is None or not i.has_attr('src'):
                continue
            if i["src"] not in images:
                #loop through the image's parents, until we find what to cut
                for p in i.parents:
                    # old-style image formatting:
                    old_style = bool(p.select("table tr td img") and
                                     len(p.select("table tr td")) == 1)
                    new_style = bool("class" in p.attrs and
                                     "scp-image-block" in p["class"])
                    if old_style or new_style:
                        p.decompose()
                        break
                else:
                    # if we couldn't find any parents to remove,
                    # just remove the image itself
                    i.decompose()
            else:
                    self.images.append(i["src"])
                    page, image_url = i["src"].split("/")[-2:]
                    i["src"] = "images/{}_{}".format(page, image_url)
        return data

    def _parse_tabviews(self, data):
        soup = BeautifulSoup(str(data))
        for i in data.select("div.yui-navset"):
            wraper = soup.new_tag("div", **{"class": "tabview"})
            titles = [a.text for a in i.select("ul.yui-nav em")]
            tabs = i.select("div.yui-content > div")
            for k in tabs:
                k.attrs = {"class": "tabview-tab"}
                tab_title = soup.new_tag("div", **{"class": "tab-title"})
                tab_title.string = titles[tabs.index(k)]
                k.insert(0, tab_title)
                wraper.append(k)
            i.replace_with(wraper)
        return data

    def _parse_collapsibles(self, data):
        soup = BeautifulSoup(str(data))
        for i in data.select("div.collapsible-block"):
            link_text = i.select("a.collapsible-block-link")[0].text
            content = i.select("div.collapsible-block-content")[0]
            if content.text == "":
                content = i.select("div.collapsible-block-unfolded")[0]
                del(content["style"])
                content.select("div.collapsible-block-content")[0].decompose()
                content.select("div.collapsible-block-unfolded-link"
                               )[0].decompose()
            content["class"] = "collaps-content"
            col = soup.new_tag("div", **{"class": "collapsible"})
            content = content.wrap(col)
            col_title = soup.new_tag("div", **{"class": "collaps-title"})
            col_title.string = link_text
            content.div.insert_before(col_title)
            i.replace_with(content)
        return data

    def _parse_links(self, data):
        for i in data.select("a"):
            del(i["href"])
            i.name = "span"
            i["class"] = "link"
        return data

    def _parse_quotes(self, data):
        for i in data.select("blockquote"):
            i.name = "div"
            i["class"] = "quote"
        return data

    def _parse_footnotes(self, data):
        for i in data.select("sup.footnoteref"):
            i.string = i.a.string
        for i in data.select("sup.footnote-footer"):
            i["class"] = "footnote"
            del(i["id"])
            i.string = "".join([k for k in i.strings])
        return data

    def _meta_authors(self):
        au = namedtuple('author', 'username status')
        his_author = self.history[0].user
        rewrite = self.sn.rewrite(self.url)
        if rewrite:
            if rewrite.override:
                return [au(rewrite.author, 'original')]
            else:
                return [au(his_author, 'original'),
                        au(rewrite.author, 'rewrite')]
        else:
            return [au(his_author, 'original')]

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
    for block in (scp_blocks[i] for i in range(30)):
        first = block[0].split("-")[-1]
        last = block[-1].split("-")[-1]
        block_name = 'SCP Database/Articles {}-{}'.format(first, last)
        for url in block:
            p = Page(url)
            p.chapters = block_name.split('/')
            yield p


def get_extra_categories():
    baseurl = 'http://www.scp-wiki.net/scp-001'
    proposals_hub = Page(baseurl)
    categories = (
        ("SCP Database/001 Proposals", proposals_hub.links()),
        ("SCP Database/Explained Phenomena", Page.sn.tag("explained")),
        ("SCP Database/Joke Articles", Page.sn.tag("joke")))
    for k, v in categories:
        for url in v:
            p = Page(url)
            p.chapters = k.split('/')
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
            p.chapters = ['Canons and Series']
            yield p


def get_tales():
    for url in Page.sn.tag("tale"):
        try:
            p = Page(url)
        except:
            continue
        first_letter = [i for i in p.title.upper()
                        if re.match('[0-9A-Z]', i)][0]
        groups = ['0-9', 'A-D', 'E-H', 'I-L', 'M-P', 'Q-T', 'U-Z']
        for i in groups:
            if re.match('[{}]'.format(i), first_letter):
                p.chapters = ['Assorted Tales', 'Tales {}'.format(i)]
                yield p
                break


def get_all_in_order():
    yield from get_skips()
    yield from get_extra_categories()
    yield from get_hubs()
    yield from get_tales()
    pass

###############################################################################


def add_attributions(book):
    atrb_main = Page()
    atrb_main.title = 'Acknowledgments and Attributions'
    atrb_main.data = ("<div class='title2'>"
                      "Acknowledgments and Attributions</div>")
    book.add_page(atrb_main)
    atrb_pages = OrderedDict()
    for i in sorted(book.pageinfo, key=lambda k: k.id):
        if i.url is None or not i.authors:
            continue
        atrb = '<p><b>{}</b> ({}) was written by <b>{}</b>'
        atrb = atrb.format(i.title, i.url, i.authors[0].username)
        if not i.chapter in atrb_pages:
            atrb_pages[i.chapter] = "<div class='attrib'>"
        atrb_pages[i.chapter] += atrb
        for au in (j.username for j in i.authors if j.status == 'rewrite'):
            atrb_pages[i.chapter] += ', rewritten by <b>{}</b>'.format(au)
        atrb_pages[i.chapter] += '.</p>'
    images = Page.sn.images()
    if book.images:
        atrb_pages['Images'] = "<div class='attrib'>"
    for i in book.images:
        source = images[i].source
        if source != 'PUBLIC DOMAIN':
            atrb = ('<p>The image {}_{}, which appears on the page <b>{}</b>, '
                    'is a CC image available at <u>{}</u>.</p>')
            atrb = atrb.format(i.split("/")[-2], i.split("/")[-1],
                               book.images[i], source)
            atrb_pages['Images'] += atrb
    for k, v in atrb_pages.items():
        v += "</div>"
        p = Page()
        p.title = k
        p.data = v
        book.add_page(p, parent='Acknowledgments and Attributions')


def new_book(title):
    book = Epub(title)
    pagedir = os.path.join(STATICDATA, 'pages')
    for filename in sorted(os.listdir(pagedir)):
        p = Page()
        p.title = filename[3:-6]
        with open(os.path.join(pagedir, filename)) as F:
            p.data = F.read()
        book.add_page(p)
    book.chapters = []   # ?
    return book


def check_chapters(book, chapters):
    """Check if the chapters exist in the book, and create if necessary"""
    for n, chap in enumerate(chapters):
        if not chap in (i.title for i in book.pageinfo):
            print(chap)
            p = Page()
            p.title = chap
            p.data = "<div class='title2'>{}</div>".format(chap)
            if n > 0:
                book.add_page(p, parent=chapters[n - 1])
            else:
                book.add_page(p)
            book.chapters.append(chap)


def pick_and_add(books, page):
    if BOOKTYPE == 'COMPLETE':
        add_complete(books, page)
    elif BOOKTYPE == 'DIGEST':
        add_digest(books, page)
    elif BOOKTYPE == 'TOMES':
        add_tomes(books, page)
    else:
        raise Exception('Unsupported book type.')


def add_complete(books, page):
    if not books:
        title = 'SCP Foundation: The Complete Collection'
        books.append(new_book(title))
    last_book = books[-1]
    check_chapters(last_book, page.chapters)
    last_book.add_page(page, parent=page.chapters[-1])


def add_digest(books, page):
    digest_date = arrow.get(DIGESTMONTH, 'YYYY-MM')
    try:
        page_date = arrow.get(page.history[0].time)
    except:
        return
    if (page_date.year != digest_date.year or
            page_date.month != digest_date.month):
        return
    if not books:
        title = 'SCP Foundation Monthly Digest: {}'
        title = title.format(digest_date.format('MMMM YYYY'))
        books.append(new_book(title))
    last_book = books[-1]
    check_chapters(last_book, page.chapters)
    last_book.add_page(page, parent=page.chapters[-1])


def add_tomes(books, page):
    if not books:
        title = 'SCP Foundation: Tome 1'
        books.append(new_book(title))
    last_book = books[-1]
    chap = page.chapters[-1]
    scp = 'scp' in page.tags and chap in last_book.chapters
    tale = chap.startswith('Tales') and chap in last_book.chapters
    too_short = len(last_book.pageinfo) < 500
    switch = (page.chapters[0] in ['Canons and Series', 'Assorted Tales'] and
              page.chapters[0] not in last_book.chapters)
    if scp or tale or (too_short and not switch):
        cur_book = last_book
    else:
        new_title = 'SCP Foundation: Tome {}'.format(len(books) + 1)
        cur_book = new_book(new_title)
        books.append(cur_book)
    check_chapters(cur_book, page.chapters)
    cur_book.add_page(page, parent=page.chapters[-1])


def main():
    books = []
    for n, page in enumerate(get_all_in_order()):
        # if n > 10:
        #     break
        pick_and_add(books, page)
        # book_name = goes_in_book(book, i)
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
