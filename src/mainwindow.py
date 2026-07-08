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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMenuBar,
    QPushButton, QSizePolicy, QSpacerItem, QSplitter,
    QStatusBar, QTableWidget, QTableWidgetItem, QTextBrowser,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1280, 760)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.central_layout = QVBoxLayout(self.centralwidget)
        self.central_layout.setObjectName(u"central_layout")
        self.central_layout.setContentsMargins(8, 8, 8, 8)
        self.main_splitter = QSplitter(self.centralwidget)
        self.main_splitter.setObjectName(u"main_splitter")
        self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(6)
        self.main_splitter.setChildrenCollapsible(False)
        self.explorer_panel = QWidget(self.main_splitter)
        self.explorer_panel.setObjectName(u"explorer_panel")
        self.explorer_panel.setMinimumSize(QSize(220, 0))
        self.explorer_layout = QVBoxLayout(self.explorer_panel)
        self.explorer_layout.setSpacing(6)
        self.explorer_layout.setObjectName(u"explorer_layout")
        self.explorer_layout.setContentsMargins(0, 0, 0, 0)
        self.explorer_header_layout = QHBoxLayout()
        self.explorer_header_layout.setObjectName(u"explorer_header_layout")
        self.lbl_explorer_title = QLabel(self.explorer_panel)
        self.lbl_explorer_title.setObjectName(u"lbl_explorer_title")

        self.explorer_header_layout.addWidget(self.lbl_explorer_title)

        self.explorer_header_spacer = QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.explorer_header_layout.addItem(self.explorer_header_spacer)

        self.btn_refresh = QPushButton(self.explorer_panel)
        self.btn_refresh.setObjectName(u"btn_refresh")

        self.explorer_header_layout.addWidget(self.btn_refresh)


        self.explorer_layout.addLayout(self.explorer_header_layout)

        self.file_viewer = QTreeWidget(self.explorer_panel)
        self.file_viewer.setObjectName(u"file_viewer")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.file_viewer.sizePolicy().hasHeightForWidth())
        self.file_viewer.setSizePolicy(sizePolicy)
        self.file_viewer.setIndentation(14)
        self.file_viewer.setAnimated(True)

        self.explorer_layout.addWidget(self.file_viewer)

        self.btn_open_folder = QPushButton(self.explorer_panel)
        self.btn_open_folder.setObjectName(u"btn_open_folder")

        self.explorer_layout.addWidget(self.btn_open_folder)

        self.main_splitter.addWidget(self.explorer_panel)
        self.viewer_frame = QFrame(self.main_splitter)
        self.viewer_frame.setObjectName(u"viewer_frame")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(1)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.viewer_frame.sizePolicy().hasHeightForWidth())
        self.viewer_frame.setSizePolicy(sizePolicy1)
        self.viewer_frame.setMinimumSize(QSize(320, 0))
        self.viewer_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.viewer_frame.setFrameShadow(QFrame.Shadow.Plain)
        self.viewer_layout = QVBoxLayout(self.viewer_frame)
        self.viewer_layout.setObjectName(u"viewer_layout")
        self.viewer_layout.setContentsMargins(6, 6, 6, 6)
        self.video_player = QWidget(self.viewer_frame)
        self.video_player.setObjectName(u"video_player")

        self.viewer_layout.addWidget(self.video_player)

        self.pdf_viewer = QWidget(self.viewer_frame)
        self.pdf_viewer.setObjectName(u"pdf_viewer")

        self.viewer_layout.addWidget(self.pdf_viewer)

        self.text_viewer = QTextBrowser(self.viewer_frame)
        self.text_viewer.setObjectName(u"text_viewer")

        self.viewer_layout.addWidget(self.text_viewer)

        self.plot_frame = QWidget(self.viewer_frame)
        self.plot_frame.setObjectName(u"plot_frame")
        self.verticalLayout = QVBoxLayout(self.plot_frame)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = PlotWidget(self.plot_frame)
        self.plot_widget.setObjectName(u"plot_widget")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.plot_widget.sizePolicy().hasHeightForWidth())
        self.plot_widget.setSizePolicy(sizePolicy2)

        self.verticalLayout.addWidget(self.plot_widget)


        self.viewer_layout.addWidget(self.plot_frame)

        self.image_viewer = QLabel(self.viewer_frame)
        self.image_viewer.setObjectName(u"image_viewer")

        self.viewer_layout.addWidget(self.image_viewer)

        self.main_splitter.addWidget(self.viewer_frame)
        self.right_splitter = QSplitter(self.main_splitter)
        self.right_splitter.setObjectName(u"right_splitter")
        self.right_splitter.setOrientation(Qt.Orientation.Vertical)
        self.right_splitter.setHandleWidth(6)
        self.right_splitter.setChildrenCollapsible(False)
        self.scripts_panel = QWidget(self.right_splitter)
        self.scripts_panel.setObjectName(u"scripts_panel")
        self.scripts_panel.setMinimumSize(QSize(420, 0))
        self.scripts_layout = QVBoxLayout(self.scripts_panel)
        self.scripts_layout.setSpacing(6)
        self.scripts_layout.setObjectName(u"scripts_layout")
        self.scripts_layout.setContentsMargins(0, 0, 0, 0)
        self.scripts_header_layout = QHBoxLayout()
        self.scripts_header_layout.setObjectName(u"scripts_header_layout")
        self.lbl_scripts_title = QLabel(self.scripts_panel)
        self.lbl_scripts_title.setObjectName(u"lbl_scripts_title")

        self.scripts_header_layout.addWidget(self.lbl_scripts_title)

        self.scripts_header_spacer = QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.scripts_header_layout.addItem(self.scripts_header_spacer)

        self.btn_darkmode = QPushButton(self.scripts_panel)
        self.btn_darkmode.setObjectName(u"btn_darkmode")

        self.scripts_header_layout.addWidget(self.btn_darkmode)


        self.scripts_layout.addLayout(self.scripts_header_layout)

        self.table_data_columns = QTableWidget(self.scripts_panel)
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
        self.table_data_columns.setObjectName(u"table_data_columns")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(1)
        sizePolicy3.setHeightForWidth(self.table_data_columns.sizePolicy().hasHeightForWidth())
        self.table_data_columns.setSizePolicy(sizePolicy3)
        self.table_data_columns.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_data_columns.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_data_columns.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_data_columns.setShowGrid(False)
        self.table_data_columns.horizontalHeader().setMinimumSectionSize(0)
        self.table_data_columns.horizontalHeader().setDefaultSectionSize(110)
        self.table_data_columns.horizontalHeader().setHighlightSections(False)
        self.table_data_columns.horizontalHeader().setStretchLastSection(True)
        self.table_data_columns.verticalHeader().setVisible(False)
        self.table_data_columns.verticalHeader().setDefaultSectionSize(36)

        self.scripts_layout.addWidget(self.table_data_columns)

        self.scripts_actions_layout = QHBoxLayout()
        self.scripts_actions_layout.setSpacing(6)
        self.scripts_actions_layout.setObjectName(u"scripts_actions_layout")
        self.btn_load_config = QPushButton(self.scripts_panel)
        self.btn_load_config.setObjectName(u"btn_load_config")

        self.scripts_actions_layout.addWidget(self.btn_load_config)

        self.btn_save_config = QPushButton(self.scripts_panel)
        self.btn_save_config.setObjectName(u"btn_save_config")

        self.scripts_actions_layout.addWidget(self.btn_save_config)

        self.btn_open_scripts_dir = QPushButton(self.scripts_panel)
        self.btn_open_scripts_dir.setObjectName(u"btn_open_scripts_dir")

        self.scripts_actions_layout.addWidget(self.btn_open_scripts_dir)

        self.scripts_actions_spacer = QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.scripts_actions_layout.addItem(self.scripts_actions_spacer)

        self.btn_execute_scripts = QPushButton(self.scripts_panel)
        self.btn_execute_scripts.setObjectName(u"btn_execute_scripts")

        self.scripts_actions_layout.addWidget(self.btn_execute_scripts)


        self.scripts_layout.addLayout(self.scripts_actions_layout)

        self.right_splitter.addWidget(self.scripts_panel)
        self.log_panel = QWidget(self.right_splitter)
        self.log_panel.setObjectName(u"log_panel")
        self.log_layout = QVBoxLayout(self.log_panel)
        self.log_layout.setSpacing(6)
        self.log_layout.setObjectName(u"log_layout")
        self.log_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_log_title = QLabel(self.log_panel)
        self.lbl_log_title.setObjectName(u"lbl_log_title")

        self.log_layout.addWidget(self.lbl_log_title)

        self.log = QTextBrowser(self.log_panel)
        self.log.setObjectName(u"log")
        sizePolicy.setHeightForWidth(self.log.sizePolicy().hasHeightForWidth())
        self.log.setSizePolicy(sizePolicy)

        self.log_layout.addWidget(self.log)

        self.right_splitter.addWidget(self.log_panel)
        self.main_splitter.addWidget(self.right_splitter)

        self.central_layout.addWidget(self.main_splitter)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1280, 21))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)
        QWidget.setTabOrder(self.file_viewer, self.btn_open_folder)
        QWidget.setTabOrder(self.btn_open_folder, self.table_data_columns)
        QWidget.setTabOrder(self.table_data_columns, self.btn_load_config)
        QWidget.setTabOrder(self.btn_load_config, self.btn_save_config)
        QWidget.setTabOrder(self.btn_save_config, self.btn_execute_scripts)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"NeuroCrunch", None))
        self.lbl_explorer_title.setText(QCoreApplication.translate("MainWindow", u"Explorador", None))
        self.lbl_explorer_title.setProperty(u"class", QCoreApplication.translate("MainWindow", u"panelTitle", None))
