#!/usr/bin/env python3

from bs4 import BeautifulSoup
from lxml import etree, html
import re
import os
import shutil
import copy
import arrow
import requests
import tempfile

image_review_list = []

class Page():

    """Scrape and store contents and metadata of a page"""

    image_whitelist = {}
    author_overrides = {}
    #contains the titles of the SCP articles, e.g. "SCP-1511: Mobile Paradise"
    scp_index = {}
    datadir = os.path.expanduser("~/.scp-data/")

    def __init__(self, url=None):
        self.url = url
        self.tags = []
        self.images = []
        self.author = None
        self.rewrite_author = None
        self.title = None
        self.soup = ""
        if url is not None:
            self.scrape()
            self.cook()
        self.override()

    def override(self):
        if self.url == "http://www.scp-wiki.net/scp-1047-j":
            self.data = None
        elif self.url == "http://www.scp-wiki.net/scp-2998":
            x = [Page("{}-{}".format(self.url, n)) for n in range(2, 11)]
            for i in x:
                i.title = "SCP-2998-{}".format(i.url.split("-")[-1])
            self.list_children = lambda: x
        elif self.title == "Wills And Ways":
            x = [k for k in self.list_children()
                 if k.title != "Marshall, Carter and Dark Hub "]
            self.list_children = lambda: x
        elif self.title == "Serpent's Hand Hub":
            x = [k for k in self.list_children() if k.title !=
                 "Black Queen Hub"]
            self.list_children = lambda: x
        elif self.url == "Chicago Spirit Hub":
            self.list_children = lambda: []

    def scrape(self):
        '''Scrape the contents of the given url.'''
        def cached(path, scrape_func):
            if os.path.isfile(path):
                with open(path, "r") as F:
                    return F.read()
            else:
                data = scrape_func()
                if data is not None:
                    with open(path, "w") as F:
                        F.write(data)
                return data

        def scrape_page_body():
            print("downloading page data: \t" + self.url)
            try:
                soup = BeautifulSoup(requests.get(self.url).text)
            except Exception as e:
                print("ERROR: {}".format(e))
                return None
            return str(soup)

        def scrape_history():
            if self.soup is None:
                return None
            print("downloading history: \t" + self.url)
            pageid = re.search("pageId = ([^;]*);", self.soup)
            if pageid is not None:
                pageid = pageid.group(1)
            else:
                return None
            headers = {"Content-Type": "application/x-www-form-urlencoded;",
                       "Cookie": "wikidot_token7=123456;"}
            payload = ("page=1&perpage=1000&page_id={}&moduleName=history%2FPa"
                       "geRevisionListModule&wikidot_token7=123456"
                       .format(pageid))
            try:
                data = requests.post("http://www.scp-wiki.net/ajax-module-"
                                     "connector.php", data=payload,
                                     headers=headers).json()["body"]
            except Exception as e:
                print("ERROR: {}".format(e))
                return None
            return data
        cached_file = self.url.replace("http://www.scp-wiki.net/", "")\
            .replace("/", "_").replace(":", "")
        if cached_file == "":
            self.soup = None
            return
        if not os.path.exists(Page.datadir):
            os.mkdir(Page.datadir)
        if not os.path.exists("{}history/".format(Page.datadir)):
            os.mkdir("{}history/".format(Page.datadir))
        self.soup = cached(Page.datadir + cached_file, scrape_page_body)
        self.history = cached("{}history/{}".format(Page.datadir,
                              cached_file), scrape_history)

    def cook(self):
        '''Cook the soup, retrieve title, data, and tags'''
        if not self.soup:
            self.title = None
            self.data = None
            return
        soup = BeautifulSoup(self.soup)
        # meta
        self.tags = [a.string for a in soup.select("div.page-tags a")]
        if self.history is not None:
            author = BeautifulSoup(self.history).select("tr")[-1].select(
                "td")[-3].text
            self.author = author
            if self.url in Page.author_overrides:
                override = Page.author_overrides[self.url]
                if override[:10] == ":override:":
                    self.author = override[10:]
                else:
                    self.rewrite_author = override
        # title
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
                    s = BeautifulSoup(Page(u).soup)
                    entries = s.select("ul li")
                    for e in entries:
                        if re.match(".*>SCP-[0-9]*<.*", str(e)):
                            i = e.text.split(" - ")
                            Page.scp_index[i[0]] = i[1]
            title = "{}: {}".format(title, Page.scp_index["SCP-" + title[4:]])
        self.title = title
        # body
        if not soup.select("#page-content"):
            self.data = None
            return
        data = soup.select("#page-content")[0]
        garbage = ["div.page-rate-widget-box", "div.scp-image-block"]
        [k.decompose() for e in garbage for k in data.select(e)]
        #images
        for i in data.select("img"):
            if i.has_attr("src"):
                global image_review_list
                image_review_list.append(
                    {"url": i["src"], "page": self.url, "page_title":
                     self.title, "author": self.author})
        for i in data.select("img"):
            if i.name is None or not i.has_attr("src"):
                continue
            if i["src"] not in Page.image_whitelist:
                for k in i.parents:
                    if k.name == "table" or (k.has_attr("class") and k["class"]
                                             == "scp-image-block"):
                        k.decompose()
                        break
                i.decompose()
            else:
                self.images.append(i["src"])
                image_url = i["src"].split("/")
                i["src"] = "images/{}_{}".format(image_url[-2], image_url[-1])
        # tables
        # tab-views
        for i in data.select("div.yui-navset"):
            wraper = soup.new_tag("div", **{"class": "tabview"})
            titles = [a.text for a in i.select("ul.yui-nav em")]
            tabs = i.select("div.yui-content > div")
            for k in tabs:
                k.attrs = {"class": "tabview-tab"}
                tab_title = soup.new_tag("div", **{"class": "tab-title"})
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
            if content.text == "":
                content = i.select("div.collapsible-block-unfolded")[0]
                del(content["style"])
                content.select("div.collapsible-block-content")[0].decompose()
                content.select("div.collapsible-block-unfolded-link"
                               )[0].decompose()
            content["class"] = "collaps-content"
            col = soup.new_tag("div", **{"class": "collapsible"})
            content = content.wrap(col)
            col_title = soup.new_tag("div", **{"class": "collaps-title"})
            col_title.string = link_text
            content.div.insert_before(col_title)
            i.replace_with(content)
        # links
        for i in data.select("a"):
            #del(i["href"])
            i.name = "span"
            i["class"] = "link"
        #quote boxes
        for i in data.select("blockquote"):
            i.name = "div"
            i["class"] = "quote"
        #add title to the page
        if "scp" in self.tags:
            data = "<p class='scp-title'>{}</p>{}".format(self.title, data)
        else:
            data = "<p class='tale-title'>{}</p>{}".format(self.title, data)
        data += "<div class='tags' style='display: none'><hr/><p>{}</p></div>"\
                .format("</p><p>".join(self.tags))
        self.data = data

    def list_children(self):
        def links(self):
            links = []
            soup = BeautifulSoup(self.soup)
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
        if not any(i in self.tags for i in ["scp", "hub", "splash"]):
            return []
        lpages = []
        for url in links(self):
            p = Page(url)
            if p.soup and p.data:
                lpages.append(p)
        if any(i in self.tags for i in ["scp", "splash"]):
            mpages = [i for i in lpages if
                      any(k in i.tags for k in ["supplement", "splash"])]
            return mpages
        if "hub" in self.tags and any(i in self.tags
                                      for i in ["tale", "goi2014"]):
            mpages = [i for i in lpages if any(k in i.tags for k in
                      ["tale", "goi-format", "goi2014"])]

            def backlinks(page, child):
                if page.url in links(child):
                    return True
                soup = BeautifulSoup(child.soup)
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


