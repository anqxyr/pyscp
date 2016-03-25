#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import logging
import re
import time
import threading
import signal
import functools
import inspect

###############################################################################
# Decorators
###############################################################################

###############################################################################
# Decorator decorator is a simplified version of the code from the funcy lib.
# https://github.com/Suor/funcy
###############################################################################


class Call:

    def __init__(self, func, args, kwargs):
        self.func, self.args, self.kwargs = func, args, kwargs

    def __call__(self):
        return self.func(*self.args, **self.kwargs)


def decorator(deco):
    spec = inspect.getargspec(deco)
    if len(spec.args) > 1 or spec.varargs or spec.keywords:
        @functools.wraps(deco)
        def _fab(*dargs, **dkwargs):
            return make_decorator(deco, *dargs, **dkwargs)
        return _fab
    else:
        return functools.wraps(deco)(make_decorator(deco))


def make_decorator(deco, *dargs, **dkwargs):
    def _decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            call = Call(func, args, kwargs)
            return deco(call, *dargs, **dkwargs)
        return wrapper
    return _decorator

###############################################################################


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


@decorator
def log_errors(call, logger=print):
    try:
        return call()
    except Exception as error:
        logger(error)
        raise(error)


@decorator
def decochain(call, *decs):
    fn = call.func
    for dec in reversed(decs):
        fn = dec(fn)
    return fn(*call.args, **call.kwargs)


class cached_property:

    def __init__(self, func):
        self.func = func
        functools.update_wrapper(self, func)

    def __get__(self, obj, cls):
        if not hasattr(obj, '_cache'):
            obj._cache = {}
        if self.func.__name__ not in obj._cache:
            obj._cache[self.func.__name__] = self.func(obj)
        return obj._cache[self.func.__name__]

###############################################################################


def split(text, delimeters):
    pattern = '|'.join(map(re.escape, delimeters))
    return re.split(pattern, text)


class ProgressBar:

    def __init__(self, title, max_value):
        self.title = title
        self.max_value = max_value
        self.value = 0
        signal.signal(signal.SIGINT, self.exit)

    def start(self):
        self.finished = False
        self.time_started = time.time()
        threading.Thread(target=self.run).start()

    def update(self):
        print(self.line() + '\r', end='')

    def line(self):
        filled = 40 * self.value / self.max_value
        parts = ' ▏▎▍▌▋▊▉'
        current = int(filled * len(parts)) % len(parts)
        bar = '█' * int(filled) + parts[current] + ' ' * 40
        tm = time.gmtime(time.time() - self.time_started)
        return '{} |{}| {:>3}% ({}:{:02}:{:02})   '.format(
            self.title,
            bar[:40],
            100 * self.value // self.max_value,
            tm.tm_hour, tm.tm_min, tm.tm_sec)

    def run(self):
        while not self.finished:
            self.update()
            time.sleep(1)

    def stop(self):
        self.finished = True
        print(self.line())

    def exit(self, signum, frame):
        self.stop()
        raise KeyboardInterrupt


def pbar(it, title=None, max=None):
    max = len(it) if max is None else max
    title = '' if title is None else title + ' '
    bar = ProgressBar(title, max)
    bar.start()
    for i in it:
        yield i
        bar.value += 1
        bar.update()
    bar.stop()

###############################################################################


class LogCount:

    def __init__(self):
        self.count = 1

    def filter(self, record):
        record.count = self.count
        self.count += 1
        return True


def log_sql_debug():
    logger = logging.getLogger('peewee')
    logger.setLevel(logging.DEBUG)
    logger.addFilter(LogCount())
    term = logging.StreamHandler()
    term.setFormatter(logging.Formatter('{count} {message}', style='{'))
    logger.addHandler(term)


def default_logging(debug=False):
    term = logging.StreamHandler()
    file = logging.FileHandler('pyscp.log', mode='a', delay=True)
    if debug:
        term.setLevel(logging.DEBUG)
        file.setLevel(logging.DEBUG)
    else:
        term.setLevel(logging.INFO)
        file.setLevel(logging.INFO)
    term.setFormatter(logging.Formatter('{message}', style='{'))
    file.setFormatter(
        logging.Formatter('{asctime} {levelname:8s} {message}', style='{'))
    logger = logging.getLogger('pyscp')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(term)
    logger.addHandler(file)

###############################################################################
