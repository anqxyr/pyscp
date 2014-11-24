#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import peewee
import re

from bs4 import BeautifulSoup
from crawler import *

###############################################################################
# Global Constants
###############################################################################

DBPATH = "/home/anqxyr/heap/_scp/images.db"
WIKI = WikidotConnector('http://www.scp-wiki.net')

###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(DBPATH)


class BaseModel(peewee.Model):

    class Meta:
        database = db


class Image(BaseModel):
    image_url = peewee.CharField(unique=True)
    page_url = peewee.CharField()
    page_source = peewee.TextField()
    is_new_style = peewee.BooleanField(null=True)
    is_misc = peewee.BooleanField(null=True)
    is_offsite = peewee.BooleanField(null=True)


db.connect()
db.create_tables([Image], safe=True)

###############################################################################
# Images DB Functions
###############################################################################


def fill_db():
    Image.delete().execute()
    count = PageData.select().count()
    for n in range(1, count // 50 + 2):
        query = PageData.select().order_by(PageData.url).paginate(n, 50)
        for i in query:
            add_page_info_to_db(i.url, i.html)


def add_page_info_to_db(url, html):
    soup = BeautifulSoup(html).select('#page-content')
    if soup:
        soup = soup[0]
    else:
        return
    if not soup.select('img'):
        return
    print(url)
    pageid = WIKI.pageid(html)
    source = WIKI.source(pageid)
    for i in soup.select('img'):
        if not 'src' in i.attrs:
            print(i)
            continue
        if i['src'].startswith('http://www.wikidot.com/avatar.php?userid='):
            continue
        for par in i.parents:
            if 'class' in par.attrs and 'scp-image-block' in par['class']:
                new_style = True
                break
        else:
            new_style = False
        if i['src'].startswith('http://scp-wiki.wdfiles.com/local--files/'):
            offsite = False
        else:
            offsite = True
        print(i['src'])
        try:
            Image.create(
                image_url=i['src'],
                page_url=url,
                page_source=source,
                is_new_style=new_style,
                is_offsite=offsite)
        except:
            pass

###############################################################################
# Format Conversion Functions
###############################################################################


def convert_image_formatting(url):
    #html = WIKI.html(url)
    #pageid = WIKI.pageid(html)
    #source = WIKI.source(pageid)
    source = Image.get(Image.page_url == url).page_source
    new_source = convert_source(source)
    return new_source

FLAG = False


def convert_source(source):
    if not FLAG:
        print(source)
    r = (r'\[\[div style="float:right; margin:0 2em 1em 2em;'
         ' width:([0-9]+)px; border:0;"\]\]\n'
         '\|\|\|\| \[\[image ([\w./_:%-]+?) width="([0-9]+)px"\]\] \|\|\n'
         '\|\|\|\|~\s*([\w^█ \':,/.-]+?)\s*\|?\|\|\n'
         '\[\[/div\]\]')
    old_style = re.compile(r, re.MULTILINE | re.DOTALL)
    image = old_style.search(source)
    if not FLAG:
        print(image)
        if image is not None:
            print(image.group(0))
            print(image.groups())
    if image is None:
        return False
    size1, im_url, size2, caption = image.groups()
    caption = caption.strip('^')
    if size1 != size2:
        print('Size mismatch')
        return False
    if size1 == '300':
        size = ''
    else:
        size = '|width={}px'.format(size1)
    repl = '[[include component:image-block name={}|caption={}{}]]'
    repl = repl.format(im_url, caption, size)
    new_source = old_style.sub(repl, source)
    return new_source


###############################################################################


def main():
    #fill_db()
    if FLAG:
        urls = []
        t = 0
        f = 0
        for i in Image.select().where(Image.is_new_style == False):
            if i.page_url not in urls:
                urls.append(i.page_url)
        for i in urls:
            if not convert_image_formatting(i):
                print(i)
                f += 1
            else:
                t += 1
        print(t, f)
    else:
        convert_image_formatting('http://www.scp-wiki.net/scp-956')


if __name__ == "__main__":
    main()
