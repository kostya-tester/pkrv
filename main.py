"""
Bench Manager - полностью автономный файл с GUI и картинками.
"""

import sys
import os
import time
import socket
import threading
import subprocess
import argparse
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime

# ============================================================
# ПУТИ - ИСПРАВЛЕНО ДЛЯ EXE
# ============================================================

if getattr(sys, 'frozen', False):
    # Запуск из EXE
    BASE_DIR = sys._MEIPASS  # Временная папка PyInstaller
else:
    # Запуск из Python
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")

# Для отладки
print(f"DEBUG: BASE_DIR = {BASE_DIR}")
print(f"DEBUG: IMAGES_DIR = {IMAGES_DIR}")
print(f"DEBUG: exists = {os.path.exists(IMAGES_DIR)}")
if os.path.exists(IMAGES_DIR):
    print(f"DEBUG: files = {os.listdir(IMAGES_DIR)}")

# ============================================================
# ВСТРОЕННЫЙ ЛОГГЕР
# ============================================================

class LogManager:
    def __init__(self):
        self.log_level = "INFO"
        self.log_file = None
    def setup(self, level="INFO", log_file=None):
        self.log_level = level
        if log_file:
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                self.log_file = log_file
            except: pass
    def _write(self, level, msg):
        text = f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}"
        print(text)
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(text + '\n')
            except: pass
    def info(self, msg): self._write("INFO", msg)
    def error(self, msg): self._write("ERROR", msg)
    def warning(self, msg): self._write("WARNING", msg)
    def debug(self, msg):
        if self.log_level == "DEBUG": self._write("DEBUG", msg)

# ============================================================
# КОННЕКТОР СТЕНДОВ
# ============================================================

class StandInfo:
    def __init__(self, name, ip, username="pkrv", password="", stand_type=""):
        self.name = name
        self.ip = ip
        self.username = username
        self.password = password
        self.status = "offline"
        self.connected = False
        self.last_check = None
        self.stand_type = stand_type
    def to_dict(self):
        return {
            'name': self.name, 'ip': self.ip, 'username': self.username,
            'status': self.status, 'connected': self.connected,
            'type': self.stand_type,
            'last_check': self.last_check.strftime('%H:%M:%S') if self.last_check else 'Никогда'
        }

