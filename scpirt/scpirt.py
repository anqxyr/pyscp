#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import pathlib
import pyscp
import logging
import webbrowser
import bs4

import scpirt_ui
import imagebox_ui

from PySide import QtGui, QtCore

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)
req = pyscp.core.InsistentRequest()
sandbox = pyscp.core.WikidotConnector('scpsandbox2')

###############################################################################


class Image:

    def __init__(self, url, page, user, source, status, notes):
        self.url, self.page, self.user, self.source = url, page, user, source
        self.status = self._saved = status
        self.notes = notes

    @property
    def attribute(self):
        if self.status == self._saved:
            return False
        if self.status in ('BY-SA CC', 'BY-NC-SA CC', 'PERMISSION GRANTED'):
            return True
        return False

    @property
    def remove(self):
        if self.status == self._saved:
            return False
        if self.status in ('AWAITING REPLY', 'PERMANENTLY REMOVED'):
            return True
        return False

    def row_code(self):
        pic = '[[image {} width="50px"]]'.format(self.url)
        page = '[{} {}]'.format(self.page, self.page.split('/')[-1])
        user = '[[user {}]]'.format(self.user) if self.user else ' '
        source = '[{} source]'.format(self.source) if self.source else ' '
        status = '**{}**'.format(self.status) if self.status else ' '
        notes = self.notes.replace('\n', ' _\n') if self.notes else ' '
        return '||{}||{} _\n{}||{}||{}||{}||'.format(
            pic, page, user, source, status, notes)


###############################################################################


class Imagebox(QtGui.QWidget):

    def __init__(self, image):
        super().__init__()
        self.ui = imagebox_ui.Ui_imagebox()
        self.ui.setupUi(self)
        self.ui.status.wheelEvent = lambda x: self.parentWidget().wheelEvent(x)
        self.ui.google.clicked.connect(self.open_google)
        self.ui.tineye.clicked.connect(self.open_tineye)
        self.ui.picture.addAction(self.ui.list_delete)
        self.ui.picture.addAction(self.ui.email)
        self.load_image(image)
        self.ui.status.currentIndexChanged.connect(self.change_status)

    def load_image(self, image):
        self.image = image
        self.ui.source.setText(image.source)
        self.ui.notes.setText(image.notes)
        self.ui.picture.setToolTip('{0.url}\n{0.page}\n{0.user}'.format(image))
        self.ui.status.setCurrentIndex(self.ui.status.findText(image.status))
        self.worker = ImageDownloader(image.url)
        self.worker.finished.connect(self.set_picture)
        self.worker.start()

    def change_status(self):
        self.image.status = self.ui.status.currentText()
        for w, s in (
                (self.ui.remove, self.image.remove),
                (self.ui.attribute, self.image.attribute)):
            w.setCheckState(QtCore.Qt.Checked if s else QtCore.Qt.Unchecked)

    def open_google(self):
        webbrowser.open('https://www.google.com/searchbyimage?&image_url=' +
                        self.image.url)

    def open_tineye(self):
        webbrowser.open('http://tineye.com/search?url=' + self.image.url)

    def set_picture(self):
        filename = 'images/' + '_'.join(self.image.url.split('/')[-2:])
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

    def __init__(self, index, result_container):
        self.index = index
        self.result_container = result_container
        super().__init__()

    def run(self):
        self.update_status.emit('Downloading image list.')
        self.result_container.extend(list(parse_review_page(self.index)))
        self.update_status.emit('Done.')


class SCPIRT(QtGui.QMainWindow):

    def __init__(self):
        super().__init__()
        self.ui = scpirt_ui.Ui_MainWindow()
        self.ui.setupUi(self)
        self.show()
        self.ui.save.triggered.connect(self.save)
        for i in range(10):
            action = getattr(self.ui, 'scp{}'.format(i))
            action.triggered.connect(lambda i=i: self.get_list(i + 1))

    def get_list(self, index):
        self.current_review_page = index
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

    def save(self):
        print('||~ Image||~ Page||~ Source||~ Status||~ Notes||')
        for img in self.images:
            print(img.row_code())
        #p = sandbox('image-review-' + str(self.current_review_page))
        #p.edit(source)


def parse_review_page(index):
    p = sandbox('image-review-' + str(index))
    tables = bs4.BeautifulSoup(p.html)(class_='wiki-content-table')
    rows = [i('td') for t in tables for i in t('tr')[1:]]
    for row in rows:
        url = row[0].find('img')['src']
        page = row[1].a['href']
        user = row[1].span.a.text if row[1].select('span a') else None
        source = row[3].a['href'] if row[3]('a') else None
        status, notes = [row[i].text for i in (4, 5)]
        yield Image(url, page, user, source, status, notes)


def generate_stats():
    idxs = range(1, 28)
    data = []
    for i in idxs:
        data.extend(list(parse_review_page(i)))
    print('Review pages:', len(idxs))
    print('Images indexed:', len(data))
    print('Reviewed:', len(data) - [i['status'] for i in data].count(None))
    for status in [
            'PUBLIC DOMAIN', 'REPLACED', 'SOURCE UNKNOWN', 'UNABLE TO CONTACT',
            'PERMISSION DENIED', 'BY-SA CC', 'BY-NC-SA CC',
            'PERMISSION GRANTED', 'AWAITING REPLY', 'PERMANENTLY REMOVED']:
        print(status + ':', [i['status'] for i in data].count(status))


if __name__ == '__main__':
    app = QtGui.QApplication('')
    SCPIRT()
    app.exec_()
