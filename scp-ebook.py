#!/usr/bin/env python3

from urllib.request import urlopen
from urllib.error import HTTPError
from bs4 import BeautifulSoup
from lxml import etree, html
import re
import os
import shutil
import copy


class Page():

    """placeholder docstring"""

    #titles for scp articles
    scp_index = {}

    def __init__(self, url=None):
        self.url = url
        self.tags = []
        if url is not None:
                self.scrape()
                self.cook()
        return

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def scrape(self):
        '''Scrape the contents of the given url.'''
        url_end = re.search("/[^/]*$", self.url).group()[1:]
        if url_end == "":
            self.soup = None
            return
        path = "data/" + url_end
        if os.path.isfile(path):
            with open(path, "r") as F:
                self.soup = (F.read())
        else:
            print("downloading: \t" + self.url)
            try:
                soup = BeautifulSoup(urlopen(self.url))
            except HTTPError:
                self.soup = None
                with open(path, "w") as F:
                    F.write("")
                return
            self.soup = str(soup)
            with open(path, "w") as F:
                F.write(str(soup))

    def cook(self):
        '''Cook the soup, retrieve title, data, and tags'''
        if not self.soup:
            self.title = None
            self.data = None
            return
        self.cook_meta()    # must be cooked first
        self.cook_title()
        self.cook_data()
        return

    def cook_title(self):
        soup = BeautifulSoup(self.soup)
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
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
            title = title + ": " + Page.scp_index["SCP-" + title[4:]]
        self.title = title
        return self

    def cook_data(self):
        soup = BeautifulSoup(self.soup)
        if not soup.select("#page-content"):
            self.data = None
            return self
        data = soup.select("#page-content")[0]
        # remove the rating module
        for i in data.select("div.page-rate-widget-box"):
            i.decompose()
        #remove the image block
        for i in data.select("div.scp-image-block"):
            i.decompose()
        for i in data.select("table"):
            if i.select("img"):
                i.decompose()
        for i in data.select("img"):
            i.decompose()
        # tab-views
        for i in data.select("div.yui-navset"):
            wraper = soup.new_tag("div")
            wraper["class"] = "tabview"
            titles = [a.text for a in i.select("ul.yui-nav em")]
            tabs = i.select("div.yui-content > div")
            for k in tabs:
                k["class"] = "tabview-tab"
                del(k["id"])
                del(k["style"])
                tab_title = soup.new_tag("div")
                tab_title["class"] = "tab-title"
                tab_title.string = titles[tabs.index(k)]
                k.insert(0, tab_title)
                wraper.append(k)
            i.replace_with(wraper)
        # footnotes
        for i in data.select("sup.footnoteref"):
            i.string = i.a.string
        for i in data.select("div.footnote-footer"):
            i["class"] = "footnote"
            del(i["id"])
            i.string = "".join([k for k in i.strings])
        # collapsibles
        for i in data.select("div.collapsible-block"):
            link_text = i.select("a.collapsible-block-link")[0].text
            content = i.select("div.collapsible-block-content")[0]
            content["class"] = "col-content"
            col = soup.new_tag("div")
            col["class"] = "col"
            content = content.wrap(col)
            col_title = soup.new_tag("div")
            col_title["class"] = "col-title"
            col_title.string = link_text
            content.div.insert_before(col_title)
            i.replace_with(content)
        # links
        for i in data.select("a"):
            del(i["href"])
            i.name = "span"
            i["class"] = "link"
        #quote boxes
        for i in data.select("blockquote"):
            i.name = "div"
            i["class"] = "quote"
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
        soup = BeautifulSoup(self.soup)
        tags = [a.string for a in soup.select("div.page-tags a")]
        self.tags = tags
        return self

    def yield_children(self):
        def links(self):
            links = []
            soup = BeautifulSoup(self.soup)
            for a in soup.select("#page-content a"):
                if not a.has_attr("href") or a["href"][0] != "/":
                    if a.has_attr("href"):
                        if (a["href"] != "javascript:;" and a["href"][0] != "#"
                            and re.search("scp-wiki", a["href"])
                                and not re.search("local--files", a["href"])):
                            print("bad link: \t\t" + a["href"] + "\ton page " +
                                  self.url)
                    continue
                url = "http://www.scp-wiki.net" + a["href"]
                url = url.rstrip("|")
                if url in links:
                    continue
                links.append(url)
            return links

        if not any(i in self.tags for i in ["scp", "hub", "splash"]):
            return
        lpages = []
        for url in links(self):
            p = Page(url)
            if p.soup and p.data:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            mpages = [i for i in lpages if
                      any(k in i.tags for k in ["supplement", "splash"])]
            for p in mpages:
                    yield p
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            mpages = [i for i in lpages if any(k in i.tags for k in
                      ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in links(child):
                    return True
                soup = BeautifulSoup(child.soup)
                if soup.select("#breadcrumbs a"):
                    crumb = soup.select("#breadcrumbs a")[-1]
                    crumb = "http://www.scp-wiki.net" + crumb["href"]
                    if self.url == crumb:
                        return True
                return False
            if any(backlinks(self, p) for p in mpages):
                for p in mpages:
                    if backlinks(self, p):
                        yield p
            else:
                for p in mpages:
                        yield p


class Epub():

    """"""

    def __init__(self, title):
        self.title = title
        #change to a proper temp dir later on
        self.dir = os.getcwd() + "/ebook/"
        if os.path.exists(self.dir):
            shutil.rmtree(self.dir)
        os.mkdir(self.dir)
        os.mkdir(self.dir + "META-INF/")
        os.mkdir(self.dir + "EPUB/")
        os.mkdir(self.dir + "EPUB/pages/")
        self.template = etree.parse(os.getcwd() + "/page_template.xhtml")
        self.allpages = []
        #pre-building toc
        root = etree.Element("ncx",
                             xmlns="http://www.daisy.org/z3986/2005/ncx/",
                             version="2005-1")
        head = etree.SubElement(root, "head")
        etree.SubElement(head, "meta", content="", name="dtb:uid")
        etree.SubElement(head, "meta", content="0", name="dtb:depth")
        etree.SubElement(head, "meta", content="0", name="dtb:totalPageCount")
        etree.SubElement(head, "meta", content="0", name="dtb:maxPageNumber")
        doc_title = etree.SubElement(root, "docTitle")
        doc_title_text = etree.SubElement(doc_title, "text")
        doc_title_text.text = title
        etree.SubElement(root, "navMap")
        self.toc = root

    def add_page(self, page, node=None):
        #print(page.title)
        n = len(os.listdir(self.dir + "EPUB/pages/"))
        uid = "page_" + str(n).zfill(4)
        epub_page = copy.deepcopy(self.template)
        root = epub_page.getroot()
        for i in root.iter():
            if i.tag.endswith("title"):
                i.text = page.title
            if i.tag.endswith("body"):
                body = html.fromstring(page.data)
                i.append(body)
        epub_page.write(self.dir + "EPUB/pages/" + uid + ".xhtml")
        self.allpages.append(page.title)

        def add_to_toc(node, page, uid):
            if node is None:
                node = self.toc.find("navMap")
            navpoint = etree.SubElement(node, "navPoint",
                                        id=uid,
                                        playOrder=uid[-4:].lstrip("0"))
            navlabel = etree.SubElement(navpoint, "navLabel")
            etree.SubElement(navlabel, "text").text = page.title
            etree.SubElement(navpoint, "content", src=uid + ".xhtml")
            return navpoint
        new_node = add_to_toc(node, page, uid)
        for i in page.yield_children():
            self.add_page(i, new_node)

    def save(self, file):
        tree = etree.ElementTree(self.toc)
        toc_xml = etree.tostring(tree, xml_declaration=True, encoding="utf-8",
                                 pretty_print=True).decode()

    def add_cover(self, file):
        pass

def yield_pages():
    def urls_by_tag(tag):
        base = "http://www.scp-wiki.net/system:page-tags/tag/" + tag
        soup = BeautifulSoup(urlopen(base))
        urls = ["http://www.scp-wiki.net" + a["href"] for a in
                soup.select("""div.pages-list
                            div.pages-list-item div.title a""")]
        return urls

    def natural_key(s):
        re_natural = re.compile('[0-9]+|[^0-9]+')
        return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c
                in re_natural.findall(s)] + [s]
    # skips
    scp_main = [i for i in urls_by_tag("scp") if re.match(".*scp-[0-9]*$", i)]
    scp_main = sorted(scp_main, key=natural_key)
    scp_blocks = [[i for i in scp_main if (int(i.split("-")[-1]) // 100 == n)]
                  for n in range(30)]
    for b in scp_blocks[:1]:
        b_name = "SCP Database/Chapter " + str(scp_blocks.index(b) + 1)
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
    for p in quick_yield(["joke", "scp"], "SCP Database/Joke Articles"):
        yield p
    for p in quick_yield(["explained", "scp"],
                         "SCP Database/Explained Phenomena"):
        yield p
    #collecting canon and tale series hubs
    for p in quick_yield(["hub", ["tale", "goi2014"]], "Canons and Series"):
        yield p
    #collecting standalone tales
    for p in quick_yield(["tale"], "Assorted Tales"):
        yield p


def main():
    with open("stylesheet.css", "r") as F:
        style = F.read()
    book = Epub("SCP Foundation")
    pages_intro = []
    pages_outro = []
    for f in [f for f in sorted(os.listdir(os.getcwd() + "/pages"))
              if os.path.isfile(os.path.join(os.getcwd() + "/pages", f))]:
                p = Page()
                p.title = f[3:-6]
                with open(os.path.join(os.getcwd() + "/pages", f)) as F:
                    p.data = F.read()
                if f[0] == "0":
                    pages_intro.append(p)
                else:
                    pages_outro.append(p)
    for p in pages_intro:
        book.add_page(p)
    for i in yield_pages():
        c_up = None

        def node_with_text(text):
            for k in book.toc.iter("navPoint"):
                if text == k.find("navLabel").find("text").text:
                    return k
        for c in i.chapter.split("/"):
            if not c in book.allpages:
                print(c)
                p = Page()
                p.title = c
                p.data = "<div></div>"
                book.add_page(p, node_with_text(c_up))
            c_up = c
        print(i.title)
        book.add_page(i, node_with_text(c_up))
    for p in pages_outro:
        book.add_page(p)
    book.save("test.epub")

main()
