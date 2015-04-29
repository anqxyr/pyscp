#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import funcy
import inspect

###############################################################################
# Decorators
###############################################################################


@funcy.decorator
def listify(call, wrapper=list):
    return wrapper(call())


@funcy.decorator
def morph_exceptions(call, catch_exc, raise_exc):
    try:
        return call()
    except catch_exc as error:
        raise raise_exc(error) from error


@funcy.decorator
def ignore_exceptions(call, catch_exc, return_value=None):
    try:
        return call()
    except catch_exc:
        return return_value


def is_method(fn):
    return inspect.getargspec(fn)[0][0] == 'self'


def format_args(call):
    _args = call._args[1:] if is_method(call._func) else call._args
    _args = list(map(repr, _args))
    _kw = {k: repr(v) for k, v in call._kwargs.items()}
    _kw = list(map('='.join, _kw.items()))
    return '{}({})'.format(call._func.__qualname__, ', '.join(_args + _kw))


@funcy.decorator
def log_exceptions(call, catch_exc, logger=print):
    try:
        return call()
    except catch_exc as error:
        logger('!! {}: {}'.format(format_args(call), error))
        raise(error)


@funcy.decorator
def log_calls(call, logger=print):
    logger(format_args(call))
    return call()


@funcy.decorator
def chain_decorators(call, *decs):
    fn = call._func
    for dec in reversed(decs):
        fn = dec(fn)
    return fn(*call._args, **call._kwargs)

###############################################################################


def votes_by_user(orm, user):
    down, up = [], []
    for vote in (
            orm.Vote.select().join(orm.User)
            .where(orm.User.name == user)):
        if vote.value == 1:
            up.append(vote.page.url)
        else:
            down.append(vote.page.url)
    return {'+': up, '-': down}
