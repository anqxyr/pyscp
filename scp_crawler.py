#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import peewee
import re
import requests

###############################################################################
# Global Constants
###############################################################################

DATADB = "scp_data.db"

###############################################################################
# Decorators
###############################################################################


###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(DATADB)


class BaseModel(peewee.Model):

    class Meta:
        database = db


class PageData(BaseModel):
    url = peewee.CharField(unique=True)
    html = peewee.TextField()
    history = peewee.TextField(null=True)
    votes = peewee.TextField(null=True)


class TitleData(BaseModel):
    url = peewee.CharField(unique=True)
    skip = peewee.CharField()
    title = peewee.CharField()


class ImageData(BaseModel):
    image_url = peewee.CharField(unique=True)
    image_source = peewee.CharField()
    # for future use:
    #image_status = peewee.CharField()


class RewriteData(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    override = peewee.BooleanField()


class TagData(BaseModel):
    tag = peewee.CharField(index=True)
    url = peewee.CharField()


class SnapshotInfo(BaseModel):
    time_created = peewee.DateTimeField()
    time_updated = peewee.DateTimeField(null=True)

###############################################################################


class Snapshot:

    RTAGS = ["scp", "tale", "hub", "joke", "explained", "goi-format"]

    def __init__(self):
        req = requests.Session()
        req.mount("http://www.scp-wiki.net/",
                  requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req
        db.connect()
        db.create_tables([PageData, TitleData, ImageData, RewriteData,
                          TagData, SnapshotInfo], safe=True)

    ###########################################################################
    # Scraping Methods
    ###########################################################################

    def _wikidot_module(self, module_name, res_index, res_per_page, pageid):
        """Retrieve data from the specified wikidot module."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;",
            "Cookie": "wikidot_token7=123456;"}
        payload = {
            "page_id": pageid,
            "pageId": pageid,  # fuck wikidot
            "moduleName": module_name,
            "page": res_index,
            "perpage": res_per_page,
            "wikidot_token7": "123456"}
        data = self.req.post(
            "http://www.scp-wiki.net/ajax-module-connector.php",
            data=payload,
            headers=headers)
        try:
            return data.json()["body"]
        except Exception as e:
            print(module_name)
            print(data.json())
            print(payload)
            print(e)
            exit()

    def _scrape_html(self, url):
        data = self.req.get(url)
        if data.status_code != 404:
            return data.text
        else:
            return None

    def _scrape_history(self, pageid):
        return self._wikidot_module(
            module_name="history/PageRevisionListModule",
            res_index=1,
            res_per_page=1000000,
            pageid=pageid)

    def _scrape_votes(self, pageid):
        return self._wikidot_module(
            module_name="pagerate/WhoRatedPageModule",
            res_index=None,
            res_per_page=None,
            pageid=pageid)

    def _scrape_scp_titles(self):
        """Yield tuples of SCP articles' titles"""
        series_urls = [
            "http://www.scp-wiki.net/scp-series",
            "http://www.scp-wiki.net/scp-series-2",
            "http://www.scp-wiki.net/scp-series-3"]
        for url in series_urls:
            soup = bs4.BeautifulSoup(self.req.get(url).text)
            articles = [i for i in soup.select("ul > li")
                        if re.search("[SCP]+-[0-9]+", i.text)]
            for i in articles:
                url = "http://www.scp-wiki.net{}".format(i.a["href"])
                skip, title = i.text.split(" - ", maxsplit=1)
                yield {"url": url, "skip": skip, "title": title}

    def _scrape_image_whitelist(self):
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        soup = bs4.BeautifulSoup(self.req.get(url).text)
        for i in soup.select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            yield {"image_url": image_url, "image_source": image_source}

    def _scrape_rewrites(self):
        url = "http://05command.wikidot.com/alexandra-rewrite"
        soup = bs4.BeautifulSoup(self.req.get(url).text)
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
        soup = bs4.BeautifulSoup(self.req.get(url).text)
        for i in soup.select("div.pages-list-item a"):
            url = "http://www.scp-wiki.net{}".format(i["href"])
            yield {"tag": tag, "url": url}

    ###########################################################################
    # Database Methods
    ###########################################################################

    def _page_to_db(self, url):
        print("saving\t\t\t{}".format(url))
        try:
            db_page = PageData.get(PageData.url == url)
        except PageData.DoesNotExist:
            db_page = PageData(url=url)
        html = self._scrape_html(url)
        # this will break if html is None
        # however html should never be None with the current code
        # so I'll leave it as is to signal bad pages on the site
        pageid = re.search("pageId = ([^;]*);", html)
        if pageid is None:
            history = None
            votes = None
        else:
            pageid = pageid.group(1)
            history = self._scrape_history(pageid)
            votes = self._scrape_votes(pageid)
        db_page.html = html
        db_page.history = history
        db_page.votes = votes
        db_page.save()

    def _meta_tables(self):
        print("collecting metadata")
        TitleData.delete().execute()
        ImageData.delete().execute()
        RewriteData.delete().execute()
        with db.transaction():
            titles = list(self._scrape_scp_titles())
            for idx in range(0, len(titles), 500):
                TitleData.insert_many(titles[idx:idx + 500]).execute()
            images = list(self._scrape_image_whitelist())
            for idx in range(0, len(images), 500):
                ImageData.insert_many(images[idx:idx + 500]).execute()
            rewrites = list(self._scrape_rewrites())
            for idx in range(0, len(rewrites), 500):
                RewriteData.insert_many(rewrites[idx:idx + 500]).execute()

    def _tag_to_db(self, tag):
        print("saving tag\t\t{}".format(tag))
        tag_data = list(self._scrape_tag(tag))
        urls = [tag["url"] for tag in tag_data]
        TagData.delete().where((TagData.tag == tag) & ~ (TagData.url << urls))
        old_urls = TagData.select(TagData.url)
        new_data = [i for i in tag_data if i["url"] not in old_urls]
        with db.transaction():
            for idx in range(0, len(new_data), 500):
                TagData.insert_many(new_data[idx:idx + 500]).execute()

    def _update_info(self, action):
        try:
            info_row = SnapshotInfo.get()
        except SnapshotInfo.DoesNotExist:
            info_row = SnapshotInfo()
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
        baseurl = "http://www.scp-wiki.net/system:list-all-pages/p/{}"
        soup = bs4.BeautifulSoup(self.req.get(baseurl).text)
        counter = soup.select("div.pager span.pager-no")[0].text
        last_page = int(counter.split(" ")[-1])
        for index in reversed(range(1, last_page + 1)):
            data = self.req.get(baseurl.format(index))
            soup = bs4.BeautifulSoup(data.text)
            new_pages = soup.select("div.list-pages-item a")
            for link in new_pages:
                url = "http://www.scp-wiki.net{}".format(link["href"])
                self._page_to_db(url)

    def pagedata(self, url):
        """Retrieve PageData from the database"""
        data = PageData.get(PageData.url == url)
        return (data.html, data.history, data.votes)


class Page():

    """Scrape and store contents and metadata of a page."""

    def __init__(self, url=None, pagedata=None):
        self.url = url
        if pagedata is not None:
            raw_html, raw_history, raw_votes = pagedata
            self._parse_html(raw_html)
            self._raw_html = raw_html
            if raw_history is not None:
                self._parse_history(raw_history)
            if raw_votes is not None:
                self._parse_votes(raw_votes)
        self._override()

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
                new_children = func(args)
                self.list_children = lambda: new_children

    ###########################################################################
    # Parsing Methods
    ###########################################################################

    def _parse_html(self, raw_html):
        '''Retrieve title, data, and tags'''
        soup = bs4.BeautifulSoup(raw_html)
        rating_el = soup.select("#pagerate-button span")
        if rating_el:
            self.rating = rating_el[0].text
        
        self._parse_body(soup)
        self.tags = [a.string for a in soup.select("div.page-tags a")]
        self._parse_title(soup)
        self._add_title()
        #add title to the page
        # if "scp" in tags:
        #     data = "<p class='scp-title'>{}</p>{}".format(title, data)
        # else:
        #     data = "<p class='tale-title'>{}</p>{}".format(title, data)

    def _parse_body(self, soup):
        if not soup.select("#page-content"):
            self.data = None
            return
        self.data = bs4.BeautifulSoup(soup.select("#page-content")[0])
        for i in data.select("div.page-rate-widget-box"):
            i.decompose()
        self._parse_images()
        self._parse_tabviews()
        self._parse_collapsibles()
        self._parse_links()
        self._parse_quotes()
        self._parse_footnotes()

    def _parse_title(self, soup):
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        if "scp" in tags and re.search("scp-[0-9]+$", self.url):
            title = "{}: {}".format(title,
                                    titles[title.split("-")[1]])

    def _parse_images(self):
        for i in self.data.select("img"):
            if i.name is None or not i.has_attr("src"):
                return
            if i["src"] not in images:
                #loop through the image's parents, until we find what to cut
                for p in i.parents:
                    # old-style image formatting:
                    old_style = bool(p.select("table tr > td > img") and
                                     len(p.select("table tr > td")) == 1)
                    new_style = bool("class" in p.attrs and
                                     "scp-image-block" in p["class"])
                    if old_style or new_style:
                        p.decompose()
                        break
                else:
                    # if we couldn't find any parents to remove,
                    # just remove the image itself
                    i.decompose()
            else:
                    self.images.append(i["src"])
                    page, image_url = i["src"].split("/")[-2:]
                    i["src"] = "images/{}_{}".format(page, image_url)

    def _parse_tabviews(self):
        for i in self.data.select("div.yui-navset"):
            wraper = self.data.new_tag("div", **{"class": "tabview"})
            titles = [a.text for a in i.select("ul.yui-nav em")]
            tabs = i.select("div.yui-content > div")
            for k in tabs:
                k.attrs = {"class": "tabview-tab"}
                tab_title = self.data.new_tag("div", **{"class": "tab-title"})
                tab_title.string = titles[tabs.index(k)]
                k.insert(0, tab_title)
                wraper.append(k)
            i.replace_with(wraper)

    def _parse_collapsibles(self):
        for i in self.data.select("div.collapsible-block"):
            link_text = i.select("a.collapsible-block-link")[0].text
            content = i.select("div.collapsible-block-content")[0]
            if content.text == "":
                content = i.select("div.collapsible-block-unfolded")[0]
                del(content["style"])
                content.select("div.collapsible-block-content")[0].decompose()
                content.select("div.collapsible-block-unfolded-link"
                               )[0].decompose()
            content["class"] = "collaps-content"
            soup = bs4.BeautifulSoup(self.soup)
            col = soup.new_tag("div", **{"class": "collapsible"})
            content = content.wrap(col)
            col_title = soup.new_tag("div", **{"class": "collaps-title"})
            col_title.string = link_text
            content.div.insert_before(col_title)
            i.replace_with(content)

    def _parse_links(self):
        for i in self.data.select("a"):
            del(i["href"])
            i.name = "span"
            i["class"] = "link"

    def _parse_quotes(self):
        for i in self.data.select("blockquote"):
            i.name = "div"
            i["class"] = "quote"

    def _parse_footnotes(self):
        for i in self.data.select("sup.footnoteref"):
            i.string = i.a.string
        for i in self.data.select("sup.footnote-footer"):
            i["class"] = "footnote"
            del(i["id"])
            i.string = "".join([k for k in i.strings])

    def _parse_authors(self):
        history = bs4.BeautifulSoup(self.history)
        author = history.select("tr")[-1].select("td")[-3].text
        if self.url not in rewrites:
            return {author: "original"}
        new_author = rewrites[self.url]
        if new_author[:10] == ":override:":
            return {new_author[10:]: "original"}
        else:
            return {author: "original", new_author: "rewrite"}

    ###########################################################################

    def links(self):
        if self.soup is None:
            return []
        links = []
        soup = bs4.BeautifulSoup(self.soup)
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
            mpages = [i for i in lpages if any(
                k in i.tags for k in ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in child.links():
                    return True
                soup = bs4.BeautifulSoup(child.soup)
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


def _yield_skips():
    skips = [i for i in _scrape_tag("scp") if re.match(".*scp-[0-9]*$", i)]
    skips.sort(key=_natural_key)
    scp_blocks = [[i for i in skips if (int(i.split("-")[-1]) // 100 == n)]
                  for n in range(30)]
    for b in scp_blocks:
        b_name = "SCP Database/Articles {}-{}".format(b[0].split("-")[-1],
                                                      b[-1].split("-")[-1])
        for url in b:
            p = Page(url)
            p.chapter = b_name
            yield p


def _yield_001_proposals():
    proposals_hub = Page("http://www.scp-wiki.net/proposals-for-scp-001")
    for url in proposals_hub.links():
        p = Page(url)
        p.chapter = "SCP Database/001 Proposals"
        yield p


def _yield_joke_articles():
    for url in _scrape_tag("joke"):
        p = Page(url)
        p.chapter = "SCP Database/Joke Articles"
        yield p


def _yield_ex_articles():
    for url in _scrape_tag("explained"):
        p = Page(url)
        p.chapter = "SCP Database/Explained Phenomena"
        yield p


def _yield_hubs():
    hubhubs = ["http://www.scp-wiki.net/canon-hub",
               "http://www.scp-wiki.net/goi-contest-2014",
               "http://www.scp-wiki.net/acidverse"]
    nested_hubs = [i.url for k in hubhubs for i in Page(k).list_children()]
    hubs = [i for i in _scrape_tag("hub") if i in _scrape_tag("tale")
            or i in _scrape_tag("goi2014")]
    for url in hubs:
        if url not in nested_hubs:
            p = Page(url)
            p.chapter = "Canons and Series"
            yield p


def _yield_tales():
    for url in _scrape_tag("tale"):
        p = Page(url)
        p.chapter = "Assorted Tales"
        yield p


def all_pages():
    yield from _yield_001_proposals()
    yield from _yield_skips()
    yield from _yield_joke_articles()
    yield from _yield_ex_articles()
    yield from _yield_hubs()
    yield from _yield_tales()
    pass


def _natural_key(s):
    re_natural = re.compile('[0-9]+|[^0-9]+')
    return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c
            in re_natural.findall(s)] + [s]


def update(time):
    page = 1
    while True:
        print("downloading recent changes: page {}".format(page))
        soup = bs4.BeautifulSoup(wikidot_module(
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
    pass


main()
