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
WIKI = WikidotConnector('http://scp-wiki.wikidot.com')
#WIKI = WikidotConnector('http://scpsandbox2.wikidot.com')

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


def convert_all():
    # by the time this is on githab, I will have changed the password already
    # so don't bother trying
    pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    WIKI.auth(username='anqxyr', password=pasw)
    urls = []
    for i in Image.select().where(Image.is_new_style == False):
        if i.page_url not in urls:
            urls.append(i.page_url)
    n = 0
    for i in urls:
        edited = convert_image_formatting(i)
        if edited:
            n += 1


def convert_image_formatting(url):
    url = url.replace('http://www.scp-wiki.net', 'http://scp-wiki.wikidot.com')
    html = WIKI.html(url)
    pageid = WIKI.pageid(html)
    source = WIKI.source(pageid)
    new_source = convert_source(source, url)
    if source == new_source:
        return False
    title = WIKI.title(html)
    comment = 'updated image formatting'
    try:
        WIKI.edit(pageid, url, new_source, title, comment)
        print('page edited: {}'.format(url))
    except Exception:
        #print(e)
        print('ERROR: Failed to edit the page: {}'.format(url))
    return True


def convert_source(source, url):
    r_div_margin = 'margin:0 2em 1em 2em;'
    r_div_float = 'float:(left|right);'
    r_div_width = 'width:([0-9]+)px;'
    r_div_open = (r'\[\[div style="{} {} {} border:0;"\]\]\n'
                  .format(r_div_float, r_div_margin, r_div_width))
    r_image_width = '(width=)?"([0-9]+)px"?'
    r_image_link = '(link=)?"?([^"]+)?'
    r_image_code = (r'\|+\s*\[\[image ({}) {}{}\s?"?\]\]\s\|+\n'
                    .format('{}', r_image_width, r_image_link))
    r_caption = r'\|+~\s*({})\s*\|+\n'
    r_div_close = r'\[\[/div\]\]'
    r = r_div_open + r_image_code + r_caption + r_div_close
    image = re.compile(r.format(r'[^\s]+', r'[^\n]+?'), re.MULTILINE)
    new_source = source
    for match in image.finditer(source):
        align, size1, im_url, _, size2, _, link, caption = match.groups()
        if link is not None:
            return source
        caption = caption.strip()
        caption = caption.strip('^')
        if size1 != size2:
            print('WARNING: size mismatch: {}'.format(url))
        if size1 == '300':
            size = ''
        else:
            size = '|width={}px'.format(size2)
        if align == 'right':
            component = 'component:image-block'
        elif align == 'left':
            component = 'component:image-block-left'
        repl = '[[include {} name={}|caption={}{}]]\n'
        repl = repl.format(component, im_url, caption, size)
        new_source = re.sub(r.format(im_url, r'[^\n]+?'), repl, new_source)
    return new_source

###############################################################################


def check_formatting_errors():
    pass

###############################################################################


def main():
    #fill_db()
    check_formatting_errors()
    

if __name__ == "__main__":
    main()
