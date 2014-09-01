#!/usr/bin/env python3

from bs4 import BeautifulSoup
from lxml import etree, html
from functools import wraps
import re
import os
import shutil
import copy
import arrow
import requests
from requests.adapters import HTTPAdapter
import tempfile


datadir = os.path.expanduser("~/.scp-data/")
req = requests.Session()
req.mount("http://www.scp-wiki.net/", HTTPAdapter(max_retries=5))


def cached_to_disk(func):
    """Save the results of the func to the directory specified in datadir."""
    path = datadir + func.__name__
    replace = {"_scrape_body": "data", "_scrape_history": "history"}
    for new_str in (path.replace(k, v) for k, v in replace.items()):
        path = new_str
    if not os.path.exists(path):
        os.makedirs(path)

    @wraps(func)
    def cached_func(page):
        replace = [("http://", ""), ("/", "_"), ("www.", ""), (":", "-")]
        url_norm = page.url
        for new_str in (url_norm.replace(k, v) for k, v in replace):
            url_norm = new_str
        fullpath = "{}/{}".format(path, url_norm)
        if os.path.isfile(fullpath):
            with open(fullpath) as cached_file:
                data = cached_file.read()
        else:
            print("{:<40}{}".format(func.__name__, page.url))
            data = func(page)
            if data is not None:
                with open(fullpath, "w") as cached_file:
                    cached_file.write(data)
        return data
    return cached_func


def wikidot_module(name, page, perpage, pageid):
    """Retrieve data from the specified wikidot module."""
    headers = {"Content-Type": "application/x-www-form-urlencoded;",
               "Cookie": "wikidot_token7=123456;"}
    payload = {"page": page, "perpage": perpage, "page_id": pageid,
               "moduleName": name, "wikidot_token7": "123456"}
    payload = "&".join("=".join((k, str(v))) for k, v in payload.items())
    data = req.post("http://www.scp-wiki.net/ajax-module-connector.php",
                    data=payload, headers=headers).json()["body"]
    return data


def _page_init_titles():
        """Return a dict of SCP articles' titles"""
        index_urls = ["http://www.scp-wiki.net/scp-series",
                      "http://www.scp-wiki.net/scp-series-2",
                      "http://www.scp-wiki.net/scp-series-3"]
        titles = {}
        for url in index_urls:
            soup = BeautifulSoup(req.get(url).text)
            articles = [i for i in soup.select("ul > li")
                        if re.search("(SCP|SPC)-[0-9]+", i.text)]
            for e in articles:
                k, v = e.text.split(" - ", maxsplit=1)
                titles[k] = v
        return titles


