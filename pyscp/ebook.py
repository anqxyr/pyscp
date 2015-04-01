#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import itertools
import logging
import zipfile
import uuid

from bs4 import BeautifulSoup as bs4
from collections import namedtuple
from functools import lru_cache, wraps
from lxml import etree, html
from pathlib import Path
from pkgutil import get_data
from pyscp import SnapshotConnector, use_default_logging
from shutil import copy2
from tempfile import TemporaryDirectory

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('pyscp.ebook')

###############################################################################
# Decorators
###############################################################################


def listify(fn=None, wrapper=list):
    def listify_return(fn):
        @wraps(fn)
        def listify_helper(*args, **kw):
            return wrapper(fn(*args, **kw))
        return listify_helper
    if fn is None:
        return listify_return
    return listify_return(fn)

###############################################################################
# Primary Classes
###############################################################################


class ETreeWrapper:

    def __init__(self, *args, namespaces, **kwargs):
        self.tree = etree.ElementTree(*args, **kwargs)
        self.namespaces = namespaces

    def __call__(self, tag='*', **kwargs):
        path = './/{}'.format(tag)
        for key, value in kwargs.items():
            path += '[@{}="{}"]'.format(key, value)
        return self.tree.find(path, namespaces=self.namespaces)

    def __getattr__(self, name):
        return getattr(self.tree, name)

    def write(self, path):
        self.tree.write(str(path), xml_declaration=True,
                        encoding='UTF-8', pretty_print=True)


class Epub:

    item = namedtuple('EbookItem', 'uid title children')

    def __init__(self, **kwargs):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name).resolve()
        (self.path / 'pages').mkdir()
        (self.path / 'images').mkdir()
        self.title = kwargs.get('title', 'Untitled')
        self.language = kwargs.get('language', 'en')
        self.root = []
        self.uid = ('{:04}'.format(i) for i in itertools.count(1))

    def _template(self, name):
        return ETreeWrapper(
            etree.fromstring(
                get_data('pyscp', 'resources/templates/' + name),
                etree.XMLParser(remove_blank_text=True)),
            namespaces=dict(
                opf='http://www.idpf.org/2007/opf',
                dc='http://purl.org/dc/elements/1.1/',
                xhtml='http://www.w3.org/1999/xhtml',
                ncx='http://www.daisy.org/z3986/2005/ncx/'))

    def _write_page(self, uid, title, content):
        page = self._template('page.xhtml')
        page('xhtml:title').text = title
        try:
            page('xhtml:body').append(html.fromstring(content))
        except:
            print(content)
            exit()
        page.write(self.path / 'pages' / (uid + '.xhtml'))

    def add_page(self, title, content, parent=None):
        log.info('Writing page to disk: {}'.format(title))
        item = self.item(next(self.uid), title, [])
        if not parent:
            self.root.append(item)
        else:
            parent.children.append(item)
        self._write_page(item.uid, title, content)
        return item

    def add_image(self, filename, data):
        with open(str(self.path / filename), 'wb') as file:
            file.write(data)

    def _flatten(self, tree):
        for item in tree:
            yield item
            yield from self._flatten(item.children)

    def _write_spine(self):
        spine = self._template('content.opf')
        spine(property='dcterms:modified').text = (
            arrow.utcnow().format('YYYY-MM-DDTHH:mm:ss'))
        spine('dc:title').text = self.title
        spine(id='uuid_id').text = str(uuid.uuid4())
        spine('dc:language').text = self.language
        for item in self._flatten(self.root):
            etree.SubElement(
                spine('opf:manifest'),
                'item',
                href='pages/{}.xhtml'.format(item.uid),
                id=item.uid,
                **{'media-type': 'application/xhtml+xml'})
            etree.SubElement(spine('opf:spine'), 'itemref', idref=item.uid)
        spine.write(self.path / 'content.opf')

    def _write_container(self):
        container = self._template('container.xml')
        meta_inf = self.path / 'META-INF'
        meta_inf.mkdir()
        container.write(meta_inf / 'container.xml')

    def _add_item_to_toc(self, item, node):
        navpoint = etree.SubElement(
            node,
            'navPoint',
            id=item.uid,
            playOrder=item.uid.lstrip('0'))
        navlabel = etree.SubElement(navpoint, 'navLabel')
        etree.SubElement(navlabel, 'text').text = item.title
        etree.SubElement(
            navpoint,
            'content',
            src='pages/{}.xhtml'.format(item.uid))
        for child in item.children:
            self._add_item_to_toc(child, navpoint)

    def _write_toc(self):
        toc = self._template('toc.ncx')
        toc('ncx:text').text = self.title
        for item in self.root:
            self._add_item_to_toc(item, toc('ncx:navMap'))
        toc.write(self.path / 'toc.ncx')

    def write(self, filename):
        self._write_spine()
        self._write_container()
        self._write_toc()
        with open(str(self.path / 'mimetype'), 'w') as file:
            file.write('application/epub+zip')
        copy2(self.stylesheet, str(self.path / 'stylesheet.css'))
        copy2(self.cover, str(self.path / 'cover.png'))
        with zipfile.ZipFile(filename, 'w') as archive:
            archive.write(
                str(self.path / 'mimetype'),
                'mimetype',
                compress_type=zipfile.ZIP_STORED)
            for file in self.path.rglob('*.*'):
                archive.write(
                    str(file),
                    str(file.relative_to(self.path)),
                    compress_type=zipfile.ZIP_DEFLATED)