#if QT_CONFIG(tooltip)
        self.btn_refresh.setToolTip(QCoreApplication.translate("MainWindow", u"Refrescar carpeta y scripts", None))
#endif // QT_CONFIG(tooltip)
        self.btn_refresh.setText("")
        self.btn_refresh.setProperty(u"class", QCoreApplication.translate("MainWindow", u"iconButton", None))
        ___qtreewidgetitem = self.file_viewer.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"Carpeta de trabajo", None));
#if QT_CONFIG(tooltip)
        self.btn_open_folder.setToolTip(QCoreApplication.translate("MainWindow", u"Elegir la carpeta de trabajo", None))
#endif // QT_CONFIG(tooltip)
        self.btn_open_folder.setText(QCoreApplication.translate("MainWindow", u"Seleccionar carpeta", None))
        self.image_viewer.setText("")
        self.lbl_scripts_title.setText(QCoreApplication.translate("MainWindow", u"Pipeline de scripts", None))
        self.lbl_scripts_title.setProperty(u"class", QCoreApplication.translate("MainWindow", u"panelTitle", None))
#if QT_CONFIG(tooltip)
        self.btn_darkmode.setToolTip(QCoreApplication.translate("MainWindow", u"Cambiar tema claro/oscuro", None))
#endif // QT_CONFIG(tooltip)
        self.btn_darkmode.setText("")
        self.btn_darkmode.setProperty(u"class", QCoreApplication.translate("MainWindow", u"iconButton", None))
        ___qtablewidgetitem = self.table_data_columns.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("MainWindow", u"Script", None));
        ___qtablewidgetitem1 = self.table_data_columns.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("MainWindow", u"Configurado", None));
        ___qtablewidgetitem2 = self.table_data_columns.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("MainWindow", u"Seleccion", None));
        ___qtablewidgetitem3 = self.table_data_columns.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("MainWindow", u"Orden", None));
