#!/usr/bin/env python3

"""
Filters.

Take a list of pages and return a subset of the list.
"""

###############################################################################
# Imports
###############################################################################

import pyscp.stats.counters as cn
import pyscp.stats.scalars as sc

###############################################################################


def tag(pages, tag):
    """Pages with a given tag."""
    if not tag:
        return pages
    return [p for p in pages if tag in p.tags]


def user(pages, user):
    """Pages by a certain user."""
    return [p for p in pages if p.author == user]


# TODO: needs more indicative name.
def min_authored(pages, min_val=3):
    """Pages by authors who have at least min_val pages."""
    authors = cn.author(pages, sc.count)
    return [p for p in pages if authors[p.author] >= min_val]


def filter_rating(pages, min_val=20):
    """Pages with rating above min_val."""
    return [p for p in pages if p.rating > min_val]