class Page():

    """Scrape and store contents and metadata of a page."""

    images = {}
    authors = {}
    titles = _page_init_titles()

    def __init__(self, url=None):
        self.url = url
        self.data = None
        self.title = None
        self.tags = []
        self.images = []
        self.history = None
        self.soup = None
        if url is not None:
            self.soup = self._scrape_body()
            if self.soup is not None:
                self.data, self.title, self.tags = self._cook()
                self.history = self._scrape_history()
                if self.history is not None:
                    self.authors = self._pick_authors()
        self._override()

    @cached_to_disk
    def _scrape_body(self):
        """Scrape the contents of the page."""
        data = req.get(self.url)
        if data.status_code != 404:
            return data.text

    @cached_to_disk
    def _scrape_history(self):
        """Scrape page's history."""
        pageid = re.search("pageId = ([^;]*);", self.soup)
        if pageid is None:
            return None
        return wikidot_module(name="history/PageRevisionListModule",
                              page=1, perpage=1000, pageid=pageid.group(1))

    def _override(self):
        _inrange = lambda x: [Page("{}-{}".format(self.url, n)) for n in x]
        _except = lambda x: [p for p in self.list_children()
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
                self.list_children = lambda: func(args)

    def _cook(self):
        '''Retrieve title, data, and tags'''
        soup = BeautifulSoup(self.soup)
        # body
        parse_elements = [
            ("div.page-rate-widget-box", lambda x: x.decompose()),
            ("div.yui-navset", self._parse_tabview),
            ("div.collapsible-block", self._parse_collapsible),
            ("blockquote", self._parse_quote),
            ("sup.footnoteref", self._parse_footnote),
            ("sup.footnote-footer", self._parse_footnote_footer),
            ("a", self._parse_link),
            ("img", self._parse_image)]
        if not soup.select("#page-content"):
            data = None
        else:
            data = soup.select("#page-content")[0]
            for element, func in parse_elements:
                for i in data.select(element):
                    func(i)
        # tags
        tags = [a.string for a in soup.select("div.page-tags a")]
        # title
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        if "scp" in tags and re.search("scp-[0-9]+$", self.url):
            title = "{}: {}".format(title,
                                    Page.titles[title.replace("SPC", "SCP")])
        #add title to the page
        if "scp" in tags:
            data = "<p class='scp-title'>{}</p>{}".format(title, data)
        else:
            data = "<p class='tale-title'>{}</p>{}".format(title, data)
        data += "<div class='tags' style='display: none'><hr/><p>{}</p></div>"\
                .format("</p><p>".join(tags))
        return data, title, tags

    def _parse_image(self, element):
        if element.name is None or not element.has_attr("src"):
            return
        if element["src"] not in Page.images:
            #loop through the image's parents, until we find what to cut
            for p in element.parents:
                # old-style image formatting:
                old_style = bool(p.select("table > tr > td > img") and
                                 len(p.select("table > tr > td")) == 1)
                new_style = bool("class" in p.attrs and
                                 "scp-image-block" in p["class"])
                if old_style or new_style:
                    p.decompose()
                    break
            else:
                # if we couldn't find any parents to remove,
                # just remove the image itself
                element.decompose()
        else:
                self.images.append(element["src"])
                page, image_url = element["src"].split("/")[-2:]
                element["src"] = "images/{}_{}".format(page, image_url)

    def _parse_tabview(self, element):
        soup = BeautifulSoup(self.soup)
        wraper = soup.new_tag("div", **{"class": "tabview"})
        titles = [a.text for a in element.select("ul.yui-nav em")]
        tabs = element.select("div.yui-content > div")
        for k in tabs:
            k.attrs = {"class": "tabview-tab"}
            tab_title = soup.new_tag("div", **{"class": "tab-title"})
            tab_title.string = titles[tabs.index(k)]
            k.insert(0, tab_title)
            wraper.append(k)
        element.replace_with(wraper)

    def _parse_collapsible(self, element):
        link_text = element.select("a.collapsible-block-link")[0].text
        try:
            content = element.select("div.collapsible-block-content")[0]
        except:
            print(element.prettify())
            exit()
        if content.text == "":
            content = element.select("div.collapsible-block-unfolded")[0]
            del(content["style"])
            content.select("div.collapsible-block-content")[0].decompose()
            content.select("div.collapsible-block-unfolded-link"
                           )[0].decompose()
        content["class"] = "collaps-content"
        soup = BeautifulSoup(self.soup)
        col = soup.new_tag("div", **{"class": "collapsible"})
        content = content.wrap(col)
        col_title = soup.new_tag("div", **{"class": "collaps-title"})
        col_title.string = link_text
        content.div.insert_before(col_title)
        element.replace_with(content)

    def _parse_link(self, element):
        del(element["href"])
        element.name = "span"
        element["class"] = "link"

    def _parse_quote(self, element):
        element.name = "div"
        element["class"] = "quote"

    def _parse_footnote(self, element):
        element.string = element.a.string

    def _parse_footnote_footer(self, element):
        element["class"] = "footnote"
        del(element["id"])
        element.string = "".join([k for k in element.strings])

    def _pick_authors(self):
        history = BeautifulSoup(self.history)
        author = history.select("tr")[-1].select("td")[-3].text
        if self.url not in Page.authors:
            return {author: "original"}
        new_author = Page.authors[self.url]
        if new_author[:10] == ":override:":
            return {new_author[10:]: "original"}
        else:
            return {author: "original", new_author: "rewrite"}

    def links(self):
        if self.soup is None:
            return []
        links = []
        soup = BeautifulSoup(self.soup)
        for a in soup.select("#page-content a"):
            if not a.has_attr("href") or a["href"][0] != "/":
                continue
            if a["href"][-4:] in [".png", ".jpg", ".gif"]:
                continue
            url = "http://www.scp-wiki.net{}".format(a["href"])
            url = url.rstrip("|")
            if url in links:
                continue
            links.append(url)
        return links

    def list_children(self):
        if not hasattr(self, "tags"):
            return []
        lpages = []
        for url in self.links():
            p = Page(url)
            if p.soup is not None and p.data is not None:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            mpages = [i for i in lpages if
                      any(k in i.tags for k in ["supplement", "splash"])]
            return mpages
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            mpages = [i for i in lpages if any(k in i.tags for k in
                      ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in child.links():
                    return True
                soup = BeautifulSoup(child.soup)
                if soup.select("#breadcrumbs a"):
                    crumb = soup.select("#breadcrumbs a")[-1]
                    crumb = "http://www.scp-wiki.net{}".format(crumb["href"])
                    if self.url == crumb:
                        return True
                return False
            if any(backlinks(self, p) for p in mpages):
                return [p for p in mpages if backlinks(self, p)]
            else:
                return mpages
        return []


class Epub():

    """"""

    allpages_global = []

    def __init__(self, title):
        self.title = title
        #change to a proper temp dir later on
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
        for k in self.allpages:
            etree.SubElement(spine.xpath("/*/*[2]")[0], "item", **{
                "media-type": "application/xhtml+xml", "href":
                k["id"] + ".xhtml", "id": k["title"].replace(":", "-")})
            etree.SubElement(spine.xpath("/*/*[3]")[0], "itemref",
                             idref=k["title"].replace(":", "-"))
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


def yield_pages():
    def urls_by_tag(tag):
        print("downloading tag info: {}".format(tag))
        soup = BeautifulSoup(requests.get("http://www.scp-wiki.net/system:page"
                             "-tags/tag/" + tag).text)
        urls = ["http://www.scp-wiki.net" + a["href"] for a in soup.select(
            "div.pages-list div.pages-list-item div.title a")]
        return urls

    def natural_key(s):
        re_natural = re.compile('[0-9]+|[^0-9]+')
        return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c
                in re_natural.findall(s)] + [s]
    # skips
    url_001 = "http://www.scp-wiki.net/proposals-for-scp-001"
    for i in BeautifulSoup(requests.get(url_001).text
                           ).select("#page-content")[0].select("a"):
        url = "http://www.scp-wiki.net" + i["href"]
        p = Page(url)
        p.chapter = "SCP Database/001 Proposals"
        yield p
    scp_main = [i for i in urls_by_tag("scp") if re.match(".*scp-[0-9]*$", i)]
    scp_main = sorted(scp_main, key=natural_key)
    scp_blocks = [[i for i in scp_main if (int(i.split("-")[-1]) // 100 == n)]
                  for n in range(30)]
    for b in scp_blocks[:5]:
        b_name = "SCP Database/Articles {}-{}".format(b[0].split("-")[-1],
                                                      b[-1].split("-")[-1])
        for url in b:
            p = Page(url)
            p.chapter = b_name
            yield p
    return

    def quick_yield(tags, chapter_name):
        L = [urls_by_tag(i) for i in tags if type(i) == str]
        for i in [i for i in tags if type(i) == list]:
            a = [x for k in i for x in urls_by_tag(k)]
            L.append(a)
        for url in [i for i in L[0] if all(i in t for t in L)]:
            p = Page(url)
            p.chapter = chapter_name
            yield p
    yield from quick_yield(["joke", "scp"], "SCP Database/Joke Articles")
    yield from quick_yield(["explained", "scp"],
                           "SCP Database/Explained Phenomena")
    hubhubs = ["http://www.scp-wiki.net/canon-hub",
               "http://www.scp-wiki.net/goi-contest-2014",
               "http://www.scp-wiki.net/acidverse"]
    nested_hubs = [i.url for k in hubhubs for i in Page(k).list_children()]
    for i in quick_yield(["hub", ["tale", "goi2014"]], "Canons and Series"):
        if i.url not in nested_hubs:
            yield i
    yield from quick_yield(["tale"], "Assorted Tales")


def update(time):
    page = 1
    while True:
        print("downloading recent changes: page {}".format(page))
        soup = BeautifulSoup(wikidot_module(
            name="changes/SiteChangesListModule", page=page, perpage=100,
            pageid=1926945))
        for i in soup.select("div.changes-list-item"):
            rev_time = arrow.get(i.select("span.odate")[0].text,
                                 "DD MMM YYYY HH:mm")
            if rev_time.timestamp > arrow.get(time).timestamp:
                url = i.select("td.title a")[0]["href"]
                cached_file = datadir + url.replace(
                    "http://www.scp-wiki.net/", "").replace(
                    "/", "_").replace(":", "")
                if os.path.exists(cached_file):
                    print("deleting outdated cache: {}".format(cached_file))
                    os.remove(cached_file)
            else:
                return
        page += 1


def main():
    def retrieve_table(url):
        print("downloading tabled data: {}".format(url))
        soup = BeautifulSoup(requests.get(url).text)
        results = {}
        for i in soup.select("tr")[1:]:
            results[i.select("td")[0].text] = i.select("td")[1].text
        return results

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
            if Page.images[i] != "PUBLIC DOMAIN":
                attrib.data += (
                    "<p>The image {}_{}, which appears on the page <b>{}</b>, "
                    "is a CC image available at <u>{}</u>.</p>".format(
                        i.split("/")[-2], i.split("/")[-1], book.images[i],
                        Page.images[i]))
        attrib.data += "</div>"
        book.add_page(attrib)

    def goes_in_book(previous_book, page):
        def increment_title(old_title):
            n = old_title[-2:]
            n = str(int(n) + 1).zfill(2)
            return old_title[:-2] + n
        if ("scp" in page.tags and
                page.chapter.split("/")[-1] in previous_book.chapters):
            return previous_book.title
        elif (page.chapter == "Canons and Series" and
              previous_book.title[-4:-3] == "1"):
                return "SCP Foundation: Tome 2.01"
        elif (page.chapter == "Assorted Tales" and
              previous_book.title[-4:-3] == "2"):
                return "SCP Foundation: Tome 3.01"
        elif len(previous_book.allpages) < 500:
                return previous_book.title
        else:
                return increment_title(previous_book.title)

    def node_with_text(book, text):
        if text is None:
            return None
        return book.toc.xpath('.//navPoint[child::navLabel[child::text[text()='
                              '"{}"]]]'.format(text))[0]
    if os.path.exists("{}_lastcreated".format(datadir)):
        with open("{}_lastcreated".format(datadir)) as F:
            update(F.read())
    with open("{}_lastcreated".format(datadir), "w") as F:
        F.write(arrow.utcnow().format("YYYY-MM-DDTHH:mm:ss"))
    Page.images = retrieve_table(
        "http://scpsandbox2.wikidot.com/ebook-image-whitelist")
    Page.authors = {
        "http://www.scp-wiki.net/" + k: v for k, v in
        retrieve_table("http://05command.wikidot.com/alexandra-rewrite")
        .items()}
    book = make_new_book("SCP Foundation: Tome 1.01")

    for i in yield_pages():
        book_name = goes_in_book(book, i)
        if book.title != book_name:
            add_attributions(book)
            book.save(book.title)
            book = make_new_book(book_name)
        previous_chapter = None
        for c in i.chapter.split("/"):
            if not c in [i["title"] for i in book.allpages]:
                print(c)
                p = Page()
                p.title = c
                p.data = "<div class='title2'>{}</div>".format(c)
                book.add_page(p, node_with_text(book, previous_chapter))
                book.chapters.append(c)
            previous_chapter = c
        book.add_page(i, node_with_text(book, previous_chapter))
    add_attributions(book)
    book.save("/home/anqxyr/heap/_ebook/" + book.title)
    print("done")

main()
