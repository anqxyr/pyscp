#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import pathlib
import pyscp
import logging
import webbrowser

from scpirt_ui import Ui_MainWindow
from imagebox_ui import Ui_imagebox
from bs4 import BeautifulSoup as soup
from PySide import QtGui, QtCore

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)
req = pyscp.core.InsistentRequest()
sandbox = pyscp.WikidotConnector('scpsandbox2')

###############################################################################


class Imagebox(QtGui.QWidget):

    def __init__(self, image):
        self.image = image
        super().__init__()
        self.ui = Ui_imagebox()
        self.ui.setupUi(self)
        self.ui.source.setText(self.image['source'])
        self.ui.comments.setText(self.image['comments'])
        self.ui.picture.setToolTip(
            '{}\n{}\n{}'.format(image['url'], image['page'], image['user']))
        self.ui.status.wheelEvent = lambda x: self.parentWidget().wheelEvent(x)
        self.ui.status.currentIndexChanged.connect(self.on_status_change)
        self.ui.status.setCurrentIndex(
            self.ui.status.findText(image['status']))
        self.ui.google.clicked.connect(self.open_google)
        self.ui.tineye.clicked.connect(self.open_tineye)
        self.worker = ImageDownloader(image['url'])
        self.worker.finished.connect(self.set_picture)
        self.worker.start()

    def on_status_change(self):
        text = self.ui.status.currentText()
        self.image['status'] = text

    def open_google(self):
        url = 'https://www.google.com/searchbyimage?&image_url='
        webbrowser.open(url + self.image['url'])

    def open_tineye(self):
        url = 'http://tineye.com/search?url='
        webbrowser.open(url + self.image['url'])

    def set_picture(self):
        filename = 'images/' + '_'.join(self.image['url'].split('/')[-2:])
        pixmap = QtGui.QPixmap(filename)
        self.ui.picture.setPixmap(pixmap)
        self.ui.picture.setScaledContents(True)


class ImageDownloader(QtCore.QThread):

    def __init__(self, url):
        self.url = url
        super().__init__()

    def run(self):
        filename = 'images/' + '_'.join(self.url.split('/')[-2:])
        if pathlib.Path(filename).exists():
            return
        if not pathlib.Path('images').exists():
            pathlib.Path('images').mkdir()
        data = req.get(self.url, allow_redirects=True).content
        with open(filename, 'wb') as file:
            file.write(data)


class ImageListDownloader(QtCore.QThread):

    update_status = QtCore.Signal(str)

    def __init__(self, block_number, result_container):
        self.block_number = block_number
        self.result_container = result_container
        super().__init__()

    def run(self):
        self.update_status.emit('Downloading image list.')
        html = sandbox('image-review-{}'.format(self.block_number)).html
        tables = soup(html)(class_='wiki-content-table')
        self.update_status.emit('Parsing tables.')
        rows = [i('td') for table in tables for i in table('tr')[1:]]
        for row in rows:
            user, source = None, None
            if row[1]('span'):
                user = row[1].span.a.text
            if row[3]('a'):
                source = row[3].a['href']
            self.result_container.append(dict(
                url=row[0]('img')[0]['src'],
                page=row[1].a['href'],
                user=user,
                source=source,
                status=row[4].text,
                comments=row[5].text if row[5].text else None))
        self.update_status.emit('Done.')


class SCPIRT(QtGui.QMainWindow):

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.show()
        self.ui.scp0.triggered.connect(lambda: self.get_list(1))

    def get_list(self, index):
        self.images = []
        self.worker = ImageListDownloader(index, self.images)
        self.worker.finished.connect(self.display_detailed)
        self.worker.update_status.connect(self.ui.statusbar.showMessage)
        self.worker.start()

    def display_detailed(self):
        for i in self.images:
            self.ui.imagebox_layout.addWidget(Imagebox(i))


if __name__ == '__main__':
    app = QtGui.QApplication('')
    window = SCPIRT()
    app.exec_()
