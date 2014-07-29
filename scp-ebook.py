#!/usr/bin/env python3

from ebooklib import epub
from urllib.request import urlopen
from urllib.error import HTTPError
from bs4 import BeautifulSoup
from lxml import etree
import re
import os


class Page():

    """placeholder docstring"""

    #titles for scp articles
    scp_index = {}

    def __init__(self, url=None):
        self.url = url
        self.children = []
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
        return

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

    def get_children(self):
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

        def add_as_children(with_tags):
            for p in lpages:
                if any(i in p.tags for i in with_tags):
                    self.children.append(p)
                    p.get_children()
            return

        if not any(i in self.tags for i in ["scp", "hub", "splash"]):
            return
        lpages = []
        for url in links(self):
            p = Page(url)
            if p.soup and p.data:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            add_as_children(["supplement", "splash"])
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            add_as_children(["tale", "goi-format"])
            children_with_backlinks = []
            for p in self.children:
                if self.url in links(p):
                    children_with_backlinks.append(p)
                else:
                    soup = BeautifulSoup(p.soup)
                    if soup.select("#breadcrumbs a"):
                        crumb = soup.select("#breadcrumbs a")[-1]
                        crumb = "http://www.scp-wiki.net" + crumb["href"]
                        if self.url == crumb:
                            children_with_backlinks.append(p)
            if children_with_backlinks != []:
                self.children = children_with_backlinks
        return


class Epub():

    """Create a epub using generators and temp files for optimal memory use."""

    def __init__(self, title, stylesheet):
        book = epub.EpubBook()
        book.set_title(title)
        style = epub.EpubItem(uid="stylesheet",
                              file_name="style/stylesheet.css",
                              media_type="text/css", content=stylesheet)
        book.add_item(style)
        self.book = book
        self.style = style
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
        doc_title_text.text = "SCP Foundation"
        etree.SubElement(root, "navMap")
        self.toc = root

    def add_page(self, page, node=None):
        n = len(self.book.items) - 1
        uid = "page_" + str(n).zfill(4)
        epub_page = epub.EpubHtml(page.title, uid + ".xhtml")
        epub_page.title = page.title
        epub_page.content = page.data
        epub_page.add_item(self.style)
        self.book.add_item(epub_page)
        self.book.spine.append(epub_page)

        def add_to_toc(node, page, uid):
            if not node:
                node = self.toc.find("navMap")
            navpoint = etree.SubElement(node, "navPoint",
                                        id=uid,
                                        playOrder=uid[-4:].lstrip("0"))
            navlabel = etree.SubElement(navpoint, "navLabel")
            etree.SubElement(navlabel, "text").text = page.title
            etree.SubElement(navpoint, "content", src=uid + ".xhtml")
            return navpoint
        new_node = add_to_toc(node, page, uid)
        page.get_children()
        for i in page.children:
            self.add_page(i, new_node)

    def save(self, file):
        tree = etree.ElementTree(self.toc)
        toc_xml = etree.tostring(tree, xml_declaration=True, encoding="utf-8",
                                 pretty_print=True).decode()
        toc = epub.EpubItem(uid="toc", file_name="toc.ncx",
                            media_type="application/x-dtbncx+xml",
                            content=toc_xml)
        self.book.add_item(toc)
        epub.write_epub(file, self.book, {})


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
    for b in scp_blocks:
        break
        b_name = "Chapter " + str(scp_blocks.index(b)).zfill(2)
        for url in b:
            p = Page(url)
            p.chapter = b_name
            yield p

    def quick_yield(tag, chapter_name):
        for url in urls_by_tag(tag):
            p = Page(url)
            p.chapter = chapter_name
            yield p
    # for p in quick_yield("joke", "Joke Articles"):
    #     yield p
    # for p in quick_yield("explained", "Explained Phenomena"):
    #     yield p
    #collecting canon and tale series hubs
    tale_list = urls_by_tag("tale")
    tale_list.extend(urls_by_tag("goi2014"))
    k = 0
    for url in urls_by_tag("hub"):
        k += 1
        if k == 10:
            break
        if not url in tale_list:
            continue
        p = Page(url)
        p.chapter = "Canons and Series"
        yield p
    #collecting standalone tales
    # for p in quick_yield("tale", "Assorted Tales"):
    #     yield p


def main():
    book = Epub("SCP Foundation", "")
    for i in yield_pages():
        print(i.title)
        book.add_page(i)
    book.save("test.epub")

main()
