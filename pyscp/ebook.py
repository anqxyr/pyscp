#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import itertools
import logging
import zipfile
import uuid
import re

from bs4 import BeautifulSoup as bs4
from collections import namedtuple
from functools import lru_cache
from lxml import etree, html
from pathlib import Path
from pkgutil import get_data
from pyscp import core, utils
from shutil import copy2
from tempfile import TemporaryDirectory

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('pyscp.ebook')

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
        self.author = kwargs.get('author', '')
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
        now = arrow.utcnow().format('YYYY-MM-DDTHH:mm:ss')
        spine(property='dcterms:modified').text = now
        spine('dc:date').text = now
        spine('dc:title').text = self.title
        spine('dc:creator').text = self.author
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
        image_uid = ('img{:03}'.format(i) for i in itertools.count(1))
        for file in (self.path / 'images').glob('*'):
            if str(file).endswith('.jpg'):
                media_type = 'image/jpeg'
            elif str(file).endswith('.png'):
                media_type = 'image/png'
            else:
                continue
            etree.SubElement(
                spine('opf:manifest'),
                'item',
                href=str(file.relative_to(self.path)),
                id=next(image_uid),
                **{'media-type': media_type})
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
        self.book = Epub(title=title, author='Various Authors')
        resources = Path(__file__).parent / 'resources'
        self.book.stylesheet = str(resources / 'stylesheet.css')
        self.book.cover = str(resources / 'cover.png')
        self.root = []
        self.images = []
        self.uid = ('{:04}'.format(i) for i in itertools.count(1))
        self.image_whitelist = {
            i['url']: (i['status'], i['source'], i['data'])
            for i in self.cn.images()
            if i['status'] in ('BY-SA CC', 'PUBLIC DOMAIN')}

    def add_page(self, url=None, title=None, content=None, parent=None):
        if url:
            log.info('Queueing url: {}'.format(url))
            if url not in self.urlheap:
                return
            self.urlheap.remove(url)
            self.images.extend(
                [i for i in self.cn(url).images if i in self.image_whitelist])
        item = self.item(next(self.uid), url, title, content, [])
        if not parent:
            self.root.append(item)
        else:
            parent.children.append(item)
        if url:
            for child in self.get_page_children(url):
                self.add_page(url=child, parent=item)
        return item

    def add_opening(self):
        titles = 'Cover Page', 'Introduction', 'License', 'Title Page'
        files = 'cover', 'intro', 'license', 'title'
        contents = [
            get_data('pyscp', 'resources/pages/{}.xhtml'.format(i))
            .decode('UTF-8') for i in files]
        license = bs4(contents[2])
        license.find(class_='footer').string = arrow.now().format('YYYY-MM-DD')
        contents[2] = license.div.prettify()
        for title, content in zip(titles, contents):
            self.add_page(title=title, content=content)

    def add_credits(self):
        credits = self.add_chapter('Acknowledgments and Attributions')
        subchapters = []
        items = list(self.book._flatten(self.root))
        items_len = len(items)
        for index, item in enumerate(items):
            log.info(
                'Constructing credits: {}/{}.'.format(index + 1, items_len))
            if item.title and item.children:    # separate book section
                subchapters.append([item.title, ''])
            elif item.url:
                page = self.cn(item.url)
                if (page.author.startswith('Anonymous (') or
                        page.author.startswith('(account deleted)')):
                    continue
                entry = (
                    '<p><b>{}</b> ({}) was written by <b>{}</b>'
                    .format(page.title, page.url, page.author))
                if (len(page.authors) > 1 and
                        page.authors[1].status == 'rewrite'):
                    entry += ', rewritten by <b>{}</b>'.format(
                        page.authors[1].user)
                subchapters[-1][1] += entry + '.</p>'
        if self.images:
            subchapters.append(['Images', ''])
            for image in self.images:
                image_name = '{}_{}'.format(*image.split('/')[-2:])
                entry = (
                    '<p>The image {} is licensed under {} '
                    'and available at <u>{}</u>.</p>'
                    .format(image_name, *self.image_whitelist[image][:2]))
                subchapters[-1][1] += entry
        for title, content in subchapters:
            if not content:
                continue
            content = '<div class="attrib">{}</div>'.format(content)
            self.add_page(title=title, content=content, parent=credits)

    def add_chapter(self, title, parent=None):
        return self.add_page(
            title=title,
            content='<div class="title2">{}</div>'.format(title),
            parent=parent)

    def add_block(self, name, urls, filter_fn=None, parent=None):
        urls = list(filter(filter_fn, urls))
        if set(urls) & set(self.urlheap):
            block = self.add_chapter(name, parent)
            for url in urls:
                self.add_page(url=url, parent=block)

    def add_skips(self, start, end, parent=None):
        for block_num in range(start, end + 1):
            bl_start, bl_end = (block_num - 1) * 100 or 2, block_num * 100 - 1
            self.add_block(
                'Articles {:03}-{:03}'.format(bl_start, bl_end),
                self._tag('scp'),
                utils.ignore()(lambda x: bl_start <= int(
                    re.search(r'[0-9]{3,4}$', x).group()) <= bl_end),
                parent)

    def add_tales(self, start, end, parent=None):
        alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        start, end = start.upper(), end.upper()
        for letter in alphabet[alphabet.index(start):alphabet.index(end) + 1]:
            self.add_block(
                'Tales {}'.format(letter),
                self._tag('tale') - self._tag('hub', 'goi2014'),
                lambda x: x.split('/')[-1][0] == letter.lower(),
                parent)

    def add_hubs(self, start, end, parent=None):
        self.add_block(
            'Cannons and Series', self._tag('hub'),
            lambda x: start.lower() <= x.split('/')[-1][0] <= end.lower(),
            parent)

    def add_extras(self, parent=None):
        for name, urls in zip(
            ('001 Proposals', 'Joke Articles', 'Explained Phenomena'),
            (self.cn('scp-001').links, self._tag('joke'),
                self._tag('explained'))):
            self.add_block(name, urls, parent=parent)

    @lru_cache()
    @utils.listify(set)
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
            if suburl in self._tag('hub'):
                continue
            if suburl in self._tag('tale', 'goi-format', 'goi2014'):
                maybe_children.append(suburl)
            if url in self.cn(suburl).links:
                confirmed_children.append(suburl)
            else:
                subhtml = self.cn(suburl).html
                if not subhtml:
                    continue
                crumb = bs4(subhtml).select('#breadcrumbs a')
                if crumb and url == self.cn.site + crumb[-1]['href']:
                    confirmed_children.append(suburl)
        if confirmed_children:
            return confirmed_children
        else:
            return maybe_children

    @utils.ignore(core.ConnectorError, [])
    def get_page_children(self, url):
        if url in self._tag('scp', 'splash'):
            children = self._get_children_if_skip(url)
        elif (url in self._tag('hub') and
                url in self._tag('tale', 'goi2014') and
                url not in self._tag('_sys')):
            children = self._get_children_if_hub(url)
        else:
            children = []
        if url.endswith('scp-2998'):
            return ['{}-{}'.format(url, n) for n in range(2, 11)]
        return children

    def _write_item(self, item, parent=None):
        if item.url:
            p = self.cn(item.url)
            new_parent = self.book.add_page(
                p.title,
                self.parser(p.html, p.title, p.url in self._tag('scp')),
                parent)
        else:
            new_parent = self.book.add_page(item.title, item.content, parent)
        for child in item.children:
            self._write_item(child, new_parent)

    def write(self, filename):
        link_map = {'/' + i.url.split('/')[-1]: '{}.xhtml'.format(i.uid)
                    for i in self.book._flatten(self.root) if i.url}
        self.parser = HtmlParser(link_map, list(self.image_whitelist.keys()))
        for item in self.root:
            self._write_item(item)
        for image in self.images:
            self.book.add_image(
                'images/{}_{}'.format(*image.split('/')[-2:]),
                data=self.image_whitelist[image][2])
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
                        parent.name == 'table' and
                        parent.select('tr td img') and
                        len(parent.select('tr td')) == 1)
                    new_style = bool(
                        'class' in parent.attrs and
                        'scp-image-block' in parent['class'])
                    if old_style or new_style:
                        parent.decompose()
                        break
                else:
                    element.decompose()
            else:
                element['src'] = '../images/{}_{}'.format(*src.split('/')[-2:])

    def __call__(self, html, title, is_scp):
        soup = bs4(html).find(id='page-content')
        for element in soup(class_='page-rate-widget-box'):
            element.decompose()
        self._tabviews(soup)
        self._collapsibles(soup)
        self._footnotes(soup)
        self._links(soup)
        self._quotes(soup)
        self._images(soup)
        return '<p class="{}-title">{}</p>\n{}'.format(
            'scp' if is_scp else 'tale', title, soup.prettify())


