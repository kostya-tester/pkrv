"""
Панель управления стендами.
Отображает карточки стендов с картинками, статусом, кнопками подключения.
"""

import sys
import os
import time
from typing import Dict, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QMessageBox, QInputDialog,
    QLineEdit, QProgressBar, QGroupBox
)
from PyQt5.QtCore import (
    Qt, QTimer, QSize, pyqtSignal, QPropertyAnimation
)
from PyQt5.QtGui import (
    QPixmap, QFont, QIcon, QPalette, QColor
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.bench_connector import BenchConnector, StandInfo
    from logger.log_manager import LogManager
except ImportError:
    BenchConnector = None
    StandInfo = None
    LogManager = None

# Путь к картинкам
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")


# ============================================================
# КАРТОЧКА СТЕНДА
# ============================================================

class StandCard(QFrame):
    """Карточка одного стенда с картинкой, статусом и кнопками"""
    
    connect_clicked = pyqtSignal(str)  # имя стенда
    disconnect_clicked = pyqtSignal(str)
    refresh_clicked = pyqtSignal(str)
    
    STAND_IMAGES = {
        "ГОЗ": "goz.png",
        "Арктика": "arktika.png",
        "C1M": "c1m.png",
        "OrangePi": "orangepi.png"
    }
    
    STATUS_COLORS = {
        "online": "#4caf50",
        "offline": "#f44336",
        "connecting": "#ff9800",
        "error": "#f44336"
    }
    
    def __init__(self, stand_name: str, ip: str, username: str = "pkrv",
                 stand_type: str = "", folders: dict = None):
        super().__init__()
        self.stand_name = stand_name
        self.ip = ip
        self.username = username
        self.stand_type = stand_type
        self.folders = folders or {}
        self.is_connected = False
        self.status = "offline"
        
        self.setObjectName("standCard")
        self.setup_ui()
        self.setFixedSize(260, 400)
    
    def setup_ui(self):
        self.setStyleSheet("""
            QFrame#standCard {
                background-color: #252545;
                border: 2px solid #3a3a6a;
                border-radius: 15px;
                padding: 10px;
            }
            QFrame#standCard:hover {
                border: 2px solid #5a5a9a;
                background-color: #2a2a50;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # === КАРТИНКА СТЕНДА ===
        self.image_label = QLabel()
        self.image_label.setFixedSize(220, 140)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            background-color: #1e1e3a;
            border-radius: 10px;
            border: 1px solid #3a3a6a;
        """)
        
        image_name = self.STAND_IMAGES.get(self.stand_name, "logo.png")
        image_path = os.path.join(IMAGES_DIR, image_name)
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path).scaled(210, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText(f"[{self.stand_name}]")
            self.image_label.setStyleSheet("""
                background-color: #1e1e3a;
                border-radius: 10px;
                border: 1px solid #3a3a6a;
                color: #5a5a8a;
                font-size: 16px;
            """)
        
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)
        
        # === НАЗВАНИЕ ===
        name_label = QLabel(self.stand_name)
        name_label.setObjectName("standName")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("""
            color: #cdd6f4;
            font-size: 16px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(name_label)
        
        # === IP ===
        ip_label = QLabel(f"{self.username}@{self.ip}")
        ip_label.setAlignment(Qt.AlignCenter)
        ip_label.setStyleSheet("color: #8a8aaa; font-size: 11px; background: transparent;")
        layout.addWidget(ip_label)
        
        # === ТИП ===
        if self.stand_type:
            type_label = QLabel(self.stand_type)
            type_label.setAlignment(Qt.AlignCenter)
            type_label.setStyleSheet("color: #6a6aaa; font-size: 10px; background: transparent;")
            layout.addWidget(type_label)
        
        # === СТАТУС ===
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        self.indicator = QLabel("●")
        self.indicator.setStyleSheet("color: #f44336; font-size: 14px; background: transparent;")
        status_layout.addWidget(self.indicator)
        
        self.status_label = QLabel("OFFLINE")
        self.status_label.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold; background: transparent;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # === ПАПКИ ===
        if self.folders:
            folders_text = ""
            for key, path in self.folders.items():
                short_path = path if len(path) < 30 else "..." + path[-27:]
                folders_text += f"  {key}: {short_path}\n"
            
            folders_label = QLabel(folders_text.strip())
            folders_label.setStyleSheet("""
                color: #6a6aaa;
                font-size: 9px;
                background: transparent;
                padding: 5px;
                border: 1px solid #2a2a4a;
                border-radius: 5px;
            """)
            folders_label.setWordWrap(True)
            layout.addWidget(folders_label)
        
        layout.addStretch()
        
        # === КНОПКИ ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.connect_btn = QPushButton("ПОДКЛ.")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66bb6a;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
        """)
        self.connect_btn.clicked.connect(lambda: self.connect_clicked.emit(self.stand_name))
        btn_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("ОТКЛ.")
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ef5350;
            }
            QPushButton:pressed {
                background-color: #d32f2f;
            }
        """)
        self.disconnect_btn.clicked.connect(lambda: self.disconnect_clicked.emit(self.stand_name))
        self.disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self.disconnect_btn)
        
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #42a5f5;
            }
        """)
        self.refresh_btn.clicked.connect(lambda: self.refresh_clicked.emit(self.stand_name))
        btn_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(btn_layout)
    
    def set_status(self, status: str):
        """Обновляет статус стенда"""
        self.status = status
        color = self.STATUS_COLORS.get(status, "#f44336")
        
        self.indicator.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; background: transparent;")
        self.status_label.setText(status.upper())
        
        # Обновляем кнопки
        if status == "online":
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.setStyleSheet("""
                QFrame#standCard {
                    background-color: #253545;
                    border: 2px solid #4caf50;
                    border-radius: 15px;
                    padding: 10px;
                }
            """)
        else:
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.setStyleSheet("""
                QFrame#standCard {
                    background-color: #252545;
                    border: 2px solid #3a3a6a;
                    border-radius: 15px;
                    padding: 10px;
                }
                QFrame#standCard:hover {
                    border: 2px solid #5a5a9a;
                }
            """)


