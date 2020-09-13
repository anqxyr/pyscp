# pyscp

**pyscp** is a python library for interacting with wikidot-hosted websites. The library is mainly intended for use by the administrative staff of the www.scp-wiki.net website, and has a host of feature exclusive to it. However, the majority of the core functionality should be applicalbe to any wikidot-based site.

## Installation

Download the latest code, open the containing folder, and run the following command:
```
pip install . --user
```
Done.

## Examples

### Acessing Pages

```python
import pyscp

wiki = pyscp.wikidot.Wiki('www.scp-wiki.net')
p = wiki('scp-837')
print(
    '"{}" has a rating of {}, {} revisions, and {} comments.'
    .format(p.title, p.rating, len(p.history), len(p.comments)))
```
```
"SCP-837: Multiplying Clay" has a rating of 108, 14 revisions, and 54 comments.
```

You can access other sites as well:

```python
ru_wiki = pyscp.wikidot.Wiki('scpfoundation.ru')
p = ru_wiki('scp-837')
print('"{}" was created by {} on {}.'.format(p.title, p.author, p.created))
```
```
"SCP-837 - Глина умножения" was created by Gene R on 2012-12-26 11:12:13.
```

If the site doesn't use a custom domain, you can use the name of the site instead of the full url. E.g. `Wiki('scpsandbox2')` is the same as `Wiki('scpsandbox2.wikidot.com')`.

### Editing Pages

```python

wiki = pyscp.wikidot.Wiki('scpsandbox2')
wiki.auth('example_username', 'example_password')
p = wiki('test')
last_revision = p.history[-1].number
p.edit(
    source='= This is centered **text** that uses Wikidot markup.',
    title="you can skip the title if you don't want changing it",
    #you can leave out the comment too, but that'd be rude
    comment='testing automated editing')
print(p.text)   # see if it worked
p.revert(last_revision)  # let's revert it back to what it were.
```
```
This is centered text that uses Wikidot markup.
```


### Snapshots

When working with large number of pages, it could be faster to create a snapshot of the site than to download the pages one by one. Snapshots are optimized to download a large amount of data in the shortest possible time using multithreading.

```python
import pyscp

creator = pyscp.snapshot.SnapshotCreator('www.scp-wiki.net', 'snapshot_file.db')
creator.take_snapshot(forums=False)
# that's where we wait half an hour for it to finish
```

Once a snapshot is created, you can use `snapshot.Wiki` to read pages same as in the first example:

```python
wiki = pyscp.snapshot.Wiki('www.scp-wiki.net', 'snapshot_file.db')
p = wiki('scp-9005-2')
print(
    '"{}" has a rating of {}, was created by {}, and is awesome.'
    .format(p.title, p.rating, p.author))
print('Other pages by {}:'.format(p.author))
for other in wiki.list_pages(author=p.author):
    print(
        '{} (rating: {}, created: {})'
        .format(other.title, other.rating, other.created))
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