###############################################################################
# Page Retrieval Functions
###############################################################################


def build_complete(cn, output_path):
    book = EbookBuilder(cn, list(cn.list_pages(rating='>0')),
                        title='SCP Foundation: The Complete Collection')
    book.add_opening()
    skips = book.add_chapter('SCP Database')
    book.add_skips(1, 29, skips)
    book.add_extras(skips)
    book.add_hubs('0', 'Z')
    book.add_tales('0', 'Z', book.add_chapter('Assorted Tales'))
    book.add_credits()
    book.write(output_path + book.book.title.replace(':', '') + '.epub')


def build_tomes(cn, output_path):
    heap = list(cn.list_pages(rating='>0'))
    books = [
        EbookBuilder(cn, heap, title='SCP Foundation: Tome {}'.format(i + 1))
        for i in range(12)]
    for book in books:
        book.add_opening()
    for i in range(6):
        books[i].add_skips(i * 5 + 1, i * 5 + 5)
    books[5].add_extras()
    books[6].add_hubs('0', 'L')
    books[7].add_hubs('M', 'Z')
    for index, (start, end) in zip(range(4), ('0D', 'EL', 'MS', 'TZ')):
        books[index + 8].add_tales(start, end)
    for book in books:
        book.add_credits()
        book.write(output_path + book.book.title.replace(':', '') + '.epub')


def build_digest(cn, output_path):
    date = arrow.now().replace(months=-1).format
    book = EbookBuilder(
        cn,
        list(cn.list_pages(rating='>0', created=date('YYYY-MM'))),
        title='SCP Foundation Monthly Digest: {}'.format(date('MMMM YYYY')))
    book.add_opening()
    skips = book.add_chapter('SCP Database')
    book.add_skips(1, 29, skips)
    book.add_extras(skips)
    book.add_hubs('0', 'Z')
    book.add_tales('0', 'Z', book.add_chapter('Assorted Tales'))
    book.add_credits()
    book.write(output_path + book.book.title.replace(':', '') + '.epub')


def main():
    sn = core.SnapshotConnector(
        'www.scp-wiki.net', '/home/anqxyr/heap/_scp/scp-wiki.2015-05-01.db')
    for fn in (build_complete, build_tomes, build_digest):
        fn(sn, '/home/anqxyr/heap/_scp/ebook/')


if __name__ == '__main__':
    core.use_default_logging()
    main()