class Epub():

    """"""

    allpages_global = []

    def __init__(self, title):
        self.title = title
        #change to a proper temp dir later on
        self.dir = tempfile.TemporaryDirectory()
        self.templates = {}
        for i in os.listdir("templates"):
            self.templates[i.split(".")[0]] = etree.parse(
                "{}/templates/{}".format(os.getcwd(), i))
        self.allpages = []
        #pre-building toc
        self.toc = self.templates["toc"]
        self.toc.xpath("/*/*[2]/*")[0].text = title
        self.images = {}

    def add_page(self, page, node=None):
        #each page can only appear once in the book
        if page.url in Epub.allpages_global or page.data is None:
            return
        epub_page = copy.deepcopy(self.templates["page"])
        #XPath expressions are pre-generated with etree.getpath
        #I have no clue how they work
        epub_page.xpath("/*/*[1]/*[1]")[0].text = page.title
        epub_page.xpath("/*/*[2]")[0].append(html.fromstring(page.data))
        #write the page on disk
        uid = "page_{:0>4}".format(len(self.allpages))
        epub_page.write("{}/{}.xhtml".format(self.dir.name, uid))
        #add the images in the page to the list of images used in the book
        for i in page.images:
            self.images[i] = page.title
        #add the page to the list of all pages in the book
        self.allpages.append({
            "title": page.title, "id": uid, "author": page.author,
            "rewrite_author": page.rewrite_author, "url": page.url})
        if page.url is not None:
            Epub.allpages_global.append(page.url)

        def add_to_toc(node, page, uid):
            if node is None:
                node = self.toc.xpath("/*/*[3]")[0]
            navpoint = etree.SubElement(node, "navPoint", id=uid, playOrder=
                                        str(len(self.allpages)))
            navlabel = etree.SubElement(navpoint, "navLabel")
            etree.SubElement(navlabel, "text").text = page.title
            etree.SubElement(navpoint, "content", src="{}.xhtml".format(uid))
            return navpoint
        new_node = add_to_toc(node, page, uid)
        [self.add_page(i, new_node) for i in page.list_children()]

    def save(self, filename):
        self.toc.write(
            "{}/toc.ncx".format(self.dir.name), xml_declaration=True,
            encoding="utf-8", pretty_print=True)
        #building the spine
        spine = self.templates["content"]
        self.allpages.sort(key=lambda k: k["id"])
        spine.xpath("/*/*[1]/*[1]")[0].text = arrow.utcnow().format(
            "YYYY-MM-DDTHH:mm:ss")
        spine.xpath("/*/*[1]/dc:title", namespaces={
            "dc": "http://purl.org/dc/elements/1.1/"})[0].text = self.title
        for k in self.allpages:
            etree.SubElement(spine.xpath("/*/*[2]")[0], "item", **{
                "media-type": "application/xhtml+xml", "href":
                k["id"] + ".xhtml", "id": k["title"].replace(":", "-")})
            etree.SubElement(spine.xpath("/*/*[3]")[0], "itemref",
                             idref=k["title"].replace(":", "-"))
        os.mkdir("{}/images/".format(self.dir.name))
        imagedir = "{}images/".format(Page.datadir)
        if not os.path.exists(imagedir):
            os.mkdir(imagedir)
        for i in self.images:
            path = "_".join([i.split("/")[-2], i.split("/")[-1]])
            if not os.path.isfile(imagedir + path):
                print("downloading image: {}".format(i))
                with open(imagedir + path, "wb") as F:
                    shutil.copyfileobj(requests.get(i, stream=True).raw, F)
            shutil.copy(imagedir + path, "{}/images/".format(self.dir.name))
        spine.write(self.dir.name + "/content.opf", xml_declaration=True,
                    encoding="utf-8", pretty_print=True)
        #other necessary files
        container = self.templates["container"]
        os.mkdir(self.dir.name + "/META-INF/")
        container.write(self.dir.name + "/META-INF/container.xml",
                        xml_declaration=True, encoding="utf-8",
                        pretty_print=True)
        with open(self.dir.name + "/mimetype", "w") as F:
            F.write("application/epub+zip")
        shutil.copy("stylesheet.css", self.dir.name)
        shutil.copy("cover.png", self.dir.name)
        shutil.make_archive(filename, "zip", self.dir.name)
        shutil.move(filename + ".zip", filename + ".epub")


