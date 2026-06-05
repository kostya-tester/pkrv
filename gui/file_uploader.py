"""
Модуль загрузки файлов на стенды через GUI.
Drag-and-drop, прогресс-бар, очередь загрузок, история.
Картинки стендов и логотип.
"""

import sys
import os
import time
import threading
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QProgressBar, QComboBox,
    QLineEdit, QFileDialog, QFrame, QSplitter, QTextEdit,
    QMessageBox, QApplication, QGridLayout, QSizePolicy,
    QScrollArea, QGroupBox, QCheckBox, QMainWindow
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QUrl, QMimeData,
    QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QDragEnterEvent, QDropEvent, QPixmap, QFont, QIcon, QPalette, QColor
)

# Путь к изображениям
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# Импорт модулей проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.bench_connector import BenchConnector
    from core.file_transfer import FileTransfer
    from logger.log_manager import LogManager
except ImportError:
    BenchConnector = None
    FileTransfer = None
    LogManager = None


# ============================================================
# СТИЛИ
# ============================================================

DARK_THEME = """
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 12px;
}

QGroupBox {
    border: 2px solid #2a2a4a;
    border-radius: 10px;
    margin-top: 15px;
    padding-top: 20px;
    font-weight: bold;
    font-size: 13px;
    color: #a0b0ff;
    background-color: #1e1e32;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 10px;
    left: 15px;
}

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4a4ad2, stop:1 #3a3ab0);
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    color: white;
    font-weight: bold;
    font-size: 12px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #5a5ae2, stop:1 #4a4ac0);
}

QPushButton:pressed {
    background: #3a3aa0;
}

QPushButton:disabled {
    background: #2a2a3a;
    color: #606060;
}

QPushButton#btnCancel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #d24a4a, stop:1 #b03a3a);
}

QPushButton#btnCancel:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e25a5a, stop:1 #c04a4a);
}

QPushButton#btnClear {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4ad24a, stop:1 #3ab03a);
}

QPushButton#btnClear:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #5ae25a, stop:1 #4ac04a);
}

QComboBox {
    background-color: #2a2a4a;
    border: 1px solid #4a4a8a;
    border-radius: 5px;
    padding: 6px 10px;
    color: #e0e0e0;
    min-width: 150px;
}

QComboBox:hover {
    border: 1px solid #6a6aaa;
}

QComboBox::drop-down {
    border: none;
    width: 25px;
}

QComboBox QAbstractItemView {
    background-color: #2a2a4a;
    border: 1px solid #4a4a8a;
    color: #e0e0e0;
    selection-background-color: #4a4ad2;
}

QLineEdit {
    background-color: #2a2a4a;
    border: 1px solid #4a4a8a;
    border-radius: 5px;
    padding: 6px 10px;
    color: #e0e0e0;
}

QLineEdit:focus {
    border: 1px solid #6a6ac0;
}

QProgressBar {
    border: 1px solid #4a4a8a;
    border-radius: 4px;
    background-color: #2a2a4a;
    text-align: center;
    color: #e0e0e0;
    font-size: 10px;
    height: 16px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4a4ad2, stop:1 #6a6af0);
    border-radius: 3px;
}

QListWidget {
    background-color: #1e1e32;
    border: 2px dashed #3a3a6a;
    border-radius: 8px;
    color: #e0e0e0;
    padding: 5px;
}

QListWidget::item {
    background-color: #2a2a4a;
    border-radius: 5px;
    margin: 2px 0px;
    padding: 8px;
}

QListWidget::item:selected {
    background-color: #4a4ad2;
}

QListWidget::item:hover {
    background-color: #3a3a6a;
}

QTextEdit {
    background-color: #1a1a2e;
    border: 1px solid #3a3a6a;
    border-radius: 5px;
    color: #a0a0c0;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QLabel#dragLabel {
    color: #6a6aaa;
    font-size: 16px;
    font-weight: bold;
    border: 2px dashed #4a4a8a;
    border-radius: 10px;
    padding: 20px;
    background-color: #1e1e32;
}

QLabel#standName {
    color: #cdd6f4;
    font-size: 14px;
    font-weight: bold;
}

QLabel#standStatus {
    font-size: 11px;
    font-weight: bold;
}

QLabel#standStatus[status="online"] {
    color: #4caf50;
}

QLabel#standStatus[status="offline"] {
    color: #f44336;
}

QLabel#standStatus[status="connecting"] {
    color: #ff9800;
}

QFrame#standCard {
    background-color: #252545;
    border: 2px solid #3a3a6a;
    border-radius: 12px;
    padding: 10px;
}

QFrame#standCard:hover {
    border: 2px solid #5a5a9a;
}

QFrame#standCard[active="true"] {
    border: 2px solid #4caf50;
    background-color: #253545;
}

QLabel#logoLabel {
    background: transparent;
    border: none;
}
"""


