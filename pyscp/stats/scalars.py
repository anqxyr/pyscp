#!/usr/bin/env python3

"""
Scalars.

Take a list of pages and return a single value.
"""

def upvotes(pages):
    """Upvotes."""
    return sum([v.value for v in p.votes].count(1) for p in pages)


def rating(pages):
    """Net rating."""
    return sum(p.rating for p in pages)


def rating_average(pages):
    """Average rating."""
    return rating(pages) / len(pages)


def divided(pages):
    """Controversy score."""
    return sum(len(p.votes) / p.rating for p in pages)


def redactions(pages):
    """Redaction score."""
    return sum(
        p.text.count('█') +
        20 * sum(map(p.text.count, ('REDACTED', 'EXPUNGED')))
        for p in pages)


def wordcount(pages):
    return sum(p.wordcount for p in pages)


def wordcount_average(pages):
    return wordcount(pages) / len(pages)
