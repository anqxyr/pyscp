#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################


import arrow
import copy
import logging
import natsort
import os
import re
import shutil
import tempfile

from bs4 import BeautifulSoup
from cached_property import cached_property
from collections import defaultdict, namedtuple, OrderedDict
from crawler import Page, Snapshot, enable_logging
from lxml import etree, html

###############################################################################
# Global Constants And Variables
###############################################################################

SAVEPATH = '/home/anqxyr/heap/_scp/ebook/'
STATICDATA = os.path.dirname(os.path.abspath(__file__))
# pick from 'COMPLETE', 'TOMES', and 'DIGEST'
BOOKTYPE = 'DIGEST'
DIGESTMONTH = '2015-01'

logger = logging.getLogger('scp.ebook')
logger.setLevel(logging.DEBUG)

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
        if (page.url in self.allpages_global or
            page.parsed_html is None or
            (page.rating is not None and page.rating < 0) or
            (page.title.startswith('Author Tales')
                or page.title.startswith('Tales by Year'))):
            return
        logger.info('Adding page: {}'.format(page.url))
        epub_page = copy.deepcopy(self.templates["page"])
        #XPath expressions are pre-generated with etree.getpath
        #I have no clue how they work
        epub_page.xpath("/*/*[1]/*[1]")[0].text = page.title
        epub_page.xpath("/*/*[2]")[0].append(html.fromstring(page.parsed_html))
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
        for i in page.children:
            p = BookPage(i)
            p.chapters = page.chapters
            self.add_page(p, node=new_node)

    def add_to_toc(self, node, page, uid):
        navpoint = etree.SubElement(node, "navPoint", id=uid,
                                    playOrder=str(len(self.pageinfo)))
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
            with open(os.path.join(imagedir, path), "wb") as F:
                F.write(BookPage.sn.get_image_metadata(i)['data'])
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


class BookPage(Page):

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url=None):
        super().__init__(url)
        self.images = []

    ###########################################################################
    # Internal Parsing Methods
    ###########################################################################

    @staticmethod
    def _parse_tabviews(html):
        soup = BeautifulSoup(str(html))
        for i in html.select('div.yui-navset'):
            wraper = soup.new_tag('div', **{'class': 'tabview'})
            titles = [a.text for a in i.select('ul.yui-nav em')]
            tabs = i.select('div.yui-content > div')
            for k in tabs:
                k.attrs = {'class': 'tabview-tab'}
                tab_title = soup.new_tag('div', **{'class': 'tab-title'})
                tab_title.string = titles[tabs.index(k)]
                k.insert(0, tab_title)
                wraper.append(k)
            i.replace_with(wraper)
        return html

    @staticmethod
    def _parse_collapsibles(html):
        soup = BeautifulSoup(str(html))
        for i in html.select('div.collapsible-block'):
            link_text = i.select('a.collapsible-block-link')[0].text
            content = i.select('div.collapsible-block-content')[0]
            if not content.text:
                content = i.select('div.collapsible-block-unfolded')[0]
                del(content['style'])
                content.select('div.collapsible-block-content')[0].decompose()
                content.select(
                    'div.collapsible-block-unfolded-link')[0].decompose()
            content['class'] = 'collaps-content'
            col = soup.new_tag('div', **{'class': 'collapsible'})
            content = content.wrap(col)
            col_title = soup.new_tag('div', **{'class': 'collaps-title'})
            col_title.string = link_text
            content.div.insert_before(col_title)
            i.replace_with(content)
        return html

    @staticmethod
    def _parse_footnotes(html):
        for i in html.select('sup.footnoteref'):
            i.string = i.a.string
        for i in html.select('sup.footnote-footer'):
            i['class'] = 'footnote'
            del(i['id'])
            i.string = ''.join(i.strings)
        return html

    @staticmethod
    def _parse_links(html):
        for i in html.select('a'):
            del(i['href'])
            i.name = 'span'
            i['class'] = 'link'
        return html

    @staticmethod
    def _parse_quotes(html):
        for i in html.select('blockquote'):
            i.name = 'div'
            i['class'] = 'quote'
        return html

    def _parse_images(self, html):
        for i in html.select('img'):
            if i.name is None or 'src' not in i.attrs:
                continue
            img_meta = self.sn.get_image_metadata(i['src'])
            if img_meta is None:
                #loop through the image's parents, until we find what to cut
                for p in i.parents:
                    # old-style image formatting:
                    old_style = bool(
                        p.select('table tr td img') and
                        len(p.select('table tr td')) == 1)
                    new_style = bool(
                        'class' in p.attrs and
                        'scp-image-block' in p['class'])
                    if old_style or new_style:
                        p.decompose()
                        break
                else:
                    # if we couldn't find any parents to remove,
                    # just remove the image itself
                    i.decompose()
            else:
                self.images.append(i['src'])
                page, image_url = i['src'].split('/')[-2:]
                i['src'] = 'images/{}_{}'.format(page, image_url)
        return html

    ###########################################################################
    # Public Properties
    ###########################################################################

    @cached_property
    def children(self):
        if self.url is None:
            return []
        if self.url.endswith('scp-2998'):
            return ['{}-{}'.format(self.url, n) for n in range(2, 11)]
        if self.url.endswith('wills-and-ways-hub'):
            return [i for i in super().children
                    if not i.endswith('marshall-carter-and-dark-hub')]
        if self.url.endswith('serpent-s-hand-hub'):
            return [i for i in super().children
                    if not i.endswith('black-queen-hub')]
        if self.url.endswith('chicago-spirit-hub'):
            return []
        return super().children

    @cached_property
    def parsed_html(self):
        logger.debug('Parsing page html: {}'.format(self.url))
        soup = BeautifulSoup(self.html)
        content = soup.select('#page-content')
        if not content:
            return None
        parsed = content[0]
        [i.decompose() for i in parsed.select('div.page-rate-widget-box')]
        parsed = self._parse_tabviews(parsed)
        parsed = self._parse_collapsibles(parsed)
        parsed = self._parse_footnotes(parsed)
        parsed = self._parse_links(parsed)
        parsed = self._parse_quotes(parsed)
        parsed = self._parse_images(parsed)
        if 'scp' in self.tags:
            title_wrap = '<p class="scp-title">{}</p>\n{}'
        else:
            title_wrap = '<p class="tale-title">{}</p>\n{}'
        parsed = title_wrap.format(self.title, parsed)
        return parsed

