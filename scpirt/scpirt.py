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
        super().__init__()
        self.ui = Ui_imagebox()
        self.ui.setupUi(self)
        self.ui.status.wheelEvent = lambda x: self.parentWidget().wheelEvent(x)
        self.ui.status.currentIndexChanged.connect(self.change_status)
        self.ui.google.clicked.connect(self.open_google)
        self.ui.tineye.clicked.connect(self.open_tineye)
        self.ui.attribute.stateChanged.connect(self.check('attribute'))
        self.ui.send_pm.stateChanged.connect(self.check('send_pm'))
        self.ui.remove.stateChanged.connect(self.check('remove'))
        self.ui.picture.addAction(self.ui.list_delete)
        self.ui.picture.addAction(self.ui.email)
        self.load_image(image)

    def load_image(self, image):
        self.image = image
        self.ui.source.setText(image['source'])
        self.ui.comments.setText(image['comments'])
        self.ui.picture.setToolTip('{url}\n{page}\n{user}'.format(**image))
        self.ui.status.setCurrentIndex(
            self.ui.status.findText(image['status']))
        self.worker = ImageDownloader(image['url'])
        self.worker.finished.connect(self.set_picture)
        self.worker.start()

    def change_status(self):
        status = self.ui.status.currentText()
        self.image['status'] = status
        if status in (
                self.image['saved_status'], '', 'PUBLIC DOMAIN', 'REPLACED',
                'SOURCE UNKNOWN', 'UNABLE TO CONTACT', 'PERMISSION DENIED'):
            # PERMISSION DENIED is in this group because usually it was
            # preceeded by AWAITING REPLY, and so the image is already removed
            values = 0, 0, 0
        elif status in ('BY-SA CC', 'BY-NC-SA CC', 'PERMISSION GRANTED'):
            values = 1, 0, 0
        elif status in ('AWAITING REPLY', 'PERMANENTLY REMOVED'):
            values = 0, 1, 1
        for field, value in zip(('attribute', 'send_pm', 'remove'), values):
            state = QtCore.Qt.Checked if value else QtCore.Qt.Unchecked
            getattr(self.ui, field).setCheckState(state)

    def check(self, field):
        return lambda x: self.image.update({field: x == 2})

    def open_google(self):
        #url = 'https://www.google.com/searchbyimage?&image_url='
        #webbrowser.open(url + self.image['url'])
        from pprint import pprint
        pprint(self.image)

    def open_tineye(self):
        webbrowser.open('http://tineye.com/search?url=' + self.image['url'])

    def set_picture(self):
        filename = 'images/' + '_'.join(self.image['url'].split('/')[-2:])
        self.ui.picture.setPixmap(QtGui.QPixmap(filename))


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
                saved_status=row[4].text,
                comments=row[5].text if row[5].text else None))
        self.update_status.emit('Done.')


class SCPIRT(QtGui.QMainWindow):

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.show()
        for i in range(10):
            action = getattr(self.ui, 'scp{}'.format(i))
            action.triggered.connect(lambda i=i: self.get_list(i + 1))

    def get_list(self, index):
        self.current_review_block = index
        self.images = []
        self.worker = ImageListDownloader(index, self.images)
        self.worker.finished.connect(self.display_detailed)
        self.worker.update_status.connect(self.ui.statusbar.showMessage)
        self.worker.start()

    def display_detailed(self):
        child = self.ui.main.takeAt(0)
        while child:
            child.widget().deleteLater()
            child = self.ui.main.takeAt(0)
        for i in self.images:
            self.ui.main.addWidget(Imagebox(i))


if __name__ == '__main__':
    app = QtGui.QApplication('')
    SCPIRT()
    app.exec_()