# ============================================================
# КАРТОЧКА СТЕНДА
# ============================================================

class StandCard(QFrame):
    """Виджет-карточка стенда с картинкой и статусом"""
    
    clicked = pyqtSignal(str)  # Имя стенда
    
    STAND_IMAGES = {
        "ГОЗ": "goz.png",
        "Арктика": "arktika.png",
        "C1M": "c1m.png",
        "OrangePi": "orangepi.png"
    }
    
    def __init__(self, stand_name: str, ip: str, stand_type: str = ""):
        super().__init__()
        self.stand_name = stand_name
        self.ip = ip
        self.stand_type = stand_type
        self.is_active = False
        self.setObjectName("standCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(180, 220)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Картинка стенда
        self.image_label = QLabel()
        self.image_label.setFixedSize(140, 100)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: transparent; border: none;")
        
        # Загружаем картинку
        image_name = self.STAND_IMAGES.get(self.stand_name, "logo.png")
        image_path = os.path.join(IMAGES_DIR, image_name)
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path).scaled(140, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText(f"[{self.stand_name}]")
            self.image_label.setStyleSheet("color: #6a6aaa; font-size: 14px;")
        
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)
        
        # Название стенда
        name_label = QLabel(self.stand_name)
        name_label.setObjectName("standName")
        name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(name_label)
        
        # IP
        ip_label = QLabel(self.ip)
        ip_label.setStyleSheet("color: #8a8aaa; font-size: 10px;")
        ip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(ip_label)
        
        # Тип стенда
        if self.stand_type:
            type_label = QLabel(self.stand_type)
            type_label.setStyleSheet("color: #6a6aaa; font-size: 9px; background: transparent;")
            type_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(type_label)
        
        # Статус
        self.status_label = QLabel("OFFLINE")
        self.status_label.setObjectName("standStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Индикатор (точка)
        self.indicator = QLabel("⬤")
        self.indicator.setAlignment(Qt.AlignCenter)
        self.indicator.setStyleSheet("color: #f44336; font-size: 10px; background: transparent;")
        layout.addWidget(self.indicator)
    
    def set_status(self, status: str):
        """Обновляет статус стенда"""
        if status == "online":
            self.status_label.setText("ONLINE")
            self.status_label.setStyleSheet("color: #4caf50; font-size: 11px; font-weight: bold;")
            self.indicator.setStyleSheet("color: #4caf50; font-size: 10px; background: transparent;")
        elif status == "connecting":
            self.status_label.setText("CONNECTING")
            self.status_label.setStyleSheet("color: #ff9800; font-size: 11px; font-weight: bold;")
            self.indicator.setStyleSheet("color: #ff9800; font-size: 10px; background: transparent;")
        else:
            self.status_label.setText("OFFLINE")
            self.status_label.setStyleSheet("color: #f44336; font-size: 11px; font-weight: bold;")
            self.indicator.setStyleSheet("color: #f44336; font-size: 10px; background: transparent;")
    
    def set_active(self, active: bool):
        """Подсвечивает карточку как активную"""
        self.is_active = active
        if active:
            self.setStyleSheet("""
                QFrame#standCard {
                    background-color: #253545;
                    border: 2px solid #4caf50;
                    border-radius: 12px;
                    padding: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#standCard {
                    background-color: #252545;
                    border: 2px solid #3a3a6a;
                    border-radius: 12px;
                    padding: 10px;
                }
                QFrame#standCard:hover {
                    border: 2px solid #5a5a9a;
                }
            """)
    
    def mousePressEvent(self, event):
        self.clicked.emit(self.stand_name)


# ============================================================
# DRAG-AND-DROP ЗОНА
# ============================================================

class DragDropZone(QListWidget):
    """Область для перетаскивания файлов"""
    
    files_dropped = pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)
        self.setStyleSheet("""
            QListWidget {
                background-color: #1e1e32;
                border: 2px dashed #4a4a8a;
                border-radius: 10px;
                color: #6a6aaa;
                font-size: 14px;
                padding: 15px;
            }
        """)
        self.addItem("  Перетащите файлы сюда или нажмите для выбора...")
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QListWidget {
                    background-color: #252545;
                    border: 2px dashed #4caf50;
                    border-radius: 10px;
                    color: #4caf50;
                    font-size: 14px;
                    padding: 15px;
                }
            """)
    
    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QListWidget {
                background-color: #1e1e32;
                border: 2px dashed #4a4a8a;
                border-radius: 10px;
                color: #6a6aaa;
                font-size: 14px;
                padding: 15px;
            }
        """)
    
    def dropEvent(self, event: QDropEvent):
        event.acceptProposedAction()
        
        self.setStyleSheet("""
            QListWidget {
                background-color: #1e1e32;
                border: 2px dashed #4a4a8a;
                border-radius: 10px;
                color: #6a6aaa;
                font-size: 14px;
                padding: 15px;
            }
        """)
        
        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                files.append(file_path)
        
        if files:
            self.clear()
            for f in files:
                item = QListWidgetItem(f"  {os.path.basename(f)}")
                item.setToolTip(f)
                self.addItem(item)
            
            self.files_dropped.emit(files)
    
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        
        # Открываем диалог выбора файлов
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы для загрузки", "",
            "Все файлы (*.*)"
        )
        
        if files:
            self.clear()
            for f in files:
                item = QListWidgetItem(f"  {os.path.basename(f)}")
                item.setToolTip(f)
                self.addItem(item)
            
            self.files_dropped.emit(list(files))