#if QT_CONFIG(tooltip)
        self.btn_load_config.setToolTip(QCoreApplication.translate("MainWindow", u"Cargar configuraci\u00f3n desde archivo", None))
#endif // QT_CONFIG(tooltip)
        self.btn_load_config.setText(QCoreApplication.translate("MainWindow", u"Cargar", None))
#if QT_CONFIG(tooltip)
        self.btn_save_config.setToolTip(QCoreApplication.translate("MainWindow", u"Guardar configuraci\u00f3n actual", None))
#endif // QT_CONFIG(tooltip)
        self.btn_save_config.setText(QCoreApplication.translate("MainWindow", u"Guardar", None))
#if QT_CONFIG(tooltip)
        self.btn_open_scripts_dir.setToolTip(QCoreApplication.translate("MainWindow", u"Abrir carpeta de scripts de usuario", None))
#endif // QT_CONFIG(tooltip)
        self.btn_open_scripts_dir.setText(QCoreApplication.translate("MainWindow", u"Scripts", None))
#if QT_CONFIG(tooltip)
        self.btn_execute_scripts.setToolTip(QCoreApplication.translate("MainWindow", u"Ejecutar los scripts seleccionados en orden", None))
#endif // QT_CONFIG(tooltip)
        self.btn_execute_scripts.setText(QCoreApplication.translate("MainWindow", u"Ejecutar", None))
        self.lbl_log_title.setText(QCoreApplication.translate("MainWindow", u"Registro", None))
        self.lbl_log_title.setProperty(u"class", QCoreApplication.translate("MainWindow", u"panelTitle", None))
    # retranslateUi

