# pyscp

Python API and utilities for the scp-wiki.net website.

## Installation

Download **dist/pyscp-0.8.0-py3-none-any.whl** , then run
```
pip install pyscp-0.8.0-py3-none-any.whl
```

Done.

## Retrieving information about a page.
 

```python
from pyscp import WikidotConnector, Page

wiki = WikidotConnector('www.scp-wiki.net')
with Page.load_from(wiki):
    p = Page('scp-837')
    print(
        'Page "{}" has a rating of {}, {} revisions, and {} comments.'
        .format(p.title, p.rating, len(p.history), len(p.comments)))
```
```
Page "SCP-837: Multiplying Clay" has a rating of 108, 14 revisions, and 54 comments.
```

First, we create a connector to the wiki, and use the `load_from` method to specify that we will be retriving pages via this connector. Then, we create a page and pirnt out some of its attributes.

You can use other sites to create a connector as well:

```python
ru_wiki = WikidotConnector('scpfoundation.ru')
with Page.load_from(ru_wiki):
    p = Page('scp-837')
    print(
        'Page "{}" was created by {} on {}.'
        .format(p.title, p.author, p.created))

```
```
Page "SCP-837 - Глина умножения" was created by Gene R on 2012-12-26 11:12:13.
```

Note that neither of "scp-wiki.net" or "www.scpfoundation.ru" will work, since they're both redirecting to a different domains, and **pyscp** does not follow redirects. If the site doesn't use a custom domain, you can use the name of the site instead of the full url. E.g. `WikidotConnector('scpsandbox2')` is the same as `WikidotConnector('scpsandbox2.wikidot.com')`.

## Authentication and Editing Pages

Some operation require you to authenticate first. Depending on the site, these can range from editing pages to merely reading them.

```python
import getpass

wiki = WikidotConnector('scpsandbox2')
username = input('Enter your username: ')
password = getpass.getpass('Enter your Wikidot password: ')
wiki.auth(username, password)
with Page.load_from(wiki):
    p = Page('test')
    last_revision = p.history[-1].number
    p.edit(
        source='= This is centered **text** that uses Wikidot markup.',
        title="you can skip the title if you don't want changing it",
        #you can leave out the comment to, but that'd be rude
        comment='testing automated editing'
    )
    print(p.text)   # see if it worked
    p.revert_to(last_revision)  # let's revert it back to what it were.
```
```
Enter your username: anqxyr
Enter your Wikidot password: 

This is centered text that uses Wikidot markup.
```


## Snapshots

When working with large number of pages, it could be faster to create a snapshot of the site than to download the pages one by one. Snapshots are optimized to download a large amount of data in the shortest possible time using multithreading.

```python
from pyscp import Snapshot, use_default_logging

use_default_logging()
sn = Snapshot('snapshot_file.db')
sn.take('www.scp-wiki.net')  # that's where we wait half an hour for it to finish

# use this instead if you want the standalone forum threads as well
#sn.take('www.scp-wiki.net', include_forums=True)
```

Once a snapshot is created, you can use it 

```python
with Page.load_from(sn):
    p = Page('scp-9005-2')
    print(
        'Page "{}" has a rating of {}, was created by {}, and is awesome.'
        .format(p.title, p.rating, p.author))
    print('Other pages by {}:'.format(p.author))
    for url in sn.list_all_pages():
        p2 = Page(url)
        if p2.author == p.author:
            print(
                '{} (rating: {}, created: {}'
                .format(p2.title, p2.rating, p2.created))
```
```
Page "SCP-9005-2" has a rating of 80, was created by yellowdrakex, and is awesome.
Other pages by yellowdrakex:
ClusterfREDACTED (rating: 112, created: 2011-10-20 18:08:49)
Dr Rights' Draft Box (rating: None, created: 2009-02-01 18:58:36)
Dr. Rights' Personal Log (rating: 3, created: 2008-11-26 23:03:27)
Dr. Rights' Personnel File (rating: 13, created: 2008-11-24 20:45:34)
Fifteen To Sixteen (rating: 17, created: 2010-02-15 05:55:58)
Great Short Story Concepts (rating: 1, created: 2010-06-03 19:26:06)
RUN AWAY FOREVURRR (rating: 79, created: 2011-10-24 16:34:23)
SCP-288: The "Stepford Marriage" Rings (rating: 56, created: 2008-11-27 07:47:01)
SCP-291: Disassembler/Reassembler (rating: 113, created: 2008-11-24 20:11:11)
...
```

Note the use of the `use_default_logging` method. **pyscp** uses default python logging module, and thus can be configured in any way you like. `use_default_logging` is useful when you don't want to spend time on configuring the logging yourself. It will output all non-debug messages to the terminal, and write any warning and error messages to an scp.log file in the current directory.

It is highly advised to use some form of logging while taking snapshots, to have some indication that the progress is being made.
