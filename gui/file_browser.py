"""
Файловый браузер для локальной и удаленной файловой системы.
Две панели, drag-and-drop, навигация, операции с файлами.
"""

import sys
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeView, QListView, QComboBox, QLineEdit, QFileDialog,
    QGroupBox, QSplitter, QMenu, QAction, QMessageBox, QInputDialog,
    QHeaderView, QAbstractItemView, QFrame
)
from PyQt5.QtCore import (
    Qt, QDir, QThread, pyqtSignal, QTimer, QFileSystemModel, QModelIndex
)
from PyQt5.QtGui import (
    QFont, QColor, QIcon
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.bench_connector import BenchConnector
    from core.file_manager import FileManager, FileInfo
    from core.file_transfer import FileTransfer
    from logger.log_manager import LogManager
except ImportError:
    BenchConnector = None
    FileManager = None
    FileInfo = None
    FileTransfer = None
    LogManager = None


# ============================================================
# ПОТОК ЗАГРУЗКИ СПИСКА ФАЙЛОВ СО СТЕНДА
# ============================================================

class RemoteListThread(QThread):
    """Поток получения списка файлов с удаленного стенда"""
    
    finished = pyqtSignal(list, str)
    error = pyqtSignal(str)
    
    def __init__(self, fm, stand_name: str, path: str):
        super().__init__()
        self.fm = fm
        self.stand_name = stand_name
        self.path = path
    
    def run(self):
        try:
            files = self.fm.list_remote(self.stand_name, self.path)
            self.finished.emit(files, self.path)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
# МОДЕЛЬ ФАЙЛОВ (ДЛЯ УДАЛЕННОГО ПРОСМОТРА)
# ============================================================

class RemoteFileModel:
    """Простая модель для отображения удаленных файлов"""
    
    def __init__(self):
        self.files: List[FileInfo] = []
        self.path = "/"
    
    def set_files(self, files: List[FileInfo], path: str):
        self.files = files
        self.path = path


# ============================================================
# ПАНЕЛЬ ФАЙЛОВ (ОДНА СТОРОНА)
# ============================================================

class FilePanel(QFrame):
    """Панель просмотра файлов (локальная или удаленная)"""
    
    path_changed = pyqtSignal(str)
    file_selected = pyqtSignal(str)
    file_double_clicked = pyqtSignal(str, bool)  # путь, is_dir
    
    def __init__(self, title: str, is_remote: bool = False):
        super().__init__()
        self.title = title
        self.is_remote = is_remote
        self.current_path = os.path.expanduser("~") if not is_remote else "/"
        self.path_history: List[str] = []
        
        self.setup_ui()
    
    def setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #252545;
                border: 1px solid #3a3a6a;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Заголовок
        header = QLabel(self.title)
        header.setStyleSheet("color: #a0b0ff; font-size: 13px; font-weight: bold; background: transparent;")
        layout.addWidget(header)
        
        # Адресная строка
        addr_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedWidth(30)
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a6a;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 14px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #5a5a9a;
            }
        """)
        addr_layout.addWidget(self.back_btn)
        
        self.up_btn = QPushButton("↑")
        self.up_btn.setFixedWidth(30)
        self.up_btn.clicked.connect(self.go_up)
        self.up_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a6a;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 14px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #5a5a9a;
            }
        """)
        addr_layout.addWidget(self.up_btn)
        
        self.path_edit = QLineEdit(self.current_path)
        self.path_edit.returnPressed.connect(self.on_path_entered)
        self.path_edit.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e32;
                border: 1px solid #3a3a6a;
                border-radius: 3px;
                color: #e0e0e0;
                padding: 4px;
                font-size: 11px;
            }
        """)
        addr_layout.addWidget(self.path_edit)
        
        layout.addLayout(addr_layout)
        
        # Список файлов
        self.file_list = QTreeView() if not self.is_remote else QListView()
        
        if not self.is_remote:
            # Локальная файловая модель
            self.model = QFileSystemModel()
            self.model.setRootPath(self.current_path)
            self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            
            self.file_list.setModel(self.model)
            self.file_list.setRootIndex(self.model.index(self.current_path))
            self.file_list.setColumnWidth(0, 200)
            self.file_list.setColumnWidth(1, 80)
            self.file_list.setColumnWidth(2, 100)
            self.file_list.doubleClicked.connect(self.on_local_double_click)
        else:
            # Удаленный список (простой)
            self.file_list.setViewMode(QListView.ListMode)
            self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        
        self.file_list.setStyleSheet("""
            QTreeView, QListView {
                background-color: #1e1e32;
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                color: #e0e0e0;
                font-size: 11px;
            }
            QTreeView::item:hover, QListView::item:hover {
                background-color: #3a3a6a;
            }
            QTreeView::item:selected, QListView::item:selected {
                background-color: #4a4ad2;
            }
            QHeaderView::section {
                background-color: #2a2a4a;
                color: #a0b0ff;
                padding: 4px;
                border: none;
                font-size: 10px;
            }
        """)
        
        layout.addWidget(self.file_list)
        
        # Статус
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6a6aaa; font-size: 10px; background: transparent;")
        layout.addWidget(self.status_label)
    
    def on_local_double_click(self, index: QModelIndex):
        """Двойной клик по локальному файлу"""
        file_path = self.model.filePath(index)
        is_dir = self.model.isDir(index)
        
        if is_dir:
            self.navigate_to(file_path)
        else:
            self.file_double_clicked.emit(file_path, False)
    
    def navigate_to(self, path: str):
        """Переходит в указанную папку"""
        self.path_history.append(self.current_path)
        self.current_path = path
        self.path_edit.setText(path)
        
        if not self.is_remote:
            self.file_list.setRootIndex(self.model.index(path))
        
        self.path_changed.emit(path)
    
    def go_back(self):
        """Возвращается в предыдущую папку"""
        if self.path_history:
            prev_path = self.path_history.pop()
            self.current_path = prev_path
            self.path_edit.setText(prev_path)
            
            if not self.is_remote:
                self.file_list.setRootIndex(self.model.index(prev_path))
            
            self.path_changed.emit(prev_path)
    
    def go_up(self):
        """Переходит на уровень выше"""
        parent = os.path.dirname(self.current_path)
        if parent != self.current_path:
            self.navigate_to(parent)
    
    def on_path_entered(self):
        """Обработчик ввода пути вручную"""
        new_path = self.path_edit.text()
        if os.path.exists(new_path) if not self.is_remote else True:
            self.navigate_to(new_path)
    
    def refresh(self):
        """Обновляет вид"""
        if not self.is_remote:
            self.file_list.setRootIndex(self.model.index(self.current_path))
    
    def get_selected_path(self) -> Optional[str]:
        """Возвращает путь к выбранному файлу"""
        if not self.is_remote:
            index = self.file_list.currentIndex()
            if index.isValid():
                return self.model.filePath(index)
        return None
    
    def update_remote_files(self, files: List[FileInfo], path: str):
        """Обновляет список удаленных файлов"""
        self.current_path = path
        self.path_edit.setText(path)
        
        # Очищаем и заполняем список
        self.file_list.clear()
        self.file_list.addItem("..")
        
        dirs = [f for f in files if f.is_dir]
        files_list = [f for f in files if not f.is_dir]
        
        for f in dirs:
            item = QListWidgetItem(f"📁 {f.name}")
            item.setData(Qt.UserRole, f.path)
            self.file_list.addItem(item)
        
        for f in files_list:
            item = QListWidgetItem(f"📄 {f.name} ({f.size_str})")
            item.setData(Qt.UserRole, f.path)
            self.file_list.addItem(item)
        
        self.status_label.setText(f"Файлов: {len(files)}")


# Добавляем импорт QListWidgetItem
from PyQt5.QtWidgets import QListWidgetItem


# ============================================================
# ФАЙЛОВЫЙ БРАУЗЕР (ДВЕ ПАНЕЛИ)
# ============================================================

class FileBrowser(QWidget):
    """
    Файловый браузер с локальной и удаленной панелями.
    
    Возможности:
    - Две панели (локальная и удаленная)
    - Навигация по папкам
    - Drag-and-drop для загрузки на стенд
    - Контекстное меню
    - Копирование/перемещение между панелями
    """
    
    def __init__(self, bench_connector=None, file_manager=None, file_transfer=None):
        super().__init__()
        self.bc = bench_connector
        self.fm = file_manager
        self.ft = file_transfer
        
        self.remote_thread = None
        
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        
        # Заголовок
        title = QLabel("ФАЙЛОВЫЙ БРАУЗЕР")
        title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        main_layout.addWidget(title)
        
        # Выбор стенда для удаленной панели
        stand_layout = QHBoxLayout()
        stand_layout.addWidget(QLabel("Стенд:"))
        
        self.stand_combo = QComboBox()
        self.stand_combo.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
        self.stand_combo.currentTextChanged.connect(self.on_stand_changed)
        stand_layout.addWidget(self.stand_combo)
        
        # Быстрые пути
        self.quick_path_combo = QComboBox()
        self.quick_path_combo.addItems([
            "/home/pkrv/CVS",
            "/home/pkrv/fpo_cfg",
            "/tmp",
            "/home/orangepi",
            "/var/log"
        ])
        self.quick_path_combo.setEditable(True)
        self.quick_path_combo.currentTextChanged.connect(self.on_quick_path)
        stand_layout.addWidget(self.quick_path_combo)
        
        stand_layout.addStretch()
        
        # Кнопка загрузки
        self.upload_selected_btn = QPushButton("ЗАГРУЗИТЬ ВЫБРАННОЕ →")
        self.upload_selected_btn.clicked.connect(self.upload_selected_file)
        self.upload_selected_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4ad2;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a5ae2;
            }
        """)
        stand_layout.addWidget(self.upload_selected_btn)
        
        main_layout.addLayout(stand_layout)
        
        # Две панели
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель (локальная)
        self.local_panel = FilePanel("ЛОКАЛЬНЫЕ ФАЙЛЫ", is_remote=False)
        self.local_panel.file_double_clicked.connect(self.on_local_file_double_click)
        self.splitter.addWidget(self.local_panel)
        
        # Правая панель (удаленная)
        self.remote_panel = FilePanel("УДАЛЕННЫЕ ФАЙЛЫ (СТЕНД)", is_remote=True)
        self.splitter.addWidget(self.remote_panel)
        
        self.splitter.setSizes([400, 400])
        
        main_layout.addWidget(self.splitter)
        
        # Статус
        self.status_label = QLabel("Готов")
        self.status_label.setStyleSheet("color: #6a6aaa; padding: 5px;")
        main_layout.addWidget(self.status_label)
    
    def set_managers(self, bc, fm=None, ft=None):
        """Устанавливает менеджеры"""
        self.bc = bc
        self.fm = fm
        self.ft = ft
        self.update_stand_list()
    
    def update_stand_list(self):
        """Обновляет список стендов"""
        if self.bc:
            self.stand_combo.clear()
            for stand_name in self.bc.stands:
                self.stand_combo.addItem(stand_name)
    
    # ============================================================
    # НАВИГАЦИЯ
    # ============================================================
    
    def on_stand_changed(self, stand_name: str):
        """Стенд изменен - обновляем удаленную панель"""
        self.refresh_remote_panel()
    
    def on_quick_path(self, path: str):
        """Быстрый переход по пути"""
        if self.fm and self.bc:
            stand_name = self.stand_combo.currentText()
            if self.bc.is_connected(stand_name):
                self.load_remote_directory(path)
    
    def load_remote_directory(self, path: str):
        """Загружает содержимое удаленной директории"""
        stand_name = self.stand_combo.currentText()
        
        if not self.fm or not self.bc or not self.bc.is_connected(stand_name):
            self.status_label.setText(f"Стенд {stand_name} не подключен")
            return
        
        self.status_label.setText(f"Загрузка {path}...")
        
        self.remote_thread = RemoteListThread(self.fm, stand_name, path)
        self.remote_thread.finished.connect(self.on_remote_files_loaded)
        self.remote_thread.error.connect(self.on_remote_error)
        self.remote_thread.start()
    
    def on_remote_files_loaded(self, files: List[FileInfo], path: str):
        """Файлы загружены"""
        self.remote_panel.update_remote_files(files, path)
        self.status_label.setText(f"Загружено: {len(files)} файлов")
    
    def on_remote_error(self, error: str):
        """Ошибка загрузки"""
        self.status_label.setText(f"Ошибка: {error}")
    
    def refresh_remote_panel(self):
        """Обновляет удаленную панель"""
        current_path = self.remote_panel.current_path
        self.load_remote_directory(current_path)
    
    def on_local_file_double_click(self, path: str, is_dir: bool):
        """Двойной клик по локальному файлу - загрузить на стенд?"""
        if not is_dir:
            reply = QMessageBox.question(
                self, "Загрузка на стенд",
                f"Загрузить файл '{os.path.basename(path)}' на стенд?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.upload_file_to_stand(path)
    
    # ============================================================
    # ЗАГРУЗКА ФАЙЛОВ
    # ============================================================
    
    def upload_selected_file(self):
        """Загружает выбранный локальный файл на стенд"""
        path = self.local_panel.get_selected_path()
        if path and os.path.isfile(path):
            self.upload_file_to_stand(path)
        else:
            QMessageBox.warning(self, "Внимание", "Выберите файл для загрузки!")
    
    def upload_file_to_stand(self, local_path: str):
        """Загружает файл на стенд"""
        stand_name = self.stand_combo.currentText()
        remote_path = self.remote_panel.current_path
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        if self.ft:
            filename = os.path.basename(local_path)
            self.status_label.setText(f"Загрузка {filename} на {stand_name}:{remote_path}...")
            
            success = self.ft.upload_file(stand_name, local_path, remote_path)
            
            if success:
                self.status_label.setText(f"Файл {filename} загружен!")
                self.refresh_remote_panel()
            else:
                self.status_label.setText(f"Ошибка загрузки {filename}")
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить {filename}")
        else:
            QMessageBox.warning(self, "Ошибка", "FileTransfer не настроен!")
    
    def refresh_local_panel(self):
        """Обновляет локальную панель"""
        self.local_panel.refresh()


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 12px;
        }
    """)
    
    browser = FileBrowser()
    browser.setWindowTitle("Файловый браузер")
    browser.resize(950, 600)
    browser.show()
    
    sys.exit(app.exec_())