class BenchConnector:
    STANDS = {
        "ГОЗ": {"ip": "192.168.243.248", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
        "Арктика": {"ip": "192.168.243.249", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
        "C1M": {"ip": "192.168.243.254", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
        "OrangePi": {"ip": "192.168.243.46", "username": "orangepi", "password": "", "type": "Orange Pi"}
    }
    
    def __init__(self):
        self.logger = LogManager()
        self.stands = {}
        self.monitoring = False
        self._init_stands()
    
    def _init_stands(self):
        for name, cfg in self.STANDS.items():
            self.stands[name] = StandInfo(
                name, cfg['ip'], cfg['username'], 
                cfg.get('password', ''), cfg.get('type', '')
            )
    
    def check_availability(self, ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            r = s.connect_ex((ip, 22))
            s.close()
            return r == 0
        except: return False
    
    def start_monitoring(self):
        if self.monitoring: return
        self.monitoring = True
        def loop():
            while self.monitoring:
                for name, info in self.stands.items():
                    info.last_check = datetime.now()
                    if self.check_availability(info.ip):
                        info.status = "online"
                    else:
                        info.status = "offline"
                        info.connected = False
                time.sleep(5)
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        self.logger.info("Мониторинг запущен")
    
    def stop_monitoring(self): self.monitoring = False
    
    def connect(self, name, password=None):
        if name not in self.stands: return False
        info = self.stands[name]
        
        if password is None:
            password = info.password
        
        if not password:
            self.logger.error(f"Нет пароля для {name}")
            return False
        
        try:
            if os.name == 'nt':
                cmd = f'echo {password} | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {info.username}@{info.ip} "echo OK"'
            else:
                cmd = f'sshpass -p {password} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {info.username}@{info.ip} "echo OK"'
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if 'OK' in result.stdout:
                info.connected = True
                self.logger.info(f"Подключен к {name}")
                return True
            else:
                self.logger.error(f"Ошибка подключения к {name}: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Ошибка подключения к {name}: {e}")
            return False
    
    def auto_connect_all(self):
        results = {}
        for name, info in self.stands.items():
            if info.status == "online" and info.password:
                self.logger.info(f"Автоподключение к {name}...")
                results[name] = self.connect(name)
        return results
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = info.password
        if os.name == 'nt':
            cmd = f'echo {pwd} | ssh -o StrictHostKeyChecking=no {info.username}@{info.ip} "{command}"'
        else:
            cmd = f'sshpass -p {pwd} ssh -o StrictHostKeyChecking=no {info.username}@{info.ip} "{command}"'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout, r.stderr
        except: return False, "", "Ошибка"
    
    def get_all_info(self):
        return {name: s.to_dict() for name, s in self.stands.items()}

# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Bench Manager")
    parser.add_argument('--console', '-c', action='store_true', help='Консольный режим')
    parser.add_argument('--check', action='store_true', help='Проверить стенды')
    parser.add_argument('--version', '-v', action='store_true', help='Версия')
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v1.0.0")
        return
    
    bc = BenchConnector()
    bc.start_monitoring()
    
    if args.check:
        time.sleep(3)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name:12} | {info['ip']:16} | {s}")
        bc.stop_monitoring()
        return
    
    if args.console:
        time.sleep(3)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name} ({info['ip']}): {s}")
        bc.auto_connect_all()
        import code
        code.interact(local={'bc': bc})
        bc.stop_monitoring()
        return
    
    # ============================================================
    # GUI
    # ============================================================
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
            QWidget, QPushButton, QTabWidget, QTextEdit, QComboBox,
            QLineEdit, QGroupBox, QMessageBox, QInputDialog,
            QFrame, QGridLayout, QScrollArea
        )
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QPixmap, QIcon, QColor
        
        # ============================================================
        # КАРТИНКИ
        # ============================================================
        
        STAND_IMAGES = {
            "ГОЗ": "goz.png",
            "Арктика": "arktika.png",
            "C1M": "c1m.png",
            "OrangePi": "orangepi.png"
        }
        
        def load_pixmap(name, width=200, height=130):
            """Загружает картинку, ищет в нескольких местах"""
            # Список мест для поиска
            search_paths = [
                os.path.join(IMAGES_DIR, name),
                os.path.join(BASE_DIR, "gui", "images", name),
                os.path.join(os.path.dirname(sys.executable), "gui", "images", name) if getattr(sys, 'frozen', False) else None,
                os.path.join(os.path.dirname(sys.executable), name) if getattr(sys, 'frozen', False) else None,
            ]
            
            for path in search_paths:
                if path and os.path.exists(path):
                    pix = QPixmap(path)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            # Заглушка — цветной прямоугольник с текстом
            pix = QPixmap(width, height)
            pix.fill(QColor("#2a2a4a"))
            return pix
        
        # ============================================================
        # КАРТОЧКА СТЕНДА
        # ============================================================
        
        class StandCard(QFrame):
            def __init__(self, name, ip, username, stand_type):
                super().__init__()
                self.stand_name = name
                self.setMinimumSize(220, 320)
                self.setMaximumSize(280, 380)
                self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 12px; }")
                
                layout = QVBoxLayout(self)
                layout.setSpacing(6)
                
                # Картинка
                img_name = STAND_IMAGES.get(name, "logo.png")
                img_label = QLabel()
                pix = load_pixmap(img_name, 220, 130)
                img_label.setPixmap(pix)
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet("background: transparent; border: none;")
                layout.addWidget(img_label)
                
                # Название
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("color: #cdd6f4; font-size: 15px; font-weight: bold; background: transparent;")
                name_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(name_lbl)
                
                # IP
                ip_lbl = QLabel(f"{username}@{ip}")
                ip_lbl.setStyleSheet("color: #8a8aaa; font-size: 10px; background: transparent;")
                ip_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(ip_lbl)
                
                # Тип
                if stand_type:
                    type_lbl = QLabel(stand_type)
                    type_lbl.setStyleSheet("color: #6a6aaa; font-size: 9px; background: transparent;")
                    type_lbl.setAlignment(Qt.AlignCenter)
                    layout.addWidget(type_lbl)
                
                # Статус
                self.status_lbl = QLabel("OFFLINE")
                self.status_lbl.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold; background: transparent;")
                self.status_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.status_lbl)
                
                # Индикатор
                self.indicator = QLabel("●")
                self.indicator.setStyleSheet("color: #f44336; font-size: 12px; background: transparent;")
                self.indicator.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.indicator)
                
                layout.addStretch()
            
            def update_status(self, status, connected):
                if status == "online":
                    self.status_lbl.setText("ONLINE")
                    self.status_lbl.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #4caf50; font-size: 12px; background: transparent;")
                    border = "#4caf50"
                    self.setStyleSheet(f"QFrame {{ background-color: #252545; border: 2px solid {border}; border-radius: 12px; }}")
                else:
                    self.status_lbl.setText("OFFLINE")
                    self.status_lbl.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #f44336; font-size: 12px; background: transparent;")
                    self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 12px; }")
        
        # ============================================================
        # ОКНО
        # ============================================================
        
        app = QApplication(sys.argv)
        
        # Иконка
        logo_path = os.path.join(IMAGES_DIR, "logo.png")
        if os.path.exists(logo_path):
            app.setWindowIcon(QIcon(logo_path))
        
        app.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 12px; }
            QPushButton { background-color: #4a4ad2; color: white; border: none; border-radius: 5px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { background-color: #5a5ae2; }
            QTabWidget::pane { border: 1px solid #3a3a6a; border-radius: 5px; background: #1e1e32; }
            QTabBar::tab { background: #2a2a4a; color: #8a8aaa; padding: 8px 18px; font-weight: bold; }
            QTabBar::tab:selected { background: #1e1e32; color: #a0b0ff; border-bottom: 2px solid #4a4ad2; }
        """)
        
        window = QMainWindow()
        window.setWindowTitle("Bench Manager Pro")
        window.setGeometry(100, 50, 1000, 700)
        
        central = QWidget()
        window.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        
        # Header
        header = QFrame()
        header.setStyleSheet("QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a1a4a, stop:0.5 #2a2a5a, stop:1 #1a1a4a); border-radius: 10px; }")
        header.setFixedHeight(65)
        header_layout = QHBoxLayout(header)
        
        logo_header = QLabel()
        logo_p = load_pixmap("logo.png", 170, 50)
        logo_header.setPixmap(logo_p)
        logo_header.setStyleSheet("background: transparent;")
        header_layout.addWidget(logo_header)
        header_layout.addStretch()
        
        title_lbl = QLabel("BENCH MANAGER PRO")
        title_lbl.setStyleSheet("color: #cdd6f4; font-size: 18px; font-weight: bold; background: transparent;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        
        status_indicator = QLabel("ЗАГРУЗКА...")
        status_indicator.setStyleSheet("color: #ff9800; font-size: 10px; font-weight: bold; background: transparent;")
        header_layout.addWidget(status_indicator)
        
        main_layout.addWidget(header)
        
        # Вкладки
        tabs = QTabWidget()
        main_layout.addWidget(tabs)
        
        # ---- СТЕНДЫ ----
        stands_tab = QWidget()
        stands_layout = QVBoxLayout(stands_tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        cards_widget = QWidget()
        cards_grid = QGridLayout(cards_widget)
        cards_grid.setSpacing(15)
        
        stand_cards = {}
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        
        for (name, info), (row, col) in zip(bc.stands.items(), positions):
            card = StandCard(name, info.ip, info.username, info.stand_type)
            cards_grid.addWidget(card, row, col)
            stand_cards[name] = card
        
        scroll.setWidget(cards_widget)
        stands_layout.addWidget(scroll)
        
        btn_row = QHBoxLayout()
        
        def update_cards():
            for name, card in stand_cards.items():
                if name in bc.stands:
                    info = bc.stands[name]
                    card.update_status(info.status, info.connected)
            online = sum(1 for s in bc.stands.values() if s.status == "online")
            connected = sum(1 for s in bc.stands.values() if s.connected)
            status_indicator.setText(f"ONLINE: {online}/4 | ПОДКЛ: {connected}")
            status_indicator.setStyleSheet(f"color: {'#4caf50' if online > 0 else '#f44336'}; font-size: 10px; font-weight: bold; background: transparent;")
        
        refresh_btn = QPushButton("ОБНОВИТЬ")
        refresh_btn.clicked.connect(update_cards)
        btn_row.addWidget(refresh_btn)
        
        def auto_connect():
            results = bc.auto_connect_all()
            ok = sum(1 for v in results.values() if v)
            QMessageBox.information(window, "Результат", f"Подключено: {ok}/{len(results)}")
            update_cards()
        
        connect_btn = QPushButton("ПОДКЛЮЧИТЬ ВСЕ")
        connect_btn.setStyleSheet("QPushButton { background-color: #4caf50; }")
        connect_btn.clicked.connect(auto_connect)
        btn_row.addWidget(connect_btn)
        
        disconnect_btn = QPushButton("ОТКЛЮЧИТЬ ВСЕ")
        disconnect_btn.setStyleSheet("QPushButton { background-color: #d24a4a; }")
        disconnect_btn.clicked.connect(lambda: [bc.disconnect(n) for n in stand_cards] or update_cards())
        btn_row.addWidget(disconnect_btn)
        
        btn_row.addStretch()
        stands_layout.addLayout(btn_row)
        
        tabs.addTab(stands_tab, "СТЕНДЫ")
        
        # ---- ПРОЦЕССЫ ----
        proc_tab = QWidget()
        proc_layout = QVBoxLayout(proc_tab)
        proc_layout.addWidget(QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ"))
        proc_stand = QComboBox(); proc_stand.addItems(list(bc.STANDS.keys()))
        proc_layout.addWidget(proc_stand)
        proc_btns = QHBoxLayout()
        proc_btns.addWidget(QPushButton("ЗАПУСТИТЬ ./1po2_1n"))
        proc_btns.addWidget(QPushButton("ОСТАНОВИТЬ (slay)"))
        proc_btns.addWidget(QPushButton("ПЕРЕЗАПУСТИТЬ"))
        proc_layout.addLayout(proc_btns)
        proc_log = QTextEdit(); proc_log.setReadOnly(True); proc_log.setMaximumHeight(200)
        proc_layout.addWidget(proc_log)
        proc_layout.addStretch()
        tabs.addTab(proc_tab, "ПРОЦЕССЫ")
        
        # ---- ПЛАТЫ ----
        board_tab = QWidget()
        board_layout = QVBoxLayout(board_tab)
        board_layout.addWidget(QLabel("РАБОТА С ПЛАТАМИ"))
        board_stand = QComboBox(); board_stand.addItems(["ГОЗ", "Арктика", "C1M"])
        board_layout.addWidget(board_stand)
        board_layout.addWidget(QPushButton("ПРОШИТЬ (ln -sf mpo 1po2_1n)"))
        board_log = QTextEdit(); board_log.setReadOnly(True); board_log.setMaximumHeight(200)
        board_layout.addWidget(board_log)
        board_layout.addStretch()
        tabs.addTab(board_tab, "ПЛАТЫ")
        
        # ---- ЛОГИ ----
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_text = QTextEdit(); log_text.setReadOnly(True)
        log_layout.addWidget(log_text)
        log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: log_text.clear()))
        tabs.addTab(log_tab, "ЛОГИ")
        
        # Таймеры
        timer = QTimer()
        timer.timeout.connect(update_cards)
        timer.start(3000)
        QTimer.singleShot(500, update_cards)
        QTimer.singleShot(2000, lambda: [bc.auto_connect_all(), update_cards()])
        
        window.show()
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"PyQt5 не установлен: {e}")
        bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
