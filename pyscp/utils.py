#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import funcy
import inspect
import logging
import blessings
import re
import time
import threading
import signal

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


def split(text, delimeters):
    pattern = '|'.join(map(re.escape, delimeters))
    return re.split(pattern, text)


class ProgressBar:

    def __init__(self, title, max_value):
        self.title = title
        self.max_value = max_value
        self.value = 0
        self.term = blessings.Terminal()
        signal.signal(signal.SIGINT, self.exit)

    def start(self):
        self.finished = False
        self.time_started = time.time()
        threading.Thread(target=self.run).start()

    def update(self):
        print('\r' + self.line(), end='')

    def line(self):
        filled = 40 * self.value / self.max_value
        parts = ' ▏▎▍▌▋▊▉'
        current = int(filled * len(parts)) % len(parts)
        bar = '█' * int(filled) + parts[current] + ' ' * 40
        tm = time.gmtime(time.time() - self.time_started)
        return '{}{} {:>3}% ({}:{:02}:{:02})   '.format(
            self.title,
            self.term.green('{:.40}'.format(bar)),
            100 * self.value // self.max_value,
            tm.tm_hour, tm.tm_min, tm.tm_sec)

    def run(self):
        while not self.finished:
            self.update()
            time.sleep(1)

    def stop(self):
        self.finished = True
        print('\r' + self.line())

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
