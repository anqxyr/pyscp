#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

from itertools import chain
from functools import wraps, partial, update_wrapper

###############################################################################
# Decorators
###############################################################################


def listify(fn=None, wrapper=list):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kw):
            return wrapper(fn(*args, **kw))
        return wrapped
    if fn is None:
        return decorator
    return decorator(fn)


def morph_exc(catch_exc, raise_exc, message=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kw):
            try:
                return fn(*args, **kw)
            except catch_exc as error:
                raise raise_exc(message) from error
        return wrapped
    return decorator


class LogCallDecorator:

    def __init__(self, fn, logger):
        self.fn = fn
        self.logger = logger
        self.ismethod = False
        update_wrapper(self, fn)

    def __call__(self, *args, **kw):
        argsrepr = chain(
            map(repr, args),
            ('{}={}'.format(k, repr(v)) for k, v in kw.items()))
        if self.ismethod:
            next(argsrepr)  # don't print self
            message = '{}.{}'.format(
                args[0].__class__.__name__, self.fn.__name__)
        else:
            message = '{}'.format(self.fn.__name__)
        if argsrepr:
            message += '({})'.format(', '.join(argsrepr))
        self.logger(message)
        return self.fn(*args, **kw)

    def __get__(self, obj, objtype):
        self.ismethod = True
        return partial(self.__call__, obj)


log_call = lambda logger=print: lambda fn: LogCallDecorator(fn, logger)
