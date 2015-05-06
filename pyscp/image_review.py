#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

from PySide import QtGui, QtCore

###############################################################################


class Widget:

    def __init__(self, *args, **kw):
        _args, widgets, self._children = [], [], []
        for i in args:
            (widgets if isinstance(i, Widget) else _args).append(i)
        self._base_init(*_args, **kw)
        self.add(*widgets)

    def __getattr__(self, name):
        return getattr(self._base, name)

    def _base_init(self, *args, **kw):
        self._base = QtGui.QWidget(*args, **kw)
        self.setLayout(QtGui.QVBoxLayout())

    def _base_add(self, base_widget):
        self.layout().addWidget(base_widget)

    def add(self, *widgets):
        for widget in widgets:
            widget.parent = widget
            self._children.append(widget)
            self._base_add(widget._base)


class App(Widget):

    def __init__(self, title):
        self._app = QtGui.QApplication('')
        super().__init__()
        self.setWindowTitle(title)
        self.init_ui()

    def run(self):
        self.show()
        self._app.exec_()

    def init_ui(self):
        pass


class Action(Widget):

    def _base_init(self, name, fn):
        self._base = QtGui.QAction(name, None)
        self.triggered.connect(fn)


class Menu(Widget):

    def _base_init(self, name):
        self._base = QtGui.QMenu(name)

    def _base_add(self, base_widget):
        self.addAction(base_widget)


class MenuBar(Widget):

    def _base_init(self):
        self._base = QtGui.QMenuBar()

    def _base_add(self, base_widget):
        self.addMenu(base_widget)


###############################################################################

def main():
    app = App('SCP Image Review Helper')
    app.add(
        MenuBar(
            Menu(
                '&File',
                Action('&Open', lambda: None),
                Action('&Quit', app.close)
            )
        ))
    app.run()

if __name__ == '__main__':
    main()
