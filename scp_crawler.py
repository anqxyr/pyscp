#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import bs4
import functools
import os
import peewee
import pickle
import re
import requests

###############################################################################
# Global Constants
###############################################################################

DATADB = "scp_data.db"

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
    history = peewee.TextField()
    votes = peewee.TextField()


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

###############################################################################


class Snapshot:

    RTAGS = ["scp", "tale", "hub", "joke", "explained", "goi-format"]

    def __init__(self):
        req = requests.Session()
        req.mount("http://www.scp-wiki.net/",
                  requests.adapters.HTTPAdapter(max_retries=5))
        self.req = req
        db.connect()
        db.create_tables(
            [PageData, TitleData, ImageData, RewriteData, TagData],
            safe=True)

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
            res_per_page=1000,
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
                yield (url, skip, title)

    def _scrape_image_whitelist(self):
        url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
        soup = bs4.BeautifulSoup(self.req.get(url).text)
        for i in soup.select("tr")[1:]:
            image_url = i.select("td")[0].text
            image_source = i.select("td")[1].text
            yield (image_url, image_source)

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
            yield (url, author, override)

    def _scrape_tag(self, tag):
        url = "http://www.scp-wiki.net/system:page-tags/tag/{}".format(tag)
        soup = bs4.BeautifulSoup(self.req.get(url).text)
        for i in soup.select("div.pages-list-item a"):
            url = "http://www.scp-wiki.net{}".format(i["href"])
            yield url        

    ###########################################################################
    # Database Methods
    ###########################################################################

    def _page_to_db(self, url):
        try:
            db_page = PageData.get(PageData.url == url)
        except PageData.DoesNotExist:
            db_page = PageData(url=url)
        html = self._scrape_html(url)
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
        TitleData.delete().execute()
        for url, skip, title in self._scrape_scp_titles():
            TitleData.create(url=url, skip=skip, title=title)
        ImageData.delete().execute()
        for image_url, image_source in self._scrape_image_whitelist():
            ImageData.create(image_url=image_url, image_source=image_source)
        RewriteData.delete().execute()
        for url, author, override in self._scrape_rewrites():
            RewriteData.create(url=url, author=author, override=override)
 
    def _tag_to_db(self, tag):
        urls = list(self._scrape_tag(tag))
        TagData.delete().where(~ (TagData.tag << urls))
        old_urls = TagData.select(TagData.url)
        for url in [i for i in urls if i not in old_urls]:
            TagData.create(tag=tag, url=url)

    ###########################################################################

    def take(self):
        self._meta_tables()
        for tag in Snapshot.RTAGS:
            self._tag_to_db(tag)
        baseurl = "http://www.scp-wiki.net/system:list-all-pages/p/{}"
        soup = bs4.BeautifulSoup(self.req.get(baseurl).text)
        counter = soup.select("div.pager span.pager-no")[0].text
        last_page = int(counter.split(" ")[-1])
        for index in range(1, last_page + 1):
            data = self.req.get(baseurl.format(index))
            soup = bs4.BeautifulSoup(data.text)
            new_pages = soup.select("div.list-pages-item a")
            for link in new_pages:
                url = "http://www.scp-wiki.net{}".format(link["href"])
                self._page_to_db(db_page)


class cache_to_disk():

    """Save the results of the func to the directory specified in datadir."""

    def __init__(self, func):
        self.path = os.path.join(datadir, func.__name__)
        self.func = func
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        functools.update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        filename = self._make_filename(*args, **kwargs)
        fullpath = os.path.join(self.path, filename)
        if os.path.isfile(fullpath):
            with open(fullpath, "rb") as cache_file:
                data = pickle.load(cache_file)
        else:
            print("{:<40}{}".format(self.func.__name__, filename))
            data = self.func(*args, **kwargs)
            if data is not None:
                with open(fullpath, "wb") as cache_file:
                    pickle.dump(data, cache_file)
        return data

    def __get__(self, obj, objtype):
        '''Support instance methods.'''
        return functools.partial(self.__call__, obj)

    def _make_filename(self, *args, **kwargs):
        #this WILL NOT WORK in a general case
        #it does just enough for what we need and nothing more
        if args == () and kwargs == {}:
            return "no_args"
        url = getattr(args[0], "url", None)
        if url is not None:
            replace = ["http://", "/", "www.scp-wiki.net", ":"]
            for i in (url.replace(r, "") for r in replace):
                url = i
            if url == "":
                url = "www.scp-wiki.net"
            return url
        return repr(args[0])


@cache_to_disk
def _init_titles():
    """Return a dict of SCP articles' titles"""
    index_urls = ["http://www.scp-wiki.net/scp-series",
                  "http://www.scp-wiki.net/scp-series-2",
                  "http://www.scp-wiki.net/scp-series-3"]
    titles = {}
    for url in index_urls:
        soup = bs4.BeautifulSoup(req.get(url).text)
        articles = [i for i in soup.select("ul > li")
                    if re.search("[SCP]+-[0-9]+", i.text)]
        for e in articles:
            k, v = e.text.split(" - ", maxsplit=1)
            titles[k.split("-")[1]] = v
    return titles


