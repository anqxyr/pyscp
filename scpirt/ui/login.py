# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'login.ui'
#
# Created: Tue Jun 16 21:04:12 2015
#      by: pyside-uic 0.2.15 running on PySide 1.2.1
#
# WARNING! All changes made in this file will be lost!

from PySide import QtCore, QtGui

class Ui_LoginForm(object):
    def setupUi(self, LoginForm):
        LoginForm.setObjectName("LoginForm")
        LoginForm.resize(374, 86)
        LoginForm.setMaximumSize(QtCore.QSize(16777215, 86))
        self.gridLayout = QtGui.QGridLayout(LoginForm)
        self.gridLayout.setObjectName("gridLayout")
        self.name_label = QtGui.QLabel(LoginForm)
        self.name_label.setObjectName("name_label")
        self.gridLayout.addWidget(self.name_label, 0, 0, 1, 1)
        self.name = QtGui.QLineEdit(LoginForm)
        self.name.setObjectName("name")
        self.gridLayout.addWidget(self.name, 0, 1, 1, 1)
        self.password_label = QtGui.QLabel(LoginForm)
        self.password_label.setObjectName("password_label")
        self.gridLayout.addWidget(self.password_label, 1, 0, 1, 1)
        self.password = QtGui.QLineEdit(LoginForm)
        self.password.setObjectName("password")
        self.gridLayout.addWidget(self.password, 1, 1, 1, 1)
        self.ok_button = QtGui.QPushButton(LoginForm)
        self.ok_button.setFlat(False)
        self.ok_button.setObjectName("ok_button")
        self.gridLayout.addWidget(self.ok_button, 2, 0, 1, 2)

        self.retranslateUi(LoginForm)
        QtCore.QObject.connect(self.ok_button, QtCore.SIGNAL("clicked()"), LoginForm.hide)
        QtCore.QMetaObject.connectSlotsByName(LoginForm)

    def retranslateUi(self, LoginForm):
        LoginForm.setWindowTitle(QtGui.QApplication.translate("LoginForm", "Login to Wikidot", None, QtGui.QApplication.UnicodeUTF8))
        self.name_label.setText(QtGui.QApplication.translate("LoginForm", "Username", None, QtGui.QApplication.UnicodeUTF8))
        self.password_label.setText(QtGui.QApplication.translate("LoginForm", "Password:", None, QtGui.QApplication.UnicodeUTF8))
        self.ok_button.setText(QtGui.QApplication.translate("LoginForm", "OK", None, QtGui.QApplication.UnicodeUTF8))