class EbookBuilder:

    item = namedtuple('EbookItem', 'uid url title content children')

    def __init__(self, cn, urlheap, title):
        self.cn = cn
        self.urlheap = urlheap
        self.book = Epub(title=title)
        resources = Path(__file__).parent / 'resources'
        self.book.stylesheet = str(resources / 'stylesheet.css')
        self.book.cover = str(resources / 'cover.png')
        self.root = []
        self.uid = ('{:04}'.format(i) for i in itertools.count(1))

    def add_page(self, url=None, title=None, content=None, parent=None):
        if url:
            log.info('Queueing url: {}'.format(url))
            if url not in self.urlheap:
                return
            self.urlheap.remove(url)
        item = self.item(next(self.uid), url, title, content, [])
        if not parent:
            self.root.append(item)
        else:
            parent.children.append(item)
        if url:
            for child in self.get_page_children(url):
                self.add_page(url=child, parent=item)
        return item

    def add_cover_page(self):
        self.add_page(title='Cover Page', content=get_data(
            'pyscp', 'resources/pages/cover.xhtml').decode('UTF-8'))

    def add_intro(self):
        self.add_page(title='Introduction', content=get_data(
            'pyscp', 'resources/pages/intro.xhtml').decode('UTF-8'))

    def add_license(self):
        content = bs4(get_data(
            'pyscp', 'resources/pages/license.xhtml').decode('UTF-8'))
        content.find(class_='footer').string = arrow.now().format('YYYY-MM-DD')
        self.add_page(title='License', content=content.div.prettify())

    def add_title_page(self):
        self.add_page(title='Title Page', content=get_data(
            'pyscp', 'resources/pages/title.xhtml').decode('UTF-8'))

    def add_acknowledgments(self):
        pass

    @lru_cache()
    @listify
    def _tag(self, *tags):
        for tag in tags:
            yield from self.cn.list_pages(tag=tag)

    def _get_children_if_skip(self, url):
        for url in self.cn(url).links:
            if url in self._tag('supplement', 'splash'):
                yield url

    def _get_children_if_hub(self, url):
        maybe_children = []
        confirmed_children = []
        for suburl in self.cn(url).links:
            if suburl & self._tag('tale', 'goi-format', 'goi2014'):
                maybe_children.append(suburl)
            if url in self.cn(suburl).links:
                confirmed_children.append(suburl)
            else:
                crumb = bs4(self.cn(suburl).html).select('#breadcrumbs a')
                if crumb:
                    parent = self.cn.site + crumb[-1]['href']
                if url == parent:
                    confirmed_children.append(suburl)
        if confirmed_children:
            return confirmed_children
        else:
            return maybe_children

    def get_page_children(self, url):
        if url in self._tag('scp', 'splash'):
            children = self._get_children_if_skip(url)
        elif url in self._tag('hub') and url in self._tag('tale', 'goi2014'):
            children = self._get_children_if_hub(url)
        else:
            children = []
        if url.endswith('scp-2998'):
            return ['{}-{}'.format(url, n) for n in range(2, 11)]
        elif url.endswith('wills-and-ways-hub'):
            return [i for i in children
                    if not i.endswith('marshall-carter-and-dark-hub')]
        elif url.endswith('serpent-s-hand-hub'):
            return [i for i in children
                    if not i.endswith('black-queen-hub')]
        elif url.endswith('chicago-spirit-hub'):
            return []
        return children

    def _write_item(self, item, parent=None):
        if item.url:
            p = self.cn(item.url)
            html, images = self.parser(p.html)
            new_parent = self.book.add_page(p.title, html, parent)
            for i in self.cn.images():
                if i['url'] in images:
                    self.book.add_image(
                        'images/{}_{}'.format(*i['url'].split('/')[-2:]),
                        data=i['data'])
        else:
            new_parent = self.book.add_page(item.title, item.content, parent)
        for child in item.children:
            self._write_item(child, new_parent)

    def write(self, filename):
        images = [(i['url'], i['status']) for i in self.cn.images()]
        images = [u for u, s in images if s in ('BY-SA CC', 'PUBLIC DOMAIN')]
        link_map = {}
        attrib = {}
        for i in (i for i in self.book._flatten(self.root) if i.url):
            link_map['/' + i.url.split('/')[-1]] = '{}.xhtml'.format(i.uid)
            attrib[i.uid] = self.cn(i.url).author
        self.parser = HtmlParser(link_map, images)
        for item in self.root:
            self._write_item(item)
        self.book.write(filename)


