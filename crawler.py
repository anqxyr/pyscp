#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import peewee
import re
import requests

from bs4 import BeautifulSoup
from collections import namedtuple

###############################################################################
# Global Constants
###############################################################################

DBPATH = "/home/anqxyr/heap/_scp/scp-wiki.2014-12-01.db"

###############################################################################
# Decorators
###############################################################################


###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(DBPATH)


class BaseModel(peewee.Model):

    class Meta:
        database = db


class DBPage(BaseModel):
    url = peewee.CharField(unique=True)
    html = peewee.TextField()


class DBRevision(BaseModel):
    url = peewee.CharField()
    number = peewee.IntegerField()
    user = peewee.CharField()
    time = peewee.DateTimeField()
    comment = peewee.CharField()


class DBVote(BaseModel):
    url = peewee.CharField()
    user = peewee.CharField()
    vote = peewee.IntegerField()


class DBTitle(BaseModel):
    url = peewee.CharField(unique=True)
    skip = peewee.CharField()
    title = peewee.CharField()


class DBImageInfo(BaseModel):
    image_url = peewee.CharField(unique=True)
    image_source = peewee.CharField()
    image_data = peewee.BlobField()
    # for future use:
    #image_status = peewee.CharField()


class DBAuthorOverride(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    override = peewee.BooleanField()


class DBTagPoint(BaseModel):
    tag = peewee.CharField(index=True)
    url = peewee.CharField()


class DBInfo(BaseModel):
    time_created = peewee.DateTimeField()
    time_updated = peewee.DateTimeField(null=True)

###############################################################################
# Primary Classes
###############################################################################


class WikidotConnector:

    def __init__(self, site):
        if site[-1] != '/':
            site += '/'
        self.site = site
        req = requests.Session()
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req

    ###########################################################################
    # Helper Methods
    ###########################################################################

    def _module(self, name, pageid, **kwargs):
        """Retrieve data from the specified wikidot module."""
        headers = {'Content-Type': 'application/x-www-form-urlencoded;'}
        payload = {
            'page_id': pageid,
            'pageId': pageid,  # fuck wikidot
            'moduleName': name,
            'wikidot_token7': '123456'}
        cookies = {'wikidot_token7': '123456'}
        for i in self.req.cookies:
            cookies[i.name] = i.value
        for k, v in kwargs.items():
            payload[k] = v
        data = self.req.post(self.site + 'ajax-module-connector.php',
                             data=payload, headers=headers, cookies=cookies)
        return data.json()

    def _parse_forum_thread_page(self, page_html):
        soup = BeautifulSoup(page_html)
        Post = namedtuple('Post', 'id title content user time parent')
        for e in soup.select('div.post'):
            post_id = e['id'].split('-')[1]
            title = e.select('div.title')[0].text.strip()
            content = e.select('div.content')[0]
            user = e.select('span.printuser')[0].text
            unix_time = e.select('span.odate')[0]['class'][1].split('_')[1]
            time = arrow.get(unix_time).format('YYYY-MM-DD HH:mm:ss')
            granpa = e.parent.parent
            if 'class' in granpa.attrs and 'post-container' in granpa['class']:
                parent = granpa.select('div.post')[0]['id'].split('-')[1]
            else:
                parent = None
            p = Post(post_id, title, content, user, time, parent)
            yield p

    ###########################################################################
    # Site-wide Methods
    ###########################################################################

    def list_all_pages(self):
        baseurl = '{}system:list-all-pages/p/{}'.format(self.site, '{}')
        soup = BeautifulSoup(self.html(baseurl))
        counter = soup.select('div.pager span.pager-no')[0].text
        last_page = int(counter.split(' ')[-1])
        for index in range(1, last_page + 1):
            soup = BeautifulSoup(self.html(baseurl.format(index)))
            pages = soup.select('div.list-pages-item a')
            for link in pages:
                url = self.site.rstrip('/') + link["href"]
                yield url

    ###########################################################################
    # Page Interface Methods
    ###########################################################################

    def get_page_html(self, url):
        data = self.req.get(url)
        if data.status_code != 404:
            return data.text
        else:
            return None

    def get_page_history(self, pageid):
        if pageid is None:
            return None
        data = self._module(
            name='history/PageRevisionListModule',
            pageid=pageid,
            page=1,
            perpage=1000000)['body']
        soup = BeautifulSoup(data)
        history = []
        Revision = namedtuple('Revision', 'number user time comment')
        for i in soup.select('tr')[1:]:
            rev_data = i.select('td')
            number = int(rev_data[0].text.strip('.'))
            user = rev_data[4].text
            time = arrow.get(rev_data[5].text, 'DD MMM YYYY HH:mm')
            time = time.format('YYYY-MM-DD HH:mm:ss')
            comment = rev_data[6].text
            history.append(Revision(number, user, time, comment))
        return list(reversed(history))

    def get_page_votes(self, pageid):
        if pageid is None:
            return None
        data = self._module(
            name='pagerate/WhoRatedPageModule',
            pageid=pageid)['body']
        soup = BeautifulSoup(data)
        votes = []
        Vote = namedtuple('Vote', 'user vote')
        for i in soup.select('span.printuser'):
            user = i.text
            vote = i.next_sibling.next_sibling.text.strip()
            votes.append(Vote(user, vote))
        return votes

    def get_page_source(self, pageid):
        if pageid is None:
            return None
        html = self._module(
            name='viewsource/ViewSourceModule',
            pageid=pageid)['body']
        source = BeautifulSoup(html).text
        source = source[11:].strip()
        return source

    ###########################################################################
    # Read-only Methods
    ###########################################################################

    def get_forum_thread(self, url):
        thread_id = re.search(r'/forum/t-([0-9]+)/', url).group(1)
        data = self._module(
            name='forum/ForumViewThreadPostsModule',
            t=thread_id,
            pageid=None,
            pageNo='1')['body']
        soup = BeautifulSoup(data)
        try:
            pager = soup.select('span.pager-no')[0].text
            num_of_pages = int(pager.split(' of ')[1])
        except IndexError:
            num_of_pages = 1
        comments = []
        for post in self._parse_forum_thread_page(data):
            comments.append(post)
        for n in range(2, num_of_pages + 1):
            data = self._module(
                name='forum/ForumViewThreadPostsModule',
                t=thread_id,
                pageid=None,
                pageNo='1')['body']
            for post in self._parse_forum_thread_page(data):
                comments.append(post)
        return comments

    def pageid(self, html):
        pageid = re.search("pageId = ([^;]*);", html)
        if pageid is not None:
            pageid = pageid.group(1)
        return pageid

    def title(self, html):
        soup = BeautifulSoup(html)
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        return title

    ###########################################################################
    # Active Methods
    ###########################################################################

    def auth(self, username, password):
        payload = {
            'login': username,
            'password': password,
            'action': 'Login2Action',
            'event': 'login'}
        url = 'https://www.wikidot.com/default--flow/login__LoginPopupScreen'
        self.req.post(url, data=payload)

    def edit(self, pageid, url, source, title, comments=None):
        wiki_page = url.split('/')[-1]
        lock = self._module('edit/PageEditModule', pageid, mode='page')
        params = {
            'source': source,
            'comments': comments,
            'title': title,
            'lock_id': lock['lock_id'],
            'lock_secret': lock['lock_secret'],
            'revision_id': lock['page_revision_id'],
            'action': 'WikiPageAction',
            'event': 'savePage',
            'wiki_page': wiki_page}
        self._module('Empty', pageid, **params)

    def comment(self, thread_id, source, title=None):
        params = {
            'threadId': thread_id,
            'parentId': None,
            'title': title,
            'source': source,
            'action': 'ForumAction',
            'event': 'savePost'}
        self._module('Empty', None, **params)


class Snapshot:

    RTAGS = ['scp', 'tale', 'hub', 'joke', 'explained', 'goi-format']

    def __init__(self):
        db.connect()
        db.create_tables([DBPage, DBTitle, DBImageInfo, DBAuthorOverride,
                          DBTagPoint, DBInfo], safe=True)
        self.db = db
        self.wiki = WikidotConnector('http://www.scp-wiki.net')

    ###########################################################################
    # Scraping Methods
    ###########################################################################

    def _scrape_scp_titles(self):
        """Yield tuples of SCP articles' titles"""
        series_urls = [
            "http://www.scp-wiki.net/scp-series",
            "http://www.scp-wiki.net/scp-series-2",
            "http://www.scp-wiki.net/scp-series-3"]
        for url in series_urls:
            soup = BeautifulSoup(self.wiki.html(url))
            articles = [i for i in soup.select("ul > li")
                        if re.search("[SCP]+-[0-9]+", i.text)]
            for i in articles:
                url = "http://www.scp-wiki.net{}".format(i.a["href"])
                try:
                    skip, title = i.text.split(" - ", maxsplit=1)
                except:
                    skip, title = i.text.split(", ", maxsplit=1)
                yield {"url": url, "skip": skip, "title": title}

    def _scrape_image_whitelist(self):
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        req = requests.Session()
        req.mount('http://', requests.adapters.HTTPAdapter(max_retries=5))
        soup = BeautifulSoup(req.get(url).text)
        for i in soup.select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            image_data = req.get(image_url).content
            yield {"image_url": image_url,
                   "image_source": image_source,
                   "image_data": image_data}

    def _scrape_rewrites(self):
        url = "http://05command.wikidot.com/alexandra-rewrite"
        req = requests.Session()
        site = 'http://05command.wikidot.com'
        req.mount(site, requests.adapters.HTTPAdapter(max_retries=5))
        soup = BeautifulSoup(req.get(url).text)
        for i in soup.select("tr")[1:]:
            url = "http://www.scp-wiki.net/{}".format(i.select("td")[0].text)
            author = i.select("td")[1].text
            if author.startswith(":override:"):
                override = True
                author = author[10:]
            else:
                override = False
            yield {"url": url, "author": author, "override": override}

    def _scrape_tag(self, tag):
        url = "http://www.scp-wiki.net/system:page-tags/tag/{}".format(tag)
        soup = BeautifulSoup(self.wiki.html(url))
        for i in soup.select("div.pages-list-item a"):
            url = "http://www.scp-wiki.net{}".format(i["href"])
            yield {"tag": tag, "url": url}

    ###########################################################################
    # Database Methods
    ###########################################################################

    def _page_to_db(self, url):
        print("saving\t\t\t{}".format(url))
        try:
            page = DBPage.get(DBPage.url == url)
        except DBPage.DoesNotExist:
            page = DBPage(url=url)
        html = self.wiki.html(url)
        # this will break if html is None
        # however html should never be None with the current code
        # so I'll leave it as is to signal bad pages on the site
        pageid = self.wiki.pageid(html)
        history = self.wiki.history(pageid)
        votes = self.wiki.votes(pageid)
        page.html = html
        page.history = history
        page.votes = votes
        page.save()

    def _meta_tables(self):
        print("collecting metadata")
        DBTitle.delete().execute()
        DBImageInfo.delete().execute()
        DBAuthorOverride.delete().execute()
        with db.transaction():
            titles = list(self._scrape_scp_titles())
            for idx in range(0, len(titles), 500):
                DBTitle.insert_many(titles[idx:idx + 500]).execute()
            images = list(self._scrape_image_whitelist())
            for idx in range(0, len(images), 500):
                DBImageInfo.insert_many(images[idx:idx + 500]).execute()
            rewrites = list(self._scrape_rewrites())
            for idx in range(0, len(rewrites), 500):
                DBAuthorOverride.insert_many(rewrites[idx:idx + 500]).execute()

    def _tag_to_db(self, tag):
        print("saving tag\t\t{}".format(tag))
        tag_data = list(self._scrape_tag(tag))
        urls = [i["url"] for i in tag_data]
        DBTagPoint.delete().where(
            (DBTagPoint.tag == tag) & ~ (DBTagPoint.url << urls))
        old_urls = DBTagPoint.select(DBTagPoint.url)
        new_data = [i for i in tag_data if i["url"] not in old_urls]
        with db.transaction():
            for idx in range(0, len(new_data), 500):
                DBTagPoint.insert_many(new_data[idx:idx + 500]).execute()

    def _update_info(self, action):
        try:
            info_row = DBInfo.get()
        except DBInfo.DoesNotExist:
            info_row = DBInfo()
        if action == "created":
            time = arrow.utcnow().format("YYYY-MM-DD HH:mm:ss")
            info_row.time_created = time
        info_row.save()

    ###########################################################################
    # Public Methods
    ###########################################################################

    def take(self):
        self._update_info("created")
        self._meta_tables()
        for tag in Snapshot.RTAGS:
            self._tag_to_db(tag)
        for url in self.wiki.list_all_pages():
            self._page_to_db(url)

    def pagedata(self, url):
        """Retrieve PageData from the database"""
        try:
            data = DBPage.get(DBPage.url == url)
        except DBPage.DoesNotExist as e:
            raise e
        pd = namedtuple("PageData", "html history votes")
        return pd(data.html, data.history, data.votes)

    def tag(self, tag):
        """Retrieve list of pages with the tag from the database"""
        for i in DBTagPoint.select().where(DBTagPoint.tag == tag):
            yield i.url

    def rewrite(self, url):
        rd = namedtuple('DBAuthorOverride', 'url author override')
        try:
            data = DBAuthorOverride.get(DBAuthorOverride.url == url)
            return rd(data.url, data.author, data.override)
        except DBAuthorOverride.DoesNotExist:
            return False

    def images(self):
        images = {}
        im = namedtuple('Image', 'source data')
        for i in DBImageInfo.select():
            images[i.image_url] = im(i.image_source, i.image_data)
        return images

    def title(self, url):
        try:
            return DBTitle.get(DBTitle.url == url).title
        except DBTitle.DoesNotExist:
            num = re.search('[0-9]+$', url).group(0)
            skip = 'SCP-{}'.format(num)
            return DBTitle.get(DBTitle.skip == skip).title


class Page:

    """Scrape and store contents and metadata of a page."""

    sn = Snapshot()   # Snapshot instance used to init the pages

    ###########################################################################
    # Constructors
    ###########################################################################

    def __init__(self, url=None):
        self.url = url

    ###########################################################################

    def links(self):
        if self._raw_html is None:
            return []
        links = []
        soup = BeautifulSoup(self._raw_html)
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

    def children(self):
        if not hasattr(self, "tags"):
            return []
        if not any(i in self.tags for i in [
                'scp', 'hub', 'goi2014', 'splash']):
            return []
        lpages = []
        for url in self.links():
            try:
                p = Page(url)
                try:
                    p.chapters = self.chapters
                except AttributeError:
                    pass
            except DBPage.DoesNotExist:
                continue
            if p.data is not None:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            mpages = [i for i in lpages if
                      any(k in i.tags for k in ["supplement", "splash"])]
            return mpages
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            mpages = [i for i in lpages if any(
                k in i.tags for k in ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in child.links():
                    return True
                soup = BeautifulSoup(child._raw_html)
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

###############################################################################
# Methods For Retrieving Certain Pages
###############################################################################


def get_all():
    count = DBPage.select().count()
    for n in range(1, count // 50 + 2):
        query = DBPage.select().order_by(DBPage.url).paginate(n, 50)
        for i in query:
            yield Page(i.url)


def main():
    # test_url = 'http://testwiki2.wikidot.com/page1'
    # wiki_url = '/'.join(test_url.split('/')[:-1])
    # wiki = WikidotConnector(wiki_url)
    # pasw = '2A![]M/r}%t?,"GWQ.eH#uaukC3}#.*#uv=yd23NvkpuLgN:kPOBARb}:^IDT?%j'
    # wiki.auth(username='anqxyr', password=pasw)
    # wiki.edit_page(test_url,
    #                'this is page was edit by a robot',
    #                title='I am a Title too')
    #Snapshot().take()
    wiki = WikidotConnector('http://www.scp-wiki.net')
    thr = 'http://www.scp-wiki.net/forum/t-466570/scp-1600'
    data = wiki.get_forum_thread(thr)
    for i in data:
        print(i.id, i.title, i.user)
    pass


if __name__ == "__main__":
    main()
