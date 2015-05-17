#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import funcy
import inspect
import logging

###############################################################################
# Decorators
###############################################################################


decorator = funcy.decorator


@decorator
def listify(call, wrapper=list):
    return wrapper(call())


@decorator
def morph(call, catch_exc, raise_exc):
    try:
        return call()
    except catch_exc as error:
        raise raise_exc(error) from error


@decorator
def ignore(call, error=Exception, value=None):
    try:
        return call()
    except error:
        return value


def is_method(fn):
    spec = inspect.getargspec(fn)
    if not spec[0]:
        return False
    return spec[0][0] == 'self'


def format_args(call):
    _args = call._args[1:] if is_method(call._func) else call._args
    _args = list(map(repr, _args))
    _kw = {k: repr(v) for k, v in call._kwargs.items()}
    _kw = list(map('='.join, _kw.items()))
    return '{}({})'.format(call._func.__qualname__, ', '.join(_args + _kw))


@decorator
def log_errors(call, logger=print):
    try:
        return call()
    except Exception as error:
        logger('!! {}: {}'.format(format_args(call), error))
        raise(error)


@decorator
def log_calls(call, logger=print):
    logger(format_args(call))
    return call()


@decorator
def decochain(call, *decs):
    fn = call._func
    for dec in reversed(decs):
        fn = dec(fn)
    return fn(*call._args, **call._kwargs)

###############################################################################


def default_logging(debug=False):
    term = logging.StreamHandler()
    file = logging.FileHandler('pyscp.log', mode='w', delay=True)
    if debug:
        term.setLevel(logging.DEBUG)
        file.setLevel(logging.DEBUG)
    else:
        term.setLevel(logging.INFO)
        file.setLevel(logging.WARNING)
    term.setFormatter(logging.Formatter('{message}', style='{'))
    file.setFormatter(
        logging.Formatter('{asctime} {levelname:8s} {message}', style='{'))
    logger = logging.getLogger('pyscp')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(term)
    logger.addHandler(file)

###############################################################################
