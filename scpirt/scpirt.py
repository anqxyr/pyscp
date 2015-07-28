#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import pathlib
import pyscp
import logging
import webbrowser
import bs4

import ui

from PySide import QtGui, QtCore

###############################################################################
# Global Constants And Variables
###############################################################################

log = logging.getLogger(__name__)
req = pyscp.wikidot.InsistentRequest()
sandbox = pyscp.wikidot.Wiki('scpsandbox2')
authenticated = False

###############################################################################


class Image:

    statuses = (
        'PUBLIC DOMAIN',
        'BY-SA CC',
        'BY-NC-SA CC',
        'PERMISSION GRANTED',
        'REPLACED',
        'AWAITING REPLY',
        'SOURCE UNKNOWN',
        'UNABLE TO CONTACT',
        'PERMISSION DENIED',
        'PERMANENTLY REMOVED')

    def __init__(self, url, page, user, source, status, notes):
        self.url, self.page, self.user = url, page, user
        self.source, self.notes = source, notes
        self.status = status if status.strip() else None
        if self.status and self.status not in self.statuses:
            self.status = 'OTHER'
        self.attribute, self.remove = False, False

    def status_index(self):
        if self.status not in self.statuses:
            return None
        return self.statuses.index(self.status)

    def color(self):
        index = self.status_index()
        if index is None:
            return None
        if index < 2:
            color = 'green'
        elif index < 6:
            color = 'blue'
        else:
            color = 'darkred'
        return color

    def row_code(self):
        pic = '[[image {} width="50px"]]'.format(self.url)
        page = '[{} {}]'.format(self.page, self.page.split('/')[-1])
        user = '[[user {}]]'.format(self.user) if self.user else ' '
        source = '[{} source]'.format(self.source) if self.source else ' '
        status = '**{}**'.format(self.status) if self.status else ' '
        if self.status_index() is not None:
            status = '##{}|{}##'.format(self.color(), status)
        notes = self.notes.replace('\n', ' _\n') if self.notes else ' '
        return '||{}||{} _\n{}||{}||{}||{}||'.format(
            pic, page, user, source, status, notes)


###############################################################################


class Imagebox(QtGui.QWidget):

    def __init__(self, image):
        super().__init__()
        self.ui = ui.ImageBox()
        self.ui.setupUi(self)
        self.ui.status.wheelEvent = lambda x: self.parentWidget().wheelEvent(x)
        self.ui.google.clicked.connect(self.open_google)
        self.ui.tineye.clicked.connect(self.open_tineye)
        self.ui.picture.addAction(self.ui.list_delete)
        self.ui.picture.addAction(self.ui.email)
        self.load_image(image)
        self.ui.status.currentIndexChanged.connect(self.change_status)
        self.ui.source.textChanged.connect(self.change_source)
        self.ui.notes.textChanged.connect(self.change_notes)

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

    def change_source(self):
        self.image.source = self.ui.source.text()

    def change_notes(self):
        self.image.notes = self.ui.notes.toPlainText()

    def open_google(self):
        webbrowser.open('https://www.google.com/searchbyimage?&image_url=' +
                        self.image.url)

    def open_tineye(self):
        webbrowser.open('http://tineye.com/search?url=' + self.image.url)

    def set_picture(self):
        filename = 'images/' + '_'.join(self.image.url.split('/')[-2:])
        self.ui.picture.setPixmap(QtGui.QPixmap(filename))


class LoginForm(QtGui.QDialog, ui.LoginForm):

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.ok_button.clicked.connect(self.login)

    def login(self):
        sandbox.auth(self.name.text(), self.password.text())
        global authenticated
        authenticated = True
        self.close()


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
        self.ui = ui.MainWindow()
        self.ui.setupUi(self)
        self.show()
        self.ui.save.triggered.connect(self.save)
        self.ui.login.triggered.connect(self.login)
        for i in range(30):
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

    def login(self):
        if authenticated:
            return True
        form = LoginForm()
        form.exec()
        return authenticated

    def save(self):
        if not self.login():
            return
        source = ['||~ Image||~ Page||~ Source||~ Status||~ Notes||']
        source.extend(i.row_code() for i in self.images)
        source = '\n'.join(source)
        p = sandbox('image-review-' + str(self.current_review_page))
        p.edit(source, comment='SCPIRT automated edit')


def parse_review_page(index):
    p = sandbox('image-review-' + str(index))
    tables = bs4.BeautifulSoup(p.html)(class_='wiki-content-table')
    rows = [i('td') for t in tables for i in t('tr')[1:]]
    for row in rows:
        url = row[0].find('img')['src']
        page = row[1].a['href']
        user = row[1].span.a.text if row[1].select('span a') else None
        source = row[2].a['href'] if row[2]('a') else None
        status, notes = [row[i].text for i in (3, 4)]
        yield Image(url, page, user, source, status, notes)


def generate_stats():
    idxs = range(1, 36)
    data = []
    for i in idxs:
        data.extend(list(parse_review_page(i)))
    print('Review pages:', len(idxs))
    print('Images indexed:', len(data))
    statuses = [i.status for i in data]
    print('Reviewed:', len(data) - statuses.count(None))
    for status in {i for i in statuses if i}:
        print(status + ':', statuses.count(status))


if __name__ == '__main__':
    generate_stats()
    exit()
    app = QtGui.QApplication('')
    SCPIRT()
    app.exec_()