# ============================================================
# ПОТОК ЗАГРУЗКИ
# ============================================================

class UploadThread(QThread):
    """Поток для загрузки файлов без блокировки GUI"""
    
    progress = pyqtSignal(int, int)  # текущий файл, общее количество
    file_progress = pyqtSignal(str, int)  # имя файла, процент
    finished = pyqtSignal()
    error = pyqtSignal(str, str)  # имя файла, ошибка
    log = pyqtSignal(str)  # сообщение в лог
    
    def __init__(self, stand_name: str, files: List[str], remote_folder: str,
                 file_transfer, bench_connector):
        super().__init__()
        self.stand_name = stand_name
        self.files = files
        self.remote_folder = remote_folder
        self.ft = file_transfer
        self.bc = bench_connector
        self.cancelled = False
    
    def run(self):
        total = len(self.files)
        
        for i, file_path in enumerate(self.files):
            if self.cancelled:
                break
            
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            self.progress.emit(i + 1, total)
            self.log.emit(f"Загрузка: {filename} ({self._format_size(file_size)})")
            
            # Симулируем прогресс (реальный прогресс сложно получить через subprocess)
            self.file_progress.emit(filename, 10)
            
            # Выполняем загрузку
            success = self.ft.upload_file(
                self.stand_name,
                file_path,
                self.remote_folder,
                show_progress=False,
                verify=True
            )
            
            self.file_progress.emit(filename, 100)
            
            if success:
                self.log.emit(f"  [OK] {filename} загружен")
            else:
                self.error.emit(filename, "Ошибка загрузки")
                self.log.emit(f"  [FAIL] {filename} - ошибка")
            
            time.sleep(0.3)
        
        self.finished.emit()
    
    def cancel(self):
        self.cancelled = True
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# ============================================================
# ГЛАВНАЯ ПАНЕЛЬ
# ============================================================