###############################################################################
# Page Retrieval Functions
###############################################################################


def get_skips():
    tagged = BookPage.sn.get_tag('scp')
    mainlist = [i for i in tagged if re.search("scp-[0-9]*$", i)]
    skips = natsort.natsorted(mainlist, signed=False)
    scp_blocks = defaultdict(list)
    for url in skips:
        num = int(url.split('-')[-1])
        block = num // 100      # should range from 0 to 29
        scp_blocks[block].append(url)
    for block in (scp_blocks[i] for i in range(30)):
        first = block[0].split('-')[-1]
        last = block[-1].split('-')[-1]
        block_name = 'SCP Database/Articles {}-{}'.format(first, last)
        for url in block:
            p = BookPage(url)
            p.chapters = block_name.split('/')
            yield p


def get_extra_categories():
    baseurl = 'http://www.scp-wiki.net/scp-001'
    proposals_hub = BookPage(baseurl)
    categories = (
        ("SCP Database/001 Proposals", proposals_hub.links),
        ("SCP Database/Explained Phenomena", BookPage.sn.get_tag("explained")),
        ("SCP Database/Joke Articles", BookPage.sn.get_tag("joke")))
    for k, v in categories:
        for url in v:
            p = BookPage(url)
            p.chapters = k.split('/')
            yield p


def get_hubs():
    hubhubs = ["http://www.scp-wiki.net/canon-hub",
               "http://www.scp-wiki.net/goi-contest-2014",
               "http://www.scp-wiki.net/acidverse"]
    nested_hubs = [i for k in hubhubs for i in BookPage(k).children]
    hubs = [i for i in BookPage.sn.get_tag("hub")
            if i in BookPage.sn.get_tag("tale")
            or i in BookPage.sn.get_tag("goi2014")]
    for url in hubs:
        if url not in nested_hubs:
            p = BookPage(url)
            p.chapters = ['Canons and Series']
            yield p


def get_tales():
    for url in BookPage.sn.get_tag("tale"):
        try:
            p = BookPage(url)
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
    atrb_main = BookPage()
    atrb_main.title = 'Acknowledgments and Attributions'
    atrb_main.parsed_html = ("<div class='title2'>"
                             "Acknowledgments and Attributions</div>")
    book.add_page(atrb_main)
    atrb_pages = OrderedDict()
    for i in sorted(book.pageinfo, key=lambda k: k.id):
        if i.url is None or not i.authors:
            continue
        atrb = '<p><b>{}</b> ({}) was written by <b>{}</b>'
        atrb = atrb.format(i.title, i.url, i.authors[0].user)
        if i.chapter not in atrb_pages:
            atrb_pages[i.chapter] = "<div class='attrib'>"
        atrb_pages[i.chapter] += atrb
        for au in (j.user for j in i.authors if j.status == 'rewrite'):
            atrb_pages[i.chapter] += ', rewritten by <b>{}</b>'.format(au)
        atrb_pages[i.chapter] += '.</p>'
    if book.images:
        atrb_pages['Images'] = "<div class='attrib'>"
    for i in book.images:
        source = BookPage.sn.get_image_metadata(i)['source']
        if source != 'PUBLIC DOMAIN':
            atrb = ('<p>The image {}_{}, which appears on the page <b>{}</b>, '
                    'is a CC image available at <u>{}</u>.</p>')
            atrb = atrb.format(i.split("/")[-2], i.split("/")[-1],
                               book.images[i], source)
            atrb_pages['Images'] += atrb
    for k, v in atrb_pages.items():
        v += "</div>"
        p = BookPage()
        p.title = k
        p.parsed_html = v
        book.add_page(p, parent='Acknowledgments and Attributions')


def new_book(title):
    book = Epub(title)
    pagedir = os.path.join(STATICDATA, 'pages')
    for filename in sorted(os.listdir(pagedir)):
        p = BookPage()
        p.title = filename[3:-6]
        with open(os.path.join(pagedir, filename)) as F:
            p.parsed_html = F.read()
        book.add_page(p)
    book.chapters = []   # ?
    return book


def check_chapters(book, chapters):
    """Check if the chapters exist in the book, and create if necessary"""
    for n, chap in enumerate(chapters):
        if chap not in (i.title for i in book.pageinfo):
            p = BookPage()
            p.title = chap
            p.parsed_html = "<div class='title2'>{}</div>".format(chap)
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

###############################################################################


def main():
    BookPage.sn = Snapshot('scp-wiki.2015-02-01.db')
    books = []
    for n, page in enumerate(get_all_in_order()):
        pick_and_add(books, page)
    for book in books:
        add_attributions(book)
        book.save(os.path.join(SAVEPATH, book.title))
    logger.info('Finished.')


if __name__ == "__main__":
    enable_logging(logger)
    main()
