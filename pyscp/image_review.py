#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import pyscp
import logging

from bs4 import BeautifulSoup as bs4
from PySide import QtGui, QtCore

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger('pyscp')
req = pyscp.core.InsistentRequest()

###############################################################################
# GUI Wrappers
###############################################################################


class Widget:

    def __init__(self, *args, **kw):
        _args, widgets, self._children = [], [], []
        for i in args:
            (widgets if isinstance(i, Widget) else _args).append(i)
        self._init_obj(*_args, **kw)
        self.add(*widgets)

    def _init_obj(self, *args, **kw):
        layout = kw.pop('layout', 'vbox')
        self._obj = QtGui.QWidget(*args, **kw)
        self._obj.setLayout(dict(
            vbox=QtGui.QVBoxLayout,
            hbox=QtGui.QHBoxLayout,
            grid=QtGui.QGridLayout,
            form=QtGui.QFormLayout)[layout]())

    def _add_child(self, widget):
        self._obj.layout().addWidget(widget._obj)

    def add(self, *widgets):
        for widget in widgets:
            widget.parent = self
            self._children.append(widget)
            self._add_child(widget)

    def update_ui(self):
        QtGui.qApp.processEvents()


class MainWindow(Widget):

    def _init_obj(self, *args, **kw):
        layout = kw.pop('layout', 'vbox')
        self._obj = QtGui.QMainWindow(*args, **kw)
        self._center = Widget(layout=layout)
        self._obj.setCentralWidget(self._center._obj)

    def _add_child(self, widget):
        if isinstance(widget, MenuBar):
            self._menubar = widget
            self._obj.setMenuBar(widget._obj)
        else:
            self._center.add(widget)

    def set_layout(self, layout):
        self._center.set_layout(layout)


class App(MainWindow):

    def __init__(self, title, *, layout='vbox'):
        self._app = QtGui.QApplication('')
        super().__init__(layout=layout)
        self._obj.setWindowTitle(title)

    def run(self):
        self._obj.show()
        self._app.exec_()


class Action(Widget):

    def _init_obj(self, name, fn, shortcut=None):
        self._obj = QtGui.QAction(name, None)
        if not shortcut and '&' in name:
            shortcut = 'Ctrl+' + name[name.index('&') + 1]
        self._obj.setShortcut(shortcut)
        self._obj.triggered.connect(fn)


class Menu(Widget):

    def _init_obj(self, name):
        self._obj = QtGui.QMenu(name)

    def _add_child(self, widget):
        self._obj.addAction(widget._obj)


class MenuBar(Widget):

    def _init_obj(self):
        self._obj = QtGui.QMenuBar()

    def _add_child(self, widget):
        self._obj.addMenu(widget._obj)


class Button(Widget):

    def _init_obj(self, name, fn):
        self._obj = QtGui.QPushButton(name)
        self._obj.clicked.connect(fn)


class Label(Widget):

    def _init_obj(self, text):
        self._obj = QtGui.QLabel(text)


class Picture(Widget):

    def _init_obj(self, url):
        image_data = req.get(url).content
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(image_data)
        self._obj = QtGui.QLabel()
        self._obj.setPixmap(pixmap)


###############################################################################

class ImageBox(Widget):

    def __init__(self, image, page, user, source, status, comments):
        super().__init__(layout='hbox')
        self.add(Picture(image))


class ImageReview(App):

    def __init__(self):
        super().__init__('SCPIRT', layout='vbox')
        self.sbox = pyscp.WikidotConnector('scpsandbox2')
        self.add(
            MenuBar(
                Menu(
                    '&File',
                    Action('&Quit', self._obj.close)),
                Menu(
                    '&Images', *[
                        Action(
                            'View Block {}'.format(i),
                            lambda i=i: self.view_block(i))
                        for i in range(1, 21)])))

    def view_block(self, index):
        block_html = self.sbox('image-review-{}'.format(index)).html
        tables = bs4(block_html)(class_='wiki-content-table')
        for row in [i('td') for table in tables for i in table('tr')[1:]]:
            user, source = None, None
            if row[1]('span'):
                user = row[1].span.a.text
            if row[3]('a'):
                source = row[3].a['href']
            self.add(ImageBox(
                image=row[0]('img')[0]['src'],
                page=row[1].a['href'],
                user=user,
                source=source,
                status=row[4].text,
                comments=row[5] if row[5].text else None))
            return


if __name__ == '__main__':
    ImageReview().run()