@cache_to_disk
def _init_images():
    url = "http://scpsandbox2.wikidot.com/ebook-image-whitelist"
    soup = bs4.BeautifulSoup(req.get(url).text)
    results = {}
    for i in soup.select("tr")[1:]:
        results[i.select("td")[0].text] = i.select("td")[1].text
    return results


@cache_to_disk
def _init_rewrites():
    url = "http://05command.wikidot.com/alexandra-rewrite"
    soup = bs4.BeautifulSoup(req.get(url).text)
    results = {}
    pref = "http://www.scp-wiki.net/"
    for i in soup.select("tr")[1:]:
        results[pref + i.select("td")[0].text] = i.select("td")[1].text
    return results


titles = _init_titles()
images = _init_images()
rewrites = _init_rewrites()


class Page():

    """Scrape and store contents and metadata of a page."""

    def __init__(self, url=None):
        self.url = url
        self.data = None
        self.title = None
        self.tags = []
        self.images = []
        self.authors = []
        self.history = None
        self.soup = None
        if url is not None:
            self.soup = self._scrape_body()
            if self.soup is not None:
                self.data, self.title, self.tags = self._cook()
                self.history = self._scrape_history()
                if self.history is not None:
                    self.authors = self._parse_authors()
        self._override()

    @cache_to_disk
    def _scrape_history(self):
        """Scrape page's history."""
        pageid = re.search("pageId = ([^;]*);", self.soup)
        if pageid is None:
            return None
        return wikidot_module(name="history/PageRevisionListModule",
                              page=1, perpage=1000, pageid=pageid.group(1))

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

    def _cook(self):
        '''Retrieve title, data, and tags'''
        soup = bs4.BeautifulSoup(self.soup)
        rating = soup.select("#pagerate-button span")
        if rating != []:
            if int(rating[0].text) < 0:
                return None, None, []
            self.rating = rating[0].text
        # body
        parse_elements = [
            ("div.page-rate-widget-box", lambda x: x.decompose()),
            ("div.yui-navset", self._parse_tabview),
            ("div.collapsible-block", self._parse_collapsible),
            ("blockquote", self._parse_quote),
            ("sup.footnoteref", self._parse_footnote),
            ("sup.footnote-footer", self._parse_footnote_footer),
            ("a", self._parse_link),
            ("img", self._parse_image)]
        if not soup.select("#page-content"):
            data = None
        else:
            data = soup.select("#page-content")[0]
            for element, func in parse_elements:
                for i in data.select(element):
                    func(i)
        # tags
        tags = [a.string for a in soup.select("div.page-tags a")]
        # title
        if soup.select("#page-title"):
            title = soup.select("#page-title")[0].text.strip()
        else:
            title = ""
        if "scp" in tags and re.search("scp-[0-9]+$", self.url):
            title = "{}: {}".format(title,
                                    titles[title.split("-")[1]])
        #add title to the page
        if "scp" in tags:
            data = "<p class='scp-title'>{}</p>{}".format(title, data)
        else:
            data = "<p class='tale-title'>{}</p>{}".format(title, data)
        data += "<div class='tags' style='display: none'><hr/><p>{}</p></div>"\
                .format("</p><p>".join(tags))
        return data, title, tags

    def _parse_image(self, element):
        if element.name is None or not element.has_attr("src"):
            return
        if element["src"] not in images:
            #loop through the image's parents, until we find what to cut
            for p in element.parents:
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
                element.decompose()
        else:
                self.images.append(element["src"])
                page, image_url = element["src"].split("/")[-2:]
                element["src"] = "images/{}_{}".format(page, image_url)

    def _parse_tabview(self, element):
        soup = bs4.BeautifulSoup(self.soup)
        wraper = soup.new_tag("div", **{"class": "tabview"})
        titles = [a.text for a in element.select("ul.yui-nav em")]
        tabs = element.select("div.yui-content > div")
        for k in tabs:
            k.attrs = {"class": "tabview-tab"}
            tab_title = soup.new_tag("div", **{"class": "tab-title"})
            tab_title.string = titles[tabs.index(k)]
            k.insert(0, tab_title)
            wraper.append(k)
        element.replace_with(wraper)

    def _parse_collapsible(self, element):
        link_text = element.select("a.collapsible-block-link")[0].text
        content = element.select("div.collapsible-block-content")[0]
        if content.text == "":
            content = element.select("div.collapsible-block-unfolded")[0]
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
        element.replace_with(content)

    def _parse_link(self, element):
        del(element["href"])
        element.name = "span"
        element["class"] = "link"

    def _parse_quote(self, element):
        element.name = "div"
        element["class"] = "quote"

    def _parse_footnote(self, element):
        element.string = element.a.string

    def _parse_footnote_footer(self, element):
        element["class"] = "footnote"
        del(element["id"])
        element.string = "".join([k for k in element.strings])

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

    def list_children(self):
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


@cache_to_disk
def _scrape_tag(tag):
    soup = bs4.BeautifulSoup(req.get(
        "http://www.scp-wiki.net/system:page-tags/tag/" + tag).text)
    urls = ["http://www.scp-wiki.net" + a["href"] for a in soup.select(
        "div.pages-list div.pages-list-item div.title a")]
    return urls


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
    sn = Snapshot()
    for i in sn._scrape_image_whitelist():
        print(i)


main()