# ============================================================
# ПАНЕЛЬ СТЕНДОВ
# ============================================================

class BenchPanel(QWidget):
    """
    Панель управления стендами.
    Отображает карточки всех стендов с кнопками управления.
    """
    
    stand_connected = pyqtSignal(str)
    stand_disconnected = pyqtSignal(str)
    
    def __init__(self, bench_connector=None):
        super().__init__()
        self.bc = bench_connector
        self.stand_cards: Dict[str, StandCard] = {}
        
        self.setup_ui()
        self.setup_timer()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        
        # === ЗАГОЛОВОК ===
        header_layout = QHBoxLayout()
        
        title = QLabel("УПРАВЛЕНИЕ СТЕНДАМИ")
        title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Кнопка "Подключить все"
        self.connect_all_btn = QPushButton("ПОДКЛЮЧИТЬ ВСЕ")
        self.connect_all_btn.clicked.connect(self.connect_all_stands)
        header_layout.addWidget(self.connect_all_btn)
        
        # Кнопка "Отключить все"
        self.disconnect_all_btn = QPushButton("ОТКЛЮЧИТЬ ВСЕ")
        self.disconnect_all_btn.setObjectName("btnCancel")
        self.disconnect_all_btn.clicked.connect(self.disconnect_all_stands)
        header_layout.addWidget(self.disconnect_all_btn)
        
        main_layout.addLayout(header_layout)
        
        # === КАРТОЧКИ СТЕНДОВ ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.cards_widget = QWidget()
        self.cards_layout = QGridLayout(self.cards_widget)
        self.cards_layout.setSpacing(15)
        self.cards_layout.setContentsMargins(10, 10, 10, 10)
        
        scroll.setWidget(self.cards_widget)
        main_layout.addWidget(scroll)
        
        # === ИНФОРМАЦИЯ ===
        self.info_label = QLabel("Стенды не загружены. Нажмите 'Обновить' для сканирования сети.")
        self.info_label.setStyleSheet("color: #6a6aaa; padding: 10px;")
        self.info_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.info_label)
        
        # Кнопка обновления карточек
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        
        refresh_btn = QPushButton("ОБНОВИТЬ СТЕНДЫ")
        refresh_btn.clicked.connect(self.refresh_stands)
        refresh_layout.addWidget(refresh_btn)
        
        refresh_layout.addStretch()
        main_layout.addLayout(refresh_layout)
    
    def setup_timer(self):
        """Таймер автообновления"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.auto_refresh)
        self.timer.start(5000)
    
    def set_bench_connector(self, bc):
        """Устанавливает BenchConnector"""
        self.bc = bc
        self.create_stand_cards()
    
    def create_stand_cards(self):
        """Создает карточки стендов"""
        # Очищаем старые
        for card in self.stand_cards.values():
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.stand_cards.clear()
        
        if not self.bc:
            self.info_label.setText("BenchConnector не настроен")
            return
        
        stands = self.bc.stands
        
        if not stands:
            self.info_label.setText("Стенды не найдены в конфигурации")
            return
        
        # Раскладываем по сетке (2 столбца)
        positions = [(i // 2, i % 2) for i in range(len(stands))]
        
        for (row, col), (stand_name, stand_info) in zip(positions, stands.items()):
            card = StandCard(
                stand_name=stand_name,
                ip=stand_info.ip,
                username=stand_info.username,
                stand_type=stand_info.stand_type,
                folders=stand_info.folders
            )
            
            # Подключаем сигналы
            card.connect_clicked.connect(self.connect_stand)
            card.disconnect_clicked.connect(self.disconnect_stand)
            card.refresh_clicked.connect(self.refresh_single_stand)
            
            self.cards_layout.addWidget(card, row, col)
            self.stand_cards[stand_name] = card
        
        self.info_label.setText(f"Стендов: {len(stands)}")
        self.refresh_stands()
    
    # ============================================================
    # ДЕЙСТВИЯ
    # ============================================================
    
    def connect_stand(self, stand_name: str):
        """Подключается к стенду"""
        if not self.bc:
            return
        
        if stand_name in self.stand_cards:
            self.stand_cards[stand_name].set_status("connecting")
        
        # Запрашиваем пароль
        password, ok = QInputDialog.getText(
            self,
            f"Подключение к {stand_name}",
            f"Введите пароль для {stand_name}:",
            QLineEdit.Password
        )
        
        if ok and password:
            if self.bc.connect_to_stand(stand_name, password):
                self.stand_cards[stand_name].set_status("online")
                self.stand_connected.emit(stand_name)
                QMessageBox.information(self, "Успех", f"Подключен к {stand_name}")
            else:
                self.stand_cards[stand_name].set_status("error")
                QMessageBox.critical(self, "Ошибка", f"Не удалось подключиться к {stand_name}")
    
    def disconnect_stand(self, stand_name: str):
        """Отключается от стенда"""
        if not self.bc:
            return
        
        self.bc.disconnect_from_stand(stand_name)
        
        if stand_name in self.stand_cards:
            self.stand_cards[stand_name].set_status("offline")
        
        self.stand_disconnected.emit(stand_name)
    
    def refresh_single_stand(self, stand_name: str):
        """Обновляет статус одного стенда"""
        if not self.bc or stand_name not in self.bc.stands:
            return
        
        stand_info = self.bc.stands[stand_name]
        is_available = self.bc.check_stand_availability(stand_info.ip)
        
        if stand_name in self.stand_cards:
            status = "online" if is_available else "offline"
            self.stand_cards[stand_name].set_status(status)
    
    def connect_all_stands(self):
        """Подключается ко всем доступным стендам"""
        if not self.bc:
            return
        
        for stand_name, stand_info in self.bc.stands.items():
            if stand_info.status == "online" and not stand_info.connected:
                self.connect_stand(stand_name)
    
    def disconnect_all_stands(self):
        """Отключается от всех стендов"""
        if not self.bc:
            return
        
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Отключиться от всех стендов?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for stand_name in self.stand_cards:
                self.disconnect_stand(stand_name)
    
    def refresh_stands(self):
        """Обновляет статус всех стендов"""
        if not self.bc:
            return
        
        for stand_name, stand_info in self.bc.stands.items():
            if stand_name in self.stand_cards:
                status = stand_info.status
                self.stand_cards[stand_name].set_status(status)
        
        # Обновляем счетчик
        online = sum(1 for s in self.bc.stands.values() if s.status == "online")
        total = len(self.bc.stands)
        self.info_label.setText(f"Стендов онлайн: {online}/{total}")
    
    def auto_refresh(self):
        """Автообновление статусов"""
        if self.bc:
            for stand_name, stand_info in self.bc.stands.items():
                if stand_name in self.stand_cards:
                    self.stand_cards[stand_name].set_status(stand_info.status)


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Применяем тему
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 12px;
        }
    """)
    
    # Создаем тестовый коннектор
    if BenchConnector:
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(1)
        
        panel = BenchPanel(bc)
        panel.setWindowTitle("Панель стендов")
        panel.resize(600, 500)
    else:
        panel = BenchPanel()
        panel.setWindowTitle("Панель стендов (тест)")
        panel.resize(600, 500)
    
    panel.show()
    sys.exit(app.exec_())
