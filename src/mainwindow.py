# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.9.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QApplication, QFrame,
    QGridLayout, QHeaderView, QLabel, QMainWindow,
    QMenuBar, QPushButton, QScrollArea, QSizePolicy,
    QStatusBar, QTableWidget, QTableWidgetItem, QTextBrowser,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1160, 631)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.gridLayout_12 = QGridLayout(self.centralwidget)
        self.gridLayout_12.setObjectName(u"gridLayout_12")
        self.viewer_frame = QFrame(self.centralwidget)
        self.viewer_frame.setObjectName(u"viewer_frame")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.viewer_frame.sizePolicy().hasHeightForWidth())
        self.viewer_frame.setSizePolicy(sizePolicy)
        self.viewer_frame.setMinimumSize(QSize(300, 0))
        self.viewer_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.viewer_frame.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout_22 = QGridLayout(self.viewer_frame)
        self.gridLayout_22.setObjectName(u"gridLayout_22")
        self.image_viewer = QLabel(self.viewer_frame)
        self.image_viewer.setObjectName(u"image_viewer")

        self.gridLayout_22.addWidget(self.image_viewer, 4, 0, 1, 1)

        self.plot_frame = QWidget(self.viewer_frame)
        self.plot_frame.setObjectName(u"plot_frame")
        self.verticalLayout = QVBoxLayout(self.plot_frame)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.plot_widget = PlotWidget(self.plot_frame)
        self.plot_widget.setObjectName(u"plot_widget")
        sizePolicy.setHeightForWidth(self.plot_widget.sizePolicy().hasHeightForWidth())
        self.plot_widget.setSizePolicy(sizePolicy)

        self.verticalLayout.addWidget(self.plot_widget)


        self.gridLayout_22.addWidget(self.plot_frame, 3, 0, 1, 1)

        self.pdf_viewer = QWidget(self.viewer_frame)
        self.pdf_viewer.setObjectName(u"pdf_viewer")

        self.gridLayout_22.addWidget(self.pdf_viewer, 1, 0, 1, 1)

        self.video_player = QWidget(self.viewer_frame)
        self.video_player.setObjectName(u"video_player")

        self.gridLayout_22.addWidget(self.video_player, 0, 0, 1, 1)

        self.text_viewer = QTextBrowser(self.viewer_frame)
        self.text_viewer.setObjectName(u"text_viewer")

        self.gridLayout_22.addWidget(self.text_viewer, 2, 0, 1, 1)


        self.gridLayout_12.addWidget(self.viewer_frame, 1, 1, 4, 1)

        self.scrollArea_3 = QScrollArea(self.centralwidget)
        self.scrollArea_3.setObjectName(u"scrollArea_3")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.scrollArea_3.sizePolicy().hasHeightForWidth())
        self.scrollArea_3.setSizePolicy(sizePolicy1)
        self.scrollArea_3.setMaximumSize(QSize(16777215, 16777215))
        self.scrollArea_3.setWidgetResizable(True)
        self.scrollAreaWidgetContents_3 = QWidget()
        self.scrollAreaWidgetContents_3.setObjectName(u"scrollAreaWidgetContents_3")
        self.scrollAreaWidgetContents_3.setGeometry(QRect(0, 0, 434, 88))
        self.gridLayout_23 = QGridLayout(self.scrollAreaWidgetContents_3)
        self.gridLayout_23.setObjectName(u"gridLayout_23")
        self.log = QTextBrowser(self.scrollAreaWidgetContents_3)
        self.log.setObjectName(u"log")
        sizePolicy1.setHeightForWidth(self.log.sizePolicy().hasHeightForWidth())
        self.log.setSizePolicy(sizePolicy1)
        self.log.setMaximumSize(QSize(16777215, 16777215))
        font = QFont()
        font.setPointSize(8)
        self.log.setFont(font)

        self.gridLayout_23.addWidget(self.log, 0, 0, 1, 1)

        self.scrollArea_3.setWidget(self.scrollAreaWidgetContents_3)

        self.gridLayout_12.addWidget(self.scrollArea_3, 1, 2, 1, 1)

        self.frame_15 = QFrame(self.centralwidget)
        self.frame_15.setObjectName(u"frame_15")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.frame_15.sizePolicy().hasHeightForWidth())
        self.frame_15.setSizePolicy(sizePolicy2)
        self.frame_15.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_15.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout_10 = QGridLayout(self.frame_15)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.btn_load_config = QPushButton(self.frame_15)
        self.btn_load_config.setObjectName(u"btn_load_config")
        self.btn_load_config.setMaximumSize(QSize(120, 16777215))

        self.gridLayout_10.addWidget(self.btn_load_config, 3, 1, 1, 1)

        self.btn_save_config = QPushButton(self.frame_15)
        self.btn_save_config.setObjectName(u"btn_save_config")
        self.btn_save_config.setMaximumSize(QSize(120, 16777215))

        self.gridLayout_10.addWidget(self.btn_save_config, 3, 3, 1, 1)

        self.btn_execute_scripts = QPushButton(self.frame_15)
        self.btn_execute_scripts.setObjectName(u"btn_execute_scripts")
        self.btn_execute_scripts.setMaximumSize(QSize(120, 16777215))

        self.gridLayout_10.addWidget(self.btn_execute_scripts, 3, 4, 1, 1)

        self.btn_stop_scripts = QPushButton(self.frame_15)
        self.btn_stop_scripts.setObjectName(u"btn_stop_scripts")
        self.btn_stop_scripts.setEnabled(False)
        self.btn_stop_scripts.setMaximumSize(QSize(120, 16777215))

        self.gridLayout_10.addWidget(self.btn_stop_scripts, 3, 5, 1, 1)


        self.gridLayout_12.addWidget(self.frame_15, 2, 2, 1, 1)

        self.frame_18 = QFrame(self.centralwidget)
        self.frame_18.setObjectName(u"frame_18")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.frame_18.sizePolicy().hasHeightForWidth())
        self.frame_18.setSizePolicy(sizePolicy3)
        self.frame_18.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_18.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout_21 = QGridLayout(self.frame_18)
        self.gridLayout_21.setObjectName(u"gridLayout_21")
        self.btn_darkmode = QPushButton(self.frame_18)
        self.btn_darkmode.setObjectName(u"btn_darkmode")
        self.btn_darkmode.setMaximumSize(QSize(150, 16777215))

        self.gridLayout_21.addWidget(self.btn_darkmode, 2, 0, 1, 1)

        self.btn_open_folder = QPushButton(self.frame_18)
        self.btn_open_folder.setObjectName(u"btn_open_folder")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.btn_open_folder.sizePolicy().hasHeightForWidth())
        self.btn_open_folder.setSizePolicy(sizePolicy4)
        self.btn_open_folder.setMaximumSize(QSize(150, 16777215))
        self.btn_open_folder.setFont(font)

        self.gridLayout_21.addWidget(self.btn_open_folder, 1, 0, 1, 1)

        self.btn_refresh = QPushButton(self.frame_18)
        self.btn_refresh.setObjectName(u"btn_refresh")
        sizePolicy4.setHeightForWidth(self.btn_refresh.sizePolicy().hasHeightForWidth())
        self.btn_refresh.setSizePolicy(sizePolicy4)
        self.btn_refresh.setMaximumSize(QSize(150, 16777215))
        self.btn_refresh.setFont(font)

        self.gridLayout_21.addWidget(self.btn_refresh, 0, 0, 1, 1)


        self.gridLayout_12.addWidget(self.frame_18, 4, 0, 1, 1)

        self.file_viewer = QTreeWidget(self.centralwidget)
        __qtreewidgetitem = QTreeWidgetItem(self.file_viewer)
        QTreeWidgetItem(__qtreewidgetitem)
        __qtreewidgetitem1 = QTreeWidgetItem(__qtreewidgetitem)
        QTreeWidgetItem(__qtreewidgetitem1)
        QTreeWidgetItem(__qtreewidgetitem1)
        QTreeWidgetItem(__qtreewidgetitem1)
        QTreeWidgetItem(__qtreewidgetitem1)
        QTreeWidgetItem(__qtreewidgetitem)
        QTreeWidgetItem(__qtreewidgetitem)
        self.file_viewer.setObjectName(u"file_viewer")
        sizePolicy1.setHeightForWidth(self.file_viewer.sizePolicy().hasHeightForWidth())
        self.file_viewer.setSizePolicy(sizePolicy1)
        self.file_viewer.setFont(font)

        self.gridLayout_12.addWidget(self.file_viewer, 1, 0, 3, 1)

        self.table_data_columns = QTableWidget(self.centralwidget)
        if (self.table_data_columns.columnCount() < 4):
            self.table_data_columns.setColumnCount(4)
        __qtablewidgetitem = QTableWidgetItem()
        self.table_data_columns.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.table_data_columns.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.table_data_columns.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.table_data_columns.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        if (self.table_data_columns.rowCount() < 22):
            self.table_data_columns.setRowCount(22)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.table_data_columns.setItem(0, 0, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.table_data_columns.setItem(0, 1, __qtablewidgetitem5)
        __qtablewidgetitem6 = QTableWidgetItem()
        self.table_data_columns.setItem(0, 2, __qtablewidgetitem6)
        __qtablewidgetitem7 = QTableWidgetItem()
        self.table_data_columns.setItem(1, 0, __qtablewidgetitem7)
        __qtablewidgetitem8 = QTableWidgetItem()
        self.table_data_columns.setItem(1, 1, __qtablewidgetitem8)
        __qtablewidgetitem9 = QTableWidgetItem()
        self.table_data_columns.setItem(1, 2, __qtablewidgetitem9)
        __qtablewidgetitem10 = QTableWidgetItem()
        self.table_data_columns.setItem(4, 0, __qtablewidgetitem10)
        __qtablewidgetitem11 = QTableWidgetItem()
        self.table_data_columns.setItem(4, 1, __qtablewidgetitem11)
        __qtablewidgetitem12 = QTableWidgetItem()
        self.table_data_columns.setItem(4, 2, __qtablewidgetitem12)
        __qtablewidgetitem13 = QTableWidgetItem()
        self.table_data_columns.setItem(5, 0, __qtablewidgetitem13)
        __qtablewidgetitem14 = QTableWidgetItem()
        self.table_data_columns.setItem(5, 1, __qtablewidgetitem14)
        __qtablewidgetitem15 = QTableWidgetItem()
        self.table_data_columns.setItem(5, 2, __qtablewidgetitem15)
        __qtablewidgetitem16 = QTableWidgetItem()
        self.table_data_columns.setItem(6, 0, __qtablewidgetitem16)
        __qtablewidgetitem17 = QTableWidgetItem()
        self.table_data_columns.setItem(6, 1, __qtablewidgetitem17)
        __qtablewidgetitem18 = QTableWidgetItem()
        self.table_data_columns.setItem(6, 2, __qtablewidgetitem18)
        __qtablewidgetitem19 = QTableWidgetItem()
        self.table_data_columns.setItem(7, 0, __qtablewidgetitem19)
        __qtablewidgetitem20 = QTableWidgetItem()
        self.table_data_columns.setItem(7, 1, __qtablewidgetitem20)
        __qtablewidgetitem21 = QTableWidgetItem()
        self.table_data_columns.setItem(7, 2, __qtablewidgetitem21)
        __qtablewidgetitem22 = QTableWidgetItem()
        self.table_data_columns.setItem(8, 0, __qtablewidgetitem22)
        __qtablewidgetitem23 = QTableWidgetItem()
        self.table_data_columns.setItem(8, 1, __qtablewidgetitem23)
        __qtablewidgetitem24 = QTableWidgetItem()
        self.table_data_columns.setItem(8, 2, __qtablewidgetitem24)
        __qtablewidgetitem25 = QTableWidgetItem()
        self.table_data_columns.setItem(9, 0, __qtablewidgetitem25)
        __qtablewidgetitem26 = QTableWidgetItem()
        self.table_data_columns.setItem(9, 1, __qtablewidgetitem26)
        __qtablewidgetitem27 = QTableWidgetItem()
        self.table_data_columns.setItem(9, 2, __qtablewidgetitem27)
        __qtablewidgetitem28 = QTableWidgetItem()
        self.table_data_columns.setItem(10, 0, __qtablewidgetitem28)
        __qtablewidgetitem29 = QTableWidgetItem()
        self.table_data_columns.setItem(10, 1, __qtablewidgetitem29)
        __qtablewidgetitem30 = QTableWidgetItem()
        self.table_data_columns.setItem(10, 2, __qtablewidgetitem30)
        __qtablewidgetitem31 = QTableWidgetItem()
        self.table_data_columns.setItem(11, 0, __qtablewidgetitem31)
        __qtablewidgetitem32 = QTableWidgetItem()
        self.table_data_columns.setItem(11, 1, __qtablewidgetitem32)
        __qtablewidgetitem33 = QTableWidgetItem()
        self.table_data_columns.setItem(11, 2, __qtablewidgetitem33)
        __qtablewidgetitem34 = QTableWidgetItem()
        self.table_data_columns.setItem(12, 0, __qtablewidgetitem34)
        __qtablewidgetitem35 = QTableWidgetItem()
        self.table_data_columns.setItem(12, 1, __qtablewidgetitem35)
        __qtablewidgetitem36 = QTableWidgetItem()
        self.table_data_columns.setItem(12, 2, __qtablewidgetitem36)
        __qtablewidgetitem37 = QTableWidgetItem()
        self.table_data_columns.setItem(13, 0, __qtablewidgetitem37)
        __qtablewidgetitem38 = QTableWidgetItem()
        self.table_data_columns.setItem(13, 1, __qtablewidgetitem38)
        __qtablewidgetitem39 = QTableWidgetItem()
        self.table_data_columns.setItem(13, 2, __qtablewidgetitem39)
        __qtablewidgetitem40 = QTableWidgetItem()
        self.table_data_columns.setItem(14, 0, __qtablewidgetitem40)
        __qtablewidgetitem41 = QTableWidgetItem()
        self.table_data_columns.setItem(14, 1, __qtablewidgetitem41)
        __qtablewidgetitem42 = QTableWidgetItem()
        self.table_data_columns.setItem(14, 2, __qtablewidgetitem42)
        __qtablewidgetitem43 = QTableWidgetItem()
        self.table_data_columns.setItem(15, 0, __qtablewidgetitem43)
        __qtablewidgetitem44 = QTableWidgetItem()
        self.table_data_columns.setItem(15, 1, __qtablewidgetitem44)
        __qtablewidgetitem45 = QTableWidgetItem()
        self.table_data_columns.setItem(15, 2, __qtablewidgetitem45)
        __qtablewidgetitem46 = QTableWidgetItem()
        self.table_data_columns.setItem(16, 0, __qtablewidgetitem46)
        __qtablewidgetitem47 = QTableWidgetItem()
        self.table_data_columns.setItem(16, 1, __qtablewidgetitem47)
        __qtablewidgetitem48 = QTableWidgetItem()
        self.table_data_columns.setItem(16, 2, __qtablewidgetitem48)
        __qtablewidgetitem49 = QTableWidgetItem()
        self.table_data_columns.setItem(17, 0, __qtablewidgetitem49)
        __qtablewidgetitem50 = QTableWidgetItem()
        self.table_data_columns.setItem(17, 1, __qtablewidgetitem50)
        __qtablewidgetitem51 = QTableWidgetItem()
        self.table_data_columns.setItem(17, 2, __qtablewidgetitem51)
        __qtablewidgetitem52 = QTableWidgetItem()
        self.table_data_columns.setItem(18, 0, __qtablewidgetitem52)
        __qtablewidgetitem53 = QTableWidgetItem()
        self.table_data_columns.setItem(18, 1, __qtablewidgetitem53)
        __qtablewidgetitem54 = QTableWidgetItem()
        self.table_data_columns.setItem(18, 2, __qtablewidgetitem54)
        __qtablewidgetitem55 = QTableWidgetItem()
        self.table_data_columns.setItem(19, 0, __qtablewidgetitem55)
        __qtablewidgetitem56 = QTableWidgetItem()
        self.table_data_columns.setItem(19, 1, __qtablewidgetitem56)
        __qtablewidgetitem57 = QTableWidgetItem()
        self.table_data_columns.setItem(19, 2, __qtablewidgetitem57)
        __qtablewidgetitem58 = QTableWidgetItem()
        self.table_data_columns.setItem(20, 0, __qtablewidgetitem58)
        __qtablewidgetitem59 = QTableWidgetItem()
        self.table_data_columns.setItem(20, 1, __qtablewidgetitem59)
        __qtablewidgetitem60 = QTableWidgetItem()
        self.table_data_columns.setItem(20, 2, __qtablewidgetitem60)
        __qtablewidgetitem61 = QTableWidgetItem()
        self.table_data_columns.setItem(21, 0, __qtablewidgetitem61)
        __qtablewidgetitem62 = QTableWidgetItem()
        self.table_data_columns.setItem(21, 1, __qtablewidgetitem62)
        __qtablewidgetitem63 = QTableWidgetItem()
        self.table_data_columns.setItem(21, 2, __qtablewidgetitem63)
        self.table_data_columns.setObjectName(u"table_data_columns")
        sizePolicy1.setHeightForWidth(self.table_data_columns.sizePolicy().hasHeightForWidth())
        self.table_data_columns.setSizePolicy(sizePolicy1)
        self.table_data_columns.setMinimumSize(QSize(450, 250))
        self.table_data_columns.setMaximumSize(QSize(500, 16777215))
        self.table_data_columns.setFont(font)
        self.table_data_columns.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.table_data_columns.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_data_columns.setAlternatingRowColors(False)
        self.table_data_columns.setSortingEnabled(True)
        self.table_data_columns.horizontalHeader().setCascadingSectionResizes(True)
        self.table_data_columns.horizontalHeader().setMinimumSectionSize(0)
        self.table_data_columns.horizontalHeader().setDefaultSectionSize(100)
        self.table_data_columns.horizontalHeader().setHighlightSections(False)
        self.table_data_columns.horizontalHeader().setProperty(u"showSortIndicator", True)
        self.table_data_columns.horizontalHeader().setStretchLastSection(True)
        self.table_data_columns.verticalHeader().setVisible(False)
        self.table_data_columns.verticalHeader().setCascadingSectionResizes(False)
        self.table_data_columns.verticalHeader().setDefaultSectionSize(40)
        self.table_data_columns.verticalHeader().setHighlightSections(False)
        self.table_data_columns.verticalHeader().setProperty(u"showSortIndicator", False)
        self.table_data_columns.verticalHeader().setStretchLastSection(True)

        self.gridLayout_12.addWidget(self.table_data_columns, 3, 2, 2, 1)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1160, 21))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)
        QWidget.setTabOrder(self.log, self.btn_load_config)
        QWidget.setTabOrder(self.btn_load_config, self.btn_save_config)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.image_viewer.setText("")
        self.btn_load_config.setText(QCoreApplication.translate("MainWindow", u"Cargar \n"
"Configuraci\u00f3n", None))
        self.btn_save_config.setText(QCoreApplication.translate("MainWindow", u"Guardar \n"
"Configuraci\u00f3n", None))
        self.btn_execute_scripts.setText(QCoreApplication.translate("MainWindow", u"Ejecutar \n"
"Seleccionados", None))
        self.btn_stop_scripts.setText(QCoreApplication.translate("MainWindow", u"Detener", None))
        self.btn_darkmode.setText(QCoreApplication.translate("MainWindow", u"\u2600\ufe0f", None))
        self.btn_open_folder.setText(QCoreApplication.translate("MainWindow", u"Seleccionar\n"
"Carpeta", None))
        self.btn_refresh.setText(QCoreApplication.translate("MainWindow", u"Refrescar\n"
"Carpeta", None))
        ___qtreewidgetitem = self.file_viewer.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"Name", None));

        __sortingEnabled = self.file_viewer.isSortingEnabled()
        self.file_viewer.setSortingEnabled(False)
        ___qtreewidgetitem1 = self.file_viewer.topLevelItem(0)
        ___qtreewidgetitem1.setText(0, QCoreApplication.translate("MainWindow", u"CWD", None));
        ___qtreewidgetitem2 = ___qtreewidgetitem1.child(0)
        ___qtreewidgetitem2.setText(0, QCoreApplication.translate("MainWindow", u"Folder A", None));
        ___qtreewidgetitem3 = ___qtreewidgetitem1.child(1)
        ___qtreewidgetitem3.setText(0, QCoreApplication.translate("MainWindow", u"Folder B", None));
        ___qtreewidgetitem4 = ___qtreewidgetitem3.child(0)
        ___qtreewidgetitem4.setText(0, QCoreApplication.translate("MainWindow", u"datafile_1.csv", None));
        ___qtreewidgetitem5 = ___qtreewidgetitem3.child(1)
        ___qtreewidgetitem5.setText(0, QCoreApplication.translate("MainWindow", u"datafile_2.csv", None));
        ___qtreewidgetitem6 = ___qtreewidgetitem3.child(2)
        ___qtreewidgetitem6.setText(0, QCoreApplication.translate("MainWindow", u"model_A.pkl", None));
        ___qtreewidgetitem7 = ___qtreewidgetitem3.child(3)
        ___qtreewidgetitem7.setText(0, QCoreApplication.translate("MainWindow", u"model_B.pkl", None));
        ___qtreewidgetitem8 = ___qtreewidgetitem1.child(2)
        ___qtreewidgetitem8.setText(0, QCoreApplication.translate("MainWindow", u"Folder C", None));
        ___qtreewidgetitem9 = ___qtreewidgetitem1.child(3)
        ___qtreewidgetitem9.setText(0, QCoreApplication.translate("MainWindow", u"Folder D", None));
        self.file_viewer.setSortingEnabled(__sortingEnabled)

        ___qtablewidgetitem = self.table_data_columns.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("MainWindow", u"Script", None));
        ___qtablewidgetitem1 = self.table_data_columns.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("MainWindow", u"Configurado", None));
        ___qtablewidgetitem2 = self.table_data_columns.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("MainWindow", u"Seleccion", None));
        ___qtablewidgetitem3 = self.table_data_columns.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("MainWindow", u"Orden", None));

        __sortingEnabled1 = self.table_data_columns.isSortingEnabled()
        self.table_data_columns.setSortingEnabled(False)
        ___qtablewidgetitem4 = self.table_data_columns.item(0, 0)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("MainWindow", u"process_video.py", None));
        ___qtablewidgetitem5 = self.table_data_columns.item(0, 1)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("MainWindow", u"Si", None));
        ___qtablewidgetitem6 = self.table_data_columns.item(1, 0)
        ___qtablewidgetitem6.setText(QCoreApplication.translate("MainWindow", u"clean_signals.py", None));
        ___qtablewidgetitem7 = self.table_data_columns.item(1, 1)
        ___qtablewidgetitem7.setText(QCoreApplication.translate("MainWindow", u"No", None));
        self.table_data_columns.setSortingEnabled(__sortingEnabled1)

    # retranslateUi

