#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import peewee

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
    page_source = peewee.BlobField()
    is_new_style = peewee.BooleanField(null=True)
    is_misc = peewee.BooleanField(null=True)
    is_offsite = peewee.BooleanField(null=True)


db.connect()
db.create_tables([Image], safe=True)
Image.delete().execute()

###############################################################################


def fill_db():
    count = PageData.select().count()
    for n in range(1, count // 50 + 2):
        query = PageData.select().order_by(PageData.url).paginate(n, 50)
        for i in query:
            process_page(i.url, i.html)


def process_page(url, html):
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
        if Image.select().where(Image.image_url == i['src']):
            continue
        par = i.parent
        if 'class' in par.attrs and 'scp-image-block' in par['class']:
            new_style = True
        else:
            new_style = False
        if i['src'].startswith('http://scp-wiki.wdfiles.com/local--files/'):
            offsite = False
        else:
            offsite = True
        Image.create(
            image_url=i['src'],
            page_url=url,
            page_source=source,
            is_new_style=new_style,
            is_offsite=offsite)

###############################################################################


def main():
    fill_db()


if __name__ == "__main__":
    main()