class FileUploaderWidget(QWidget):
    """
    Панель загрузки файлов на стенды.
    
    Содержит:
    - Карточки стендов с картинками и статусом
    - Drag-and-drop зону
    - Выбор папки назначения
    - Прогресс-бар
    - Лог загрузок
    - Историю
    """
    
    def __init__(self, bench_connector=None, file_transfer=None):
        super().__init__()
        
        self.bc = bench_connector
        self.ft = file_transfer
        
        self.current_files: List[str] = []
        self.selected_stand: str = None
        self.upload_thread: Optional[UploadThread] = None
        self.upload_history: List[Dict] = []
        self.stand_cards: Dict[str, StandCard] = {}
        
        self.setup_ui()
        self.setup_refresh_timer()
    
    def setup_ui(self):
        """Создает интерфейс"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        
        # ============================================================
        # ВЕРХНЯЯ ПАНЕЛЬ С ЛОГОТИПОМ
        # ============================================================
        header_layout = QHBoxLayout()
        
        # Логотип
        self.logo_label = QLabel()
        self.logo_label.setObjectName("logoLabel")
        logo_path = os.path.join(IMAGES_DIR, "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(160, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(pixmap)
        else:
            self.logo_label.setText("BENCH MANAGER")
            self.logo_label.setStyleSheet("color: #4a4ad2; font-size: 18px; font-weight: bold;")
        self.logo_label.setFixedHeight(60)
        header_layout.addWidget(self.logo_label)
        
        header_layout.addStretch()
        
        # Заголовок
        title = QLabel("ЗАГРУЗКА ФАЙЛОВ НА СТЕНДЫ")
        title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignRight)
        header_layout.addWidget(title)
        
        main_layout.addLayout(header_layout)
        
        # ============================================================
        # КАРТОЧКИ СТЕНДОВ
        # ============================================================
        stands_group = QGroupBox("Стенды")
        stands_group_layout = QHBoxLayout()
        stands_group_layout.setSpacing(15)
        stands_group_layout.setContentsMargins(15, 20, 15, 15)
        
        self.stands_widget = QWidget()
        self.stands_layout = QHBoxLayout(self.stands_widget)
        self.stands_layout.setSpacing(15)
        self.stands_layout.setContentsMargins(0, 0, 0, 0)
        
        stands_group_layout.addWidget(self.stands_widget)
        stands_group_layout.addStretch()
        
        main_layout.addWidget(stands_group)
        
        # ============================================================
        # DRAG-AND-DROP ЗОНА
        # ============================================================
        drop_group = QGroupBox("Файлы для загрузки")
        drop_layout = QVBoxLayout()
        
        self.drag_drop_zone = DragDropZone()
        self.drag_drop_zone.files_dropped.connect(self.on_files_dropped)
        drop_layout.addWidget(self.drag_drop_zone)
        
        drop_group.setLayout(drop_layout)
        main_layout.addWidget(drop_group)
        
        # ============================================================
        # НАСТРОЙКИ ЗАГРУЗКИ
        # ============================================================
        settings_layout = QHBoxLayout()
        
        # Выбор стенда
        settings_layout.addWidget(QLabel("Стенд:"))
        self.stand_combo = QComboBox()
        self.stand_combo.setMinimumWidth(150)
        settings_layout.addWidget(self.stand_combo)
        
        settings_layout.addSpacing(20)
        
        # Папка назначения
        settings_layout.addWidget(QLabel("Папка:"))
        self.folder_edit = QLineEdit("/tmp")
        self.folder_edit.setMinimumWidth(200)
        settings_layout.addWidget(self.folder_edit)
        
        # Кнопка обзора
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self.browse_remote_folder)
        settings_layout.addWidget(browse_btn)
        
        settings_layout.addStretch()
        
        main_layout.addLayout(settings_layout)
        
        # ============================================================
        # КНОПКИ И ПРОГРЕСС
        # ============================================================
        buttons_layout = QHBoxLayout()
        
        self.upload_btn = QPushButton("ЗАГРУЗИТЬ")
        self.upload_btn.setMinimumHeight(40)
        self.upload_btn.setMinimumWidth(150)
        self.upload_btn.clicked.connect(self.start_upload)
        self.upload_btn.setEnabled(False)
        buttons_layout.addWidget(self.upload_btn)
        
        self.cancel_btn = QPushButton("ОТМЕНА")
        self.cancel_btn.setObjectName("btnCancel")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.clicked.connect(self.cancel_upload)
        self.cancel_btn.setEnabled(False)
        buttons_layout.addWidget(self.cancel_btn)
        
        self.clear_btn = QPushButton("ОЧИСТИТЬ")
        self.clear_btn.setObjectName("btnClear")
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.clicked.connect(self.clear_files)
        buttons_layout.addWidget(self.clear_btn)
        
        buttons_layout.addStretch()
        
        # Общий прогресс
        self.total_progress = QProgressBar()
        self.total_progress.setMinimum(0)
        self.total_progress.setMaximum(100)
        self.total_progress.setValue(0)
        self.total_progress.setVisible(False)
        buttons_layout.addWidget(self.total_progress)
        
        main_layout.addLayout(buttons_layout)
        
        # Прогресс текущего файла
        self.file_progress = QProgressBar()
        self.file_progress.setMinimum(0)
        self.file_progress.setMaximum(100)
        self.file_progress.setValue(0)
        self.file_progress.setVisible(False)
        main_layout.addWidget(self.file_progress)
        
        # Статус
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6a6aaa;")
        main_layout.addWidget(self.status_label)
        
        # ============================================================
        # ЛОГ
        # ============================================================
        log_group = QGroupBox("Лог загрузок")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
    
    # ============================================================
    # ИНИЦИАЛИЗАЦИЯ
    # ============================================================
    
    def setup_refresh_timer(self):
        """Таймер для обновления статуса стендов"""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_stands)
        self.refresh_timer.start(3000)  # каждые 3 секунды
    
    def set_bench_connector(self, bc):
        """Устанавливает BenchConnector и создает карточки"""
        self.bc = bc
        self.create_stand_cards()
    
    def set_file_transfer(self, ft):
        """Устанавливает FileTransfer"""
        self.ft = ft
    
    def create_stand_cards(self):
        """Создает карточки стендов"""
        # Очищаем старые
        for card in self.stand_cards.values():
            self.stands_layout.removeWidget(card)
            card.deleteLater()
        self.stand_cards.clear()
        self.stand_combo.clear()
        
        if not self.bc:
            return
        
        # Создаем новые карточки
        for stand_name, stand_info in self.bc.stands.items():
            card = StandCard(
                stand_name,
                stand_info.ip,
                stand_info.stand_type
            )
            card.clicked.connect(self.on_stand_clicked)
            
            self.stands_layout.addWidget(card)
            self.stand_cards[stand_name] = card
            
            # Добавляем в выпадающий список
            self.stand_combo.addItem(f"{stand_name} ({stand_info.ip})")
        
        self.stands_layout.addStretch()
        self.refresh_stands()
    
    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    
    def on_stand_clicked(self, stand_name: str):
        """Обработчик клика по карточке стенда"""
        self.selected_stand = stand_name
        
        # Обновляем подсветку карточек
        for name, card in self.stand_cards.items():
            card.set_active(name == stand_name)
        
        # Обновляем комбобокс
        for i in range(self.stand_combo.count()):
            if stand_name in self.stand_combo.itemText(i):
                self.stand_combo.setCurrentIndex(i)
                break
        
        # Обновляем кнопку
        self.upload_btn.setEnabled(len(self.current_files) > 0 and stand_name is not None)
    
    def on_files_dropped(self, files: List[str]):
        """Обработчик перетаскивания файлов"""
        self.current_files = files
        self.upload_btn.setEnabled(len(files) > 0 and self.selected_stand is not None)
        
        total_size = sum(os.path.getsize(f) for f in files)
        self.status_label.setText(f"Выбрано файлов: {len(files)} (общий размер: {self._format_size(total_size)})")
    
    def browse_remote_folder(self):
        """Открывает диалог выбора папки на стенде"""
        folder = self.folder_edit.text()
        # Для простоты - ручной ввод или предустановленные варианты
        folders = ["/tmp", "/home/pkrv/CVS", "/home/pkrv/fpo_cfg", "/home/orangepi"]
        
        msg = QMessageBox()
        msg.setWindowTitle("Выберите папку назначения")
        msg.setText("Выберите папку или введите вручную:")
        msg.setInformativeText("\n".join(folders))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    # ============================================================
    # УПРАВЛЕНИЕ ЗАГРУЗКОЙ
    # ============================================================
    
    def start_upload(self):
        """Начинает загрузку файлов"""
        if not self.current_files:
            return
        
        stand_name = self.get_selected_stand()
        if not stand_name:
            QMessageBox.warning(self, "Ошибка", "Выберите стенд для загрузки!")
            return
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        remote_folder = self.folder_edit.text().strip()
        if not remote_folder:
            QMessageBox.warning(self, "Ошибка", "Укажите папку назначения!")
            return
        
        # Блокируем интерфейс
        self.upload_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.total_progress.setVisible(True)
        self.file_progress.setVisible(True)
        self.log_text.clear()
        
        # Запускаем поток загрузки
        self.upload_thread = UploadThread(
            stand_name,
            self.current_files,
            remote_folder,
            self.ft,
            self.bc
        )
        self.upload_thread.progress.connect(self.on_upload_progress)
        self.upload_thread.file_progress.connect(self.on_file_progress)
        self.upload_thread.finished.connect(self.on_upload_finished)
        self.upload_thread.error.connect(self.on_upload_error)
        self.upload_thread.log.connect(self.on_upload_log)
        self.upload_thread.start()
        
        self.add_log(f"=== Начало загрузки на {stand_name} ===")
        self.add_log(f"Файлов: {len(self.current_files)}")
        self.add_log(f"Папка: {remote_folder}")
    
    def cancel_upload(self):
        """Отменяет загрузку"""
        if self.upload_thread and self.upload_thread.isRunning():
            self.upload_thread.cancel()
            self.add_log("[ОТМЕНА] Загрузка отменена пользователем")
            self.upload_thread = None
        
        self.reset_ui()
    
    def on_upload_progress(self, current: int, total: int):
        """Обновление общего прогресса"""
        percent = int(current / total * 100) if total > 0 else 0
        self.total_progress.setValue(percent)
        self.status_label.setText(f"Загрузка: {current}/{total} файлов")
    
    def on_file_progress(self, filename: str, percent: int):
        """Обновление прогресса файла"""
        self.file_progress.setValue(percent)
    
    def on_upload_finished(self):
        """Загрузка завершена"""
        self.add_log("=== Загрузка завершена ===")
        
        # Сохраняем в историю
        self.upload_history.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stand': self.get_selected_stand(),
            'files': len(self.current_files),
            'folder': self.folder_edit.text()
        })
        
        self.reset_ui()
        self.status_label.setText("Загрузка завершена!")
    
    def on_upload_error(self, filename: str, error: str):
        """Ошибка загрузки"""
        self.add_log(f"[ОШИБКА] {filename}: {error}")
    
    def on_upload_log(self, message: str):
        """Сообщение в лог"""
        self.add_log(message)
    
    def reset_ui(self):
        """Сбрасывает интерфейс"""
        self.upload_btn.setEnabled(len(self.current_files) > 0)
        self.cancel_btn.setEnabled(False)
        self.total_progress.setVisible(False)
        self.file_progress.setVisible(False)
        self.total_progress.setValue(0)
        self.file_progress.setValue(0)
        self.upload_thread = None
    
    def clear_files(self):
        """Очищает список файлов"""
        self.current_files = []
        self.drag_drop_zone.clear()
        self.drag_drop_zone.addItem("  Перетащите файлы сюда или нажмите для выбора...")
        self.upload_btn.setEnabled(False)
        self.status_label.setText("")
        self.total_progress.setValue(0)
        self.file_progress.setValue(0)
    
    # ============================================================
    # ОБНОВЛЕНИЕ СТАТУСА СТЕНДОВ
    # ============================================================
    
    def refresh_stands(self):
        """Обновляет статус стендов на карточках"""
        if not self.bc:
            return
        
        for stand_name, card in self.stand_cards.items():
            if stand_name in self.bc.stands:
                stand_info = self.bc.stands[stand_name]
                card.set_status(stand_info.status)
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ
    # ============================================================
    
    def get_selected_stand(self) -> Optional[str]:
        """Возвращает выбранный стенд"""
        if self.selected_stand:
            return self.selected_stand
        
        text = self.stand_combo.currentText()
        for stand_name in self.stand_cards:
            if stand_name in text:
                return stand_name
        
        return None
    
    def add_log(self, message: str):
        """Добавляет сообщение в лог"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        
        # Автопрокрутка вниз
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def get_history(self) -> List[Dict]:
        """Возвращает историю загрузок"""
        return self.upload_history[-20:]


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)
    
    # Создаем тестовый коннектор
    if BenchConnector:
        bc = BenchConnector()
        bc.start_monitoring()
        
        if FileTransfer:
            ft = FileTransfer(bc)
        else:
            ft = None
        
        widget = FileUploaderWidget(bc, ft)
        widget.setWindowTitle("Загрузка файлов на стенды")
        widget.resize(900, 700)
        widget.show()
        
        # Создаем карточки после запуска
        time.sleep(1)
    else:
        widget = FileUploaderWidget()
        widget.setWindowTitle("Загрузка файлов на стенды (тест)")
        widget.resize(900, 700)
        widget.show()
    
    sys.exit(app.exec_())