def yield_pages():
    def urls_by_tag(tag):
        print("downloading tag info: {}".format(tag))
        soup = BeautifulSoup(requests.get("http://www.scp-wiki.net/system:page"
                             "-tags/tag/" + tag).text)
        urls = ["http://www.scp-wiki.net" + a["href"] for a in soup.select(
            "div.pages-list div.pages-list-item div.title a")]
        return urls

    def natural_key(s):
        re_natural = re.compile('[0-9]+|[^0-9]+')
        return [(1, int(c)) if c.isdigit() else (0, c.lower()) for c
                in re_natural.findall(s)] + [s]
    # skips
    url_001 = "http://www.scp-wiki.net/proposals-for-scp-001"
    for i in BeautifulSoup(requests.get(url_001).text
                           ).select("#page-content")[0].select("a"):
        url = "http://www.scp-wiki.net" + i["href"]
        p = Page(url)
        p.chapter = "SCP Database/001 Proposals"
        yield p
    scp_main = [i for i in urls_by_tag("scp") if re.match(".*scp-[0-9]*$", i)]
    scp_main = sorted(scp_main, key=natural_key)
    scp_blocks = [[i for i in scp_main if (int(i.split("-")[-1]) // 100 == n)]
                  for n in range(30)]
    for b in scp_blocks:
        b_name = "SCP Database/Articles {}-{}".format(b[0].split("-")[-1],
                                                      b[-1].split("-")[-1])
        for url in b:
            p = Page(url)
            p.chapter = b_name
            yield p

    def quick_yield(tags, chapter_name):
        L = [urls_by_tag(i) for i in tags if type(i) == str]
        for i in [i for i in tags if type(i) == list]:
            a = [x for k in i for x in urls_by_tag(k)]
            L.append(a)
        for url in [i for i in L[0] if all(i in t for t in L)]:
            p = Page(url)
            p.chapter = chapter_name
            yield p
    yield from quick_yield(["joke", "scp"], "SCP Database/Joke Articles")
    yield from quick_yield(["explained", "scp"],
                           "SCP Database/Explained Phenomena")
    hubhubs = ["http://www.scp-wiki.net/canon-hub",
               "http://www.scp-wiki.net/goi-contest-2014",
               "http://www.scp-wiki.net/acidverse"]
    nested_hubs = [i.url for k in hubhubs for i in Page(k).list_children()]
    for i in quick_yield(["hub", ["tale", "goi2014"]], "Canons and Series"):
        if i.url not in nested_hubs:
            yield i
    yield from quick_yield(["tale"], "Assorted Tales")


def image_review():
    """This function is not related to the ebook and is not necessary
    for it to work. It is here to help the wiki staff only"""
    #removing duplicates from the list
    new_list = []
    for i in image_review_list:
        if i["url"] not in [k["url"] for k in new_list]:
            new_list.append(i)
    new_list.sort(key=lambda x: x["page_title"])
    with open("image_review.txt", "w") as F:
        F.write("||~ Image||~ Page/Author||~ Search Results||~ Source"
                "||~ Status||~ Notes||\n")
        for img in new_list:
            if (img["url"] == "http://scp-wiki.wdfiles.com/local--files/compon"
                    "ent:heritage-rating/scp-heritage-v3.png"):
                continue
            post = requests.post("http://tineye.com/search", data={
                "url": img["url"]}, allow_redirects=False).headers
            tineye_url = ("[{} TinEye]".format(post["location"]) if "location"
                          in post else "TinEye")
            google_url = ("https://www.google.com/searchbyimage?&image_url={}"
                          .format(img["url"]))
            title = img["page_title"]
            title = title if len(title) < 40 else title[:36] + "(..)"
            user = img["author"]
            user = ("[[user {}]]".format(user) if user not in
                    ["Account Deleted"] else "None")
            F.write('|| _\n[[image {0} link="{0}" width="50px"]] _\n'
                    .format(img["url"]))
            F.write('||[{} {}] _\n{} _\n'.format(img["page"], title, user))
            F.write('||{} _\n [{} Google] _\n'.format(tineye_url, google_url))
            F.write('|| [pasteurlhere source] _\n'
                    '|| _\n[!-- Pick one, delete others, then delete the'
                    ' comment block\n'
                    '##darkred|**PERMANENTLY REMOVED**## _\n'
                    '##darkred|**PERMISSION DENIED**## _\n'
                    '##darkred|**UNABLE TO CONTACT**## _\n'
                    '##darkred|**SOURCE UNKNOWN**## _\n'
                    '##blue|**REPLACED**## _\n'
                    '##blue|**AWAITING REPLY**## _\n'
                    '##blue|**PERMISSION GRANTED**## _\n'
                    '##blue|**BY-NC-SA CC**## _\n'
                    '##green|**BY-SA CC**## _\n'
                    '##green|**PUBLIC DOMAIN**## _\n'
                    '--]\n || [!-- write_notes_here --] ||\n')



def update(time):
    def recent_changes(page):
        print("downloading recent changes: page {}".format(page))
        headers = {"Content-Type": "application/x-www-form-urlencoded;",
                   "Cookie": "wikidot_token7=123456;"}
        payload = ("page={}&perpage=20&page_id=1926945&moduleName=changes%2FS"
                   "iteChangesListModule&wikidot_token7=123456".format(page))
        try:
            data = requests.post("http://www.scp-wiki.net/ajax-module-"
                                 "connector.php", data=payload,
                                 headers=headers).json()["body"]
        except Exception as e:
            print("ERROR: {}".format(e))
            return None
        return BeautifulSoup(data)
    page = 1
    while True:
        soup = recent_changes(page)
        for i in soup.select("div.changes-list-item"):
            rev_time = arrow.get(i.select("span.odate")[0].text,
                                 "DD MMM YYYY HH:mm")
            if rev_time.timestamp > arrow.get(time).timestamp:
                url = i.select("td.title a")[0]["href"]
                cached_file = Page.datadir + url.replace(
                    "http://www.scp-wiki.net/", "").replace(
                    "/", "_").replace(":", "")
                if os.path.exists(cached_file):
                    print("deleting outdated cache: {}".format(cached_file))
                    os.remove(cached_file)
            else:
                return
        page += 1


def main():
    def retrieve_table(url):
        print("downloading tabled data: {}".format(url))
        soup = BeautifulSoup(requests.get(url).text)
        results = {}
        for i in soup.select("tr")[1:]:
            results[i.select("td")[0].text] = i.select("td")[1].text
        return results

    def make_new_book(title):
        book = Epub(title)
        static_pages = []
        for xf in [i for i in sorted(os.listdir(os.getcwd() + "/pages"))]:
            p = Page()
            p.title = xf[3:-6]
            with open(os.path.join(os.getcwd() + "/pages", xf)) as F:
                p.data = F.read()
            static_pages.append(p)
        #map(book.add_page, static_pages)
        [book.add_page(k) for k in static_pages]
        book.chapters = []
        return book

    def add_attributions(book):
        attrib = Page()
        attrib.title = "Acknowledgments and Attributions"
        attrib.data = "<div class='attrib'>"
        for i in sorted(book.allpages, key=lambda k: k["id"]):
            def add_one(attrib, title, url, author, r=None):
                attrib.data += "<p><b>{}</b> ({}) was written by <b>{}</b>"\
                               .format(title, url, author)
                if r is not None:
                    attrib.data += " and rewritten by <b>{}</b>.</p>".format(r)
                else:
                    attrib.data += ".</p>"
            if i["url"] is None:
                continue
            if i["author"] not in [None, "(account deleted)"]:
                add_one(attrib, i["title"], i["url"], i["author"],
                        i["rewrite_author"])
        for i in book.images:
            if Page.image_whitelist[i] != "PUBLIC DOMAIN":
                attrib.data += (
                    "<p>The image {}_{}, which appears on the page <b>{}</b>, "
                    "is a CC image available at <u>{}</u>.</p>".format(
                        i.split("/")[-2], i.split("/")[-1], book.images[i],
                        Page.image_whitelist[i]))
        attrib.data += "</div>"
        book.add_page(attrib)

    def goes_in_book(previous_book, page):
        def increment_title(old_title):
            n = old_title[-2:]
            n = str(int(n) + 1).zfill(2)
            return old_title[:-2] + n
        if ("scp" in page.tags and
                page.chapter.split("/")[-1] in previous_book.chapters):
            return previous_book.title
        elif (page.chapter == "Canons and Series" and
              previous_book.title[-4:-3] == "1"):
                return "SCP Foundation: Tome 2.01"
        elif (page.chapter == "Assorted Tales" and
              previous_book.title[-4:-3] == "2"):
                return "SCP Foundation: Tome 3.01"
        elif len(previous_book.allpages) < 500:
                return previous_book.title
        else:
                return increment_title(previous_book.title)

    def node_with_text(book, text):
        if text is None:
            return None
        return book.toc.xpath('.//navPoint[child::navLabel[child::text[text()='
                              '"{}"]]]'.format(text))[0]
    if os.path.exists("{}_lastcreated".format(Page.datadir)):
        with open("{}_lastcreated".format(Page.datadir)) as F:
            update(F.read())
    with open("{}_lastcreated".format(Page.datadir), "w") as F:
        F.write(arrow.utcnow().format("YYYY-MM-DDTHH:mm:ss"))
    Page.image_whitelist = retrieve_table(
        "http://scpsandbox2.wikidot.com/ebook-image-whitelist")
    Page.author_overrides = retrieve_table(
        "http://05command.wikidot.com/alexandra-rewrite")
    book = make_new_book("SCP Foundation: Tome 1.01")

    for i in yield_pages():
        book_name = goes_in_book(book, i)
        if book.title != book_name:
            add_attributions(book)
            book.save(book.title)
            book = make_new_book(book_name)
        previous_chapter = None
        for c in i.chapter.split("/"):
            if not c in [i["title"] for i in book.allpages]:
                print(c)
                p = Page()
                p.title = c
                p.data = "<div class='title2'>{}</div>".format(c)
                book.add_page(p, node_with_text(book, previous_chapter))
                book.chapters.append(c)
            previous_chapter = c
        book.add_page(i, node_with_text(book, previous_chapter))
    add_attributions(book)
    book.save(book.title)
    image_review()

main()