class HtmlParser:

    def __init__(self, link_map, allowed_images):
        self.link_map = link_map
        self.allowed_images = allowed_images

    def _tabviews(self, soup):
        for element in soup(class_='yui-navset'):
            element.attrs = {'class': 'tabview'}
            titles = [i.text for i in element.find(class_='yui-nav')('em')]
            element.find(class_='yui-nav').decompose()
            element.div.unwrap()
            for index, tab in enumerate(element('div', recursive=False)):
                tab.attrs = {'class': 'tabview-tab'}
                title = bs4().new_tag('p', **{'class': 'tab-title'})
                title.string = titles[index]
                tab.insert(0, title)

    def _collapsibles(self, soup):
        for element in soup(class_='collapsible-block'):
            element.attrs = {'class': 'collapsible'}
            title = bs4().new_tag('p', **{'class': 'collapsible-title'})
            title.string = element.find(class_='collapsible-block-link').text
            body = element.find(class_='collapsible-block-content')
            element.clear()
            element.append(title)
            for child in list(body.contents):
                element.append(child)

    def _footnotes(self, soup):
        for element in soup('sup', class_='footnoteref'):
            element.string = element.a.string
        for element in soup(class_='footnote-footer'):
            element.attrs = {'class': 'footnote'}
            element.string = ''.join(element.stripped_strings)

    def _links(self, soup):
        for element in soup('a'):
            if 'href' not in element.attrs:
                continue
            if element['href'] not in self.link_map:
                element.name = 'span'
                element.attrs = {'class': 'link'}
            else:
                element['href'] = self.link_map[element['href']]

    def _quotes(self, soup):
        for element in soup('blockquote'):
            element.name = 'div'
            element.attrs = {'class': 'quote'}

    def _images(self, soup):
        for element in soup('img'):
            if element.name is None or 'src' not in element.attrs:
                continue
            src = element['src']
            if src not in self.allowed_images:
                for parent in element.parents:
                    old_style = bool(
                        parent.select('table tr td img') and
                        len(parent.select('table tr td')) == 1)
                    new_style = bool(
                        'class' in parent.attrs and
                        'scp-image-block' in parent['class'])
                    if old_style or new_style:
                        parent.decompose()
                        break
                else:
                    element.decompose()
            else:
                yield src
                element['src'] = '../images/{}_{}'.format(*src.split('/')[-2:])

    def __call__(self, html):
        soup = bs4(html).find(id='page-content')
        for element in soup(class_='page-rate-widget-box'):
            element.decompose()
        self._tabviews(soup)
        self._collapsibles(soup)
        self._footnotes(soup)
        self._links(soup)
        self._quotes(soup)
        images = list(self._images(soup))
        return soup.prettify(), images


###############################################################################
# Page Retrieval Functions
###############################################################################


def main():
    cn = SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-03-16.db')
    book = EbookBuilder(cn, list(cn.list_pages()), title='Testity')
    book.add_cover_page()
    book.add_intro()
    book.add_license()
    book.add_title_page()
    for index, url in enumerate(cn.list_pages(tag='scp')):
        book.add_page(url)
    book.write('test.epub')


if __name__ == "__main__":
    use_default_logging()
    main()
