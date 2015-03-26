#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import itertools
import logging
import shutil

from bs4 import BeautifulSoup as bs4
from collections import namedtuple
from lxml import etree, html
from pkgutil import get_data
from pyscp import SnapshotConnector, use_default_logging
from tempfile import TemporaryDirectory
from pathlib import Path

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('pyscp.ebook')

###############################################################################
# Primary Classes
###############################################################################


class Epub:

    item = namedtuple('EbookItem', 'uid title children')

    def __init__(self, title):
        self.dir = TemporaryDirectory()
        self.title = title
        self.lang = 'en'
        self.root = []
        self.uid = ('{:04}'.format(i) for i in itertools.count(1))

    def _template(self, name):
        name_to_file = dict(page='page.xhtml', spine='content.opf',
                            container='container.xml', toc='toc.ncx')
        return etree.ElementTree(etree.fromstring(
            get_data('pyscp', 'resources/templates/' + name_to_file[name])))

    def _write_to_disk(self, uid, title, content):
        page = self._template('page')
        page.xpath("/*/*[1]/*[1]")[0].text = title
        page.xpath("/*/*[2]")[0].append(html.fromstring(content))
        page.write("{}/{}.xhtml".format(self.dir.name, uid))

    def add_page(self, title, content, parent=None):
        item = self.item(next(self.uid), title, [])
        if not parent:
            self.root.append(item)
        else:
            parent.children.append(item)
        self._write_to_disk(item.uid, title, content)
        return item

    def _flat_tree(self, tree, flat=[]):
        for item in tree:
            flat.append(item.uid)
            self._flat_tree(item.children)
        return flat

    def _write_spine(self):
        spine = self._template('spine')
        spine.xpath("/*/*[1]/*[1]")[0].text = arrow.utcnow().format(
            "YYYY-MM-DDTHH:mm:ss")
        spine.xpath("/*/*[1]/dc:title", namespaces={
            "dc": "http://purl.org/dc/elements/1.1/"})[0].text = self.title
        for index, uid in enumerate(self._flat_tree(self.root)):
            index = '{:04}'.format(index)
            etree.SubElement(spine.xpath("/*/*[2]")[0], "item", **{
                "media-type": "application/xhtml+xml",
                "href": uid + ".xhtml",
                "id": index})
            etree.SubElement(
                spine.xpath("/*/*[3]")[0],
                "itemref", idref=index)
        spine.write(self.dir.name + "/content.opf", xml_declaration=True,
                    encoding="utf-8", pretty_print=True)

    def _write_container(self):
        container = self._template('container')
        meta_inf = Path(self.dir.name).resolve() / 'META-INF'
        meta_inf.mkdir()
        container.write(str(meta_inf / 'container.xml'),
                        xml_declaration=True, encoding="utf-8",
                        pretty_print=True)

    def _add_item_to_toc(self, item, node=None):
        if node is None:
            node = self.toc.xpath("/*/*[3]")[0]
        navpoint = etree.SubElement(node, "navPoint", id=item.uid,
                                    playOrder=str(int(item.uid)))
        navlabel = etree.SubElement(navpoint, "navLabel")
        etree.SubElement(navlabel, "text").text = item.title
        etree.SubElement(navpoint, "content", src="{}.xhtml".format(item.uid))
        for child in item.children:
            self._add_item_to_toc(child, navpoint)

    def _write_toc(self):
        self.toc = self._template('toc')
        self.toc.xpath("/*/*[2]/*")[0].text = self.title
        for item in self.root:
            self._add_item_to_toc(item)
        self.toc.write(
            "{}/toc.ncx".format(self.dir.name), xml_declaration=True,
            encoding="utf-8", pretty_print=True)

    def write(self, filename):
        self._write_spine()
        self._write_container()
        self._write_toc()
        with open(self.dir.name + "/mimetype", "w") as file:
            file.write("application/epub+zip")
        with open(self.dir.name + '/stylesheet.css', 'wb') as file:
            file.write(get_data('pyscp', 'resources/stylesheet.css'))
        with open(self.dir.name + '/cover.png', 'wb') as file:
            file.write(get_data('pyscp', 'resources/cover.png'))
        shutil.make_archive(filename, "zip", self.dir.name)
        shutil.move(filename + ".zip", filename + ".epub")


class HtmlParser:

    def __init__(self, html):
        self.soup = bs4(html).find(id='page-content')

    def _tabviews(self):
        for element in self.soup(class_='yui-navset'):
            element.attrs = {'class': 'tabview'}
            titles = [i.text for i in element.find(class_='yui-nav')('em')]
            element.find(class_='yui-nav').decompose()
            element.div.unwrap()
            for index, tab in enumerate(element('div', recursive=False)):
                tab.attrs = {'class': 'tabview-tab'}
                title = bs4('').new_tag('p', **{'class': 'tab-title'})
                title.string = titles[index]
                tab.insert(0, title)

    def _collapsibles(self):
        for element in self.soup(class_='collapsible-block'):
            element.attrs = {'class': 'collapsible'}
            title = bs4().new_tag('p', **{'class': 'collapsible-title'})
            title.string = element.find(class_='collapsible-block-link').text
            body = element.find(class_='collapsible-block-content')
            element.clear()
            element.append(title)
            for child in list(body.contents):
                element.append(child)

    def _footnotes(self):
        for element in self.soup('sup', class_='footnoteref'):
            element.string = element.a.string
        for element in self.soup(class_='footnote-footer'):
            element.attrs = {'class': 'footnote'}
            element.string = ''.join(element.stripped_strings)

    def _links(self):
        for element in self.soup('a'):
            element.name = 'span'
            element.attrs = {'class': 'link'}

    def _quotes(self):
        for element in self.soup('blockquote'):
            element.name = 'div'
            element.attrs = {'class': 'quote'}

    def parse(self):
        for element in self.soup(class_='page-rate-widget-box'):
            element.decompose()
        self._tabviews()
        self._collapsibles()
        self._footnotes()
        self._links()
        self._quotes()
        return str(self.soup)


###############################################################################
# Page Retrieval Functions
###############################################################################


def main():
    cn = SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-03-16.db')
    book = Epub('Testity')
    previous = None
    for url, index in zip(cn.list_pages(), range(50)):
        p = cn(url)
        if index % 5 == 0:
            previous = book.add_page(p.title, p.html)
        else:
            book.add_page(p.title, p.html, parent=previous)
    book.write('test')


if __name__ == "__main__":
    use_default_logging()
    main()
