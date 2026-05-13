"""
Bench Manager - полностью автономный файл с GUI и картинками.
Подключение через системный SSH с поддержкой старых алгоритмов.
"""

import sys
import os
import time
import socket
import threading
import subprocess
import argparse
from datetime import datetime

# ============================================================
# ПУТИ
# ============================================================

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")

# ============================================================
# КОННЕКТОР СТЕНДОВ
# ============================================================

class StandInfo:
    def __init__(self, name, ip, username="pkrv", password="zxcv", stand_type=""):
        self.name = name
        self.ip = ip
        self.username = username
        self.password = password
        self.status = "offline"
        self.connected = False
        self.last_check = None
        self.stand_type = stand_type

class BenchConnector:
    STANDS = {
        "ГОЗ": {"ip": "192.168.243.248", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
        "Арктика": {"ip": "192.168.243.249", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
        "C1M": {"ip": "192.168.243.254", "username": "pkrv", "password": "zxcv", "type": "Основной стенд"},
    }
    
    ORANGEPI = {"ip": "192.168.243.46", "username": "orangepi", "password": "", "type": "Orange Pi"}
    
    OLD_SSH_OPTS = (
        "-o HostKeyAlgorithms=+ssh-rsa "
        "-o PubkeyAcceptedKeyTypes=+ssh-rsa "
        "-o MACs=+hmac-md5 "
        "-o StrictHostKeyChecking=no "
        "-o LogLevel=ERROR "
        "-o UserKnownHostsFile=NUL "
        "-o ConnectTimeout=10"
    )
    
    NORMAL_SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=5"
    
    def __init__(self):
        self.stands = {}
        self.monitoring = False
        self._init_stands()
    
    def _init_stands(self):
        for name, cfg in self.STANDS.items():
            self.stands[name] = StandInfo(name, cfg['ip'], cfg['username'], cfg.get('password', ''), cfg.get('type', ''))
        self.stands["OrangePi"] = StandInfo("OrangePi", self.ORANGEPI['ip'], self.ORANGEPI['username'],
                                             self.ORANGEPI.get('password', ''), self.ORANGEPI.get('type', ''))
    
    def check_availability(self, ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            r = s.connect_ex((ip, 22))
            s.close()
            return r == 0
        except: 
            return False
    
    def start_monitoring(self):
        if self.monitoring: 
            return
        self.monitoring = True
        def loop():
            while self.monitoring:
                for name, info in self.stands.items():
                    if self.check_availability(info.ip):
                        info.status = "online"
                    else:
                        info.status = "offline"
                        info.connected = False
                time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()
    
    def stop_monitoring(self): 
        self.monitoring = False

    def _ssh_command(self, name, remote_cmd, use_tty=False, timeout=15):
        info = self.stands[name]
        opts = self.OLD_SSH_OPTS if name in self.STANDS else self.NORMAL_SSH_OPTS
        if use_tty:
            opts = "-tt " + opts
        cmd = f'ssh {opts} {info.username}@{info.ip} "{remote_cmd}"'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            out = r.stdout if r.stdout else ""
            err = r.stderr if r.stderr else ""
            return r.returncode, out, err
        except subprocess.TimeoutExpired:
            return -1, "", "Таймаут подключения"
        except Exception as e:
            return -1, "", str(e)

    def connect(self, name, password=None):
        try:
            if name not in self.stands:
                return False, f"Стенд {name} не найден"
            info = self.stands[name]
            if password is None:
                password = info.password
            if not password:
                return False, f"Нет пароля для стенда {name}"
            
            if name in self.STANDS:
                remote_cmd = f"echo '{password}' | su -c 'qconn && ls /home/pkrv/CVS > /dev/null 2>&1 && echo OK || echo FAIL'"
                code, stdout, stderr = self._ssh_command(name, remote_cmd, use_tty=True, timeout=20)
                
                if 'OK' in stdout:
                    info.connected = True
                    return True, f"Подключен к {name}\n(su + qconn выполнены)"
                if 'FAIL' in stdout:
                    return False, "Пароль SSH принят, но su или qconn не сработали."
                if 'Permission denied' in stdout:
                    return False, "Неверный логин или пароль."
                return False, f"Ошибка подключения.\n\n{stdout[-300:]}\n\n{stderr[-300:]}"
            else:
                code, stdout, stderr = self._ssh_command(name, "echo OK", timeout=10)
                if 'OK' in stdout:
                    info.connected = True
                    return True, f"Подключен к {name}"
                return False, f"Ошибка подключения.\n{stdout[-300:]}"
        except Exception as e:
            return False, f"Критическая ошибка: {str(e)}"
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = info.password
        full_cmd = f"echo '{pwd}' | su -c 'qconn && {command}'" if name in self.STANDS else command
        code, stdout, stderr = self._ssh_command(name, full_cmd, use_tty=True, timeout=timeout)
        return code == 0, stdout, stderr
    
    def get_all_info(self):
        return {name: {"name": s.name, "ip": s.ip, "username": s.username,
                       "status": s.status, "connected": s.connected,
                       "type": s.stand_type} for name, s in self.stands.items()}

# ============================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ GUI
# ============================================================

bc = None
stand_cards = {}
window_ref = None

# ============================================================
# MAIN
# ============================================================

def main():
    global bc, stand_cards, window_ref
    
    parser = argparse.ArgumentParser(description="Bench Manager")
    parser.add_argument('--console', '-c', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--version', '-v', action='store_true')
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v1.0.0")
        return
    
    bc = BenchConnector()
    bc.start_monitoring()
    
    if args.check or args.console:
        time.sleep(3)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name:12} | {info['ip']:16} | {s}")
        if args.console:
            for n in ["ГОЗ", "Арктика", "C1M"]:
                ok, msg = bc.connect(n)
                print(f"{n}: {msg}")
        bc.stop_monitoring()
        return
    
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
            QWidget, QPushButton, QTabWidget, QTextEdit, QComboBox,
            QLineEdit, QMessageBox, QFrame, QTreeWidget, QTreeWidgetItem
        )
        from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
        from PyQt5.QtGui import QPixmap, QIcon, QColor
        
        STAND_IMAGES = {
            "ГОЗ": "goz.png", "Арктика": "arktika.png",
            "C1M": "c1m.png", "OrangePi": "orangepi.png"
        }
        
        def load_pixmap(name, width=280, height=180):
            paths = [os.path.join(IMAGES_DIR, name), os.path.join(BASE_DIR, "gui", "images", name)]
            for p in paths:
                if os.path.exists(p):
                    pix = QPixmap(p)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap(width, height)
            pix.fill(QColor("#2a2a4a"))
            return pix
        
        def load_logo(width=260, height=65):
            paths = [os.path.join(IMAGES_DIR, "logo.png"), os.path.join(BASE_DIR, "gui", "images", "logo.png")]
            for p in paths:
                if os.path.exists(p):
                    pix = QPixmap(p)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return None
        
        class StandCard(QFrame):
            def __init__(self, name, ip, username, stand_type):
                super().__init__()
                self.stand_name = name
                self.setFixedSize(340, 520)
                self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 15px; }")
                layout = QVBoxLayout(self)
                layout.setSpacing(8)
                layout.setContentsMargins(15, 15, 15, 15)
                
                img_name = STAND_IMAGES.get(name, "logo.png")
                img_label = QLabel()
                img_label.setPixmap(load_pixmap(img_name, 280, 180))
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet("background: transparent; border: none;")
                layout.addWidget(img_label)
                
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("color: #cdd6f4; font-size: 20px; font-weight: bold; background: transparent;")
                name_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(name_lbl)
                
                ip_lbl = QLabel(f"{username}@{ip}")
                ip_lbl.setStyleSheet("color: #8a8aaa; font-size: 12px; background: transparent;")
                ip_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(ip_lbl)
                
                if stand_type:
                    type_lbl = QLabel(stand_type)
                    type_lbl.setStyleSheet("color: #6a6aaa; font-size: 10px; background: transparent;")
                    type_lbl.setAlignment(Qt.AlignCenter)
                    layout.addWidget(type_lbl)
                
                self.status_lbl = QLabel("OFFLINE")
                self.status_lbl.setStyleSheet("color: #f44336; font-size: 14px; font-weight: bold; background: transparent;")
                self.status_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.status_lbl)
                
                self.indicator = QLabel("●")
                self.indicator.setStyleSheet("color: #f44336; font-size: 16px; background: transparent;")
                self.indicator.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.indicator)
                
                layout.addSpacing(10)
                
                self.connect_btn = QPushButton("ПОДКЛЮЧИТЬ")
                self.connect_btn.setMinimumHeight(35)
                self.connect_btn.setStyleSheet("QPushButton { background-color: #4caf50; font-size: 12px; padding: 8px; border-radius: 6px; } QPushButton:hover { background-color: #66bb6a; } QPushButton:disabled { background-color: #666; }")
                layout.addWidget(self.connect_btn)
                
                self.disconnect_btn = QPushButton("ОТКЛЮЧИТЬ")
                self.disconnect_btn.setMinimumHeight(35)
                self.disconnect_btn.setStyleSheet("QPushButton { background-color: #d24a4a; font-size: 12px; padding: 8px; border-radius: 6px; } QPushButton:hover { background-color: #e25a5a; } QPushButton:disabled { background-color: #666; }")
                self.disconnect_btn.setEnabled(False)
                layout.addWidget(self.disconnect_btn)
                
                layout.addStretch()
            
            def update_status(self, status, connected, is_connecting=False):
                if is_connecting:
                    self.status_lbl.setText("CONNECTING...")
                    self.status_lbl.setStyleSheet("color: #ff9800; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #ff9800; font-size: 16px; background: transparent;")
                    self.connect_btn.setEnabled(False)
                    self.disconnect_btn.setEnabled(False)
                elif status == "online":
                    self.status_lbl.setText("ONLINE")
                    self.status_lbl.setStyleSheet("color: #4caf50; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #4caf50; font-size: 16px; background: transparent;")
                    self.connect_btn.setEnabled(not connected)
                    self.disconnect_btn.setEnabled(connected)
                else:
                    self.status_lbl.setText("OFFLINE")
                    self.status_lbl.setStyleSheet("color: #f44336; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #f44336; font-size: 16px; background: transparent;")
                    self.connect_btn.setEnabled(False)
                    self.disconnect_btn.setEnabled(False)
        
        class ConnectThread(QThread):
            finished = pyqtSignal(str, bool, str)
            
            def __init__(self, name):
                super().__init__()
                self.name = name
            
            def run(self):
                ok, msg = bc.connect(self.name)
                self.finished.emit(self.name, ok, msg)
        
        class MainWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self.connecting_states = {}
                self.init_ui()
                self.setup_timer()
            
            def init_ui(self):
                self.setWindowTitle("Bench Manager Pro")
                self.setGeometry(50, 30, 1300, 850)
                
                central = QWidget()
                self.setCentralWidget(central)
                main_layout = QVBoxLayout(central)
                main_layout.setSpacing(10)
                main_layout.setContentsMargins(15, 15, 15, 15)
                
                # Header
                header = QFrame()
                header.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 12px; }")
                header.setFixedHeight(80)
                header_layout = QHBoxLayout(header)
                header_layout.setContentsMargins(25, 10, 25, 10)
                
                logo_header = QLabel()
                lp = load_logo(260, 65)
                if lp:
                    logo_header.setPixmap(lp)
                    logo_header.setFixedSize(260, 65)
                else:
                    logo_header.setText("BENCH MANAGER")
                    logo_header.setStyleSheet("color: #1a1a4a; font-size: 22px; font-weight: bold; background: transparent;")
                logo_header.setStyleSheet("background: transparent;")
                header_layout.addWidget(logo_header)
                header_layout.addStretch()
                
                title_lbl = QLabel("BENCH MANAGER PRO")
                title_lbl.setStyleSheet("color: #1a1a4a; font-size: 24px; font-weight: bold; background: transparent; letter-spacing: 4px;")
                header_layout.addWidget(title_lbl)
                header_layout.addStretch()
                
                self.status_label = QLabel("ЗАГРУЗКА...")
                self.status_label.setStyleSheet("color: #666; font-size: 13px; font-weight: bold; background: transparent;")
                header_layout.addWidget(self.status_label)
                
                main_layout.addWidget(header)
                
                # Tabs
                self.tabs = QTabWidget()
                main_layout.addWidget(self.tabs)
                
                self.create_stands_tab()
                self.create_orange_tab()
                self.create_files_tab()
                self.create_op_files_tab()
                self.create_processes_tab()
                self.create_logs_tab()
            
            def create_stands_tab(self):
                stands_tab = QWidget()
                stands_layout = QVBoxLayout(stands_tab)
                stands_layout.setAlignment(Qt.AlignCenter)
                
                cards_widget = QWidget()
                cards_layout = QHBoxLayout(cards_widget)
                cards_layout.setSpacing(25)
                cards_layout.setAlignment(Qt.AlignCenter)
                
                for name in ["ГОЗ", "Арктика", "C1M"]:
                    info = bc.stands[name]
                    card = StandCard(name, info.ip, info.username, info.stand_type)
                    card.connect_btn.clicked.connect(lambda checked, n=name: self.connect_stand(n))
                    card.disconnect_btn.clicked.connect(lambda checked, n=name: self.disconnect_stand(n))
                    cards_layout.addWidget(card)
                    stand_cards[name] = card
                
                stands_layout.addWidget(cards_widget, alignment=Qt.AlignCenter)
                
                refresh_btn = QPushButton("ОБНОВИТЬ СТАТУС")
                refresh_btn.setMaximumWidth(220)
                refresh_btn.clicked.connect(self.update_all_cards)
                stands_layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
                
                self.tabs.addTab(stands_tab, "СТЕНДЫ")
            
            def create_orange_tab(self):
                orange_tab = QWidget()
                orange_layout = QVBoxLayout(orange_tab)
                orange_layout.setAlignment(Qt.AlignCenter)
                
                title = QLabel("OrangePi")
                title.setAlignment(Qt.AlignCenter)
                title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
                orange_layout.addWidget(title)
                
                info = bc.stands["OrangePi"]
                card = StandCard("OrangePi", info.ip, info.username, info.stand_type)
                card.connect_btn.clicked.connect(lambda: self.connect_stand("OrangePi"))
                card.disconnect_btn.clicked.connect(lambda: self.disconnect_stand("OrangePi"))
                stand_cards["OrangePi"] = card
                orange_layout.addWidget(card, alignment=Qt.AlignCenter)
                orange_layout.addStretch()
                
                refresh_btn = QPushButton("ОБНОВИТЬ СТАТУС")
                refresh_btn.setMaximumWidth(220)
                refresh_btn.clicked.connect(self.update_all_cards)
                orange_layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
                
                self.tabs.addTab(orange_tab, "ORANGEPI")
            
            def create_files_tab(self):
                files_tab = QWidget()
                files_layout = QVBoxLayout(files_tab)
                
                # Selection row
                files_sel = QHBoxLayout()
                files_sel.addStretch()
                files_sel.addWidget(QLabel("Стенд:"))
                self.files_stand = QComboBox()
                self.files_stand.addItems(["ГОЗ", "Арктика", "C1M"])
                files_sel.addWidget(self.files_stand)
                files_sel.addWidget(QLabel("Путь:"))
                self.files_path = QLineEdit("/home/pkrv/CVS")
                self.files_path.setMinimumWidth(350)
                files_sel.addWidget(self.files_path)
                files_sel.addStretch()
                files_layout.addLayout(files_sel)
                
                # Quick buttons
                quick_row = QHBoxLayout()
                quick_row.addStretch()
                for path, label in [("/home/pkrv/CVS", "📁 CVS"), ("/tmp", "📁 /tmp"), ("/fead_hd", "📁 fead_hd")]:
                    btn = QPushButton(label)
                    btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; background-color: #3a3a6a; }")
                    btn.clicked.connect(lambda checked, p=path: self.browse_stand_files(p))
                    quick_row.addWidget(btn)
                quick_row.addStretch()
                files_layout.addLayout(quick_row)
                
                # Tree
                self.files_tree = QTreeWidget()
                self.files_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
                self.files_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }")
                self.files_tree.itemDoubleClicked.connect(self.cd_stand_folder)
                files_layout.addWidget(self.files_tree)
                
                # Log
                self.files_log = QTextEdit()
                self.files_log.setReadOnly(True)
                self.files_log.setMaximumHeight(50)
                files_layout.addWidget(self.files_log)
                
                # Buttons
                btn_row = QHBoxLayout()
                btn_row.addStretch()
                btn_row.addWidget(QPushButton("ОТКРЫТЬ", clicked=self.browse_stand_files))
                btn_row.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=self.cd_stand_folder))
                btn_row.addWidget(QPushButton("↑ НАВЕРХ", clicked=self.up_stand))
                btn_row.addStretch()
                files_layout.addLayout(btn_row)
                
                self.tabs.addTab(files_tab, "ФАЙЛЫ СТЕНДОВ")
            
            def create_op_files_tab(self):
                op_tab = QWidget()
                op_layout = QVBoxLayout(op_tab)
                
                op_sel = QHBoxLayout()
                op_sel.addStretch()
                op_sel.addWidget(QLabel("Стенд:"))
                self.op_stand = QComboBox()
                self.op_stand.addItems(["OrangePi"])
                op_sel.addWidget(self.op_stand)
                op_sel.addWidget(QLabel("Путь:"))
                self.op_path = QLineEdit("/")
                self.op_path.setMinimumWidth(350)
                op_sel.addWidget(self.op_path)
                op_sel.addStretch()
                op_layout.addLayout(op_sel)
                
                self.op_tree = QTreeWidget()
                self.op_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
                self.op_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; }")
                self.op_tree.itemDoubleClicked.connect(self.cd_op)
                op_layout.addWidget(self.op_tree)
                
                self.op_log = QTextEdit()
                self.op_log.setReadOnly(True)
                self.op_log.setMaximumHeight(50)
                op_layout.addWidget(self.op_log)
                
                op_btn = QHBoxLayout()
                op_btn.addStretch()
                op_btn.addWidget(QPushButton("ОТКРЫТЬ", clicked=self.browse_op))
                op_btn.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=self.cd_op))
                op_btn.addWidget(QPushButton("↑ НАВЕРХ", clicked=self.up_op))
                op_btn.addStretch()
                op_layout.addLayout(op_btn)
                
                self.tabs.addTab(op_tab, "ФАЙЛЫ ORANGEPI")
            
            def create_processes_tab(self):
                proc_tab = QWidget()
                proc_layout = QVBoxLayout(proc_tab)
                
                title = QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ")
                title.setAlignment(Qt.AlignCenter)
                title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
                proc_layout.addWidget(title)
                
                sel_row = QHBoxLayout()
                sel_row.addStretch()
                sel_row.addWidget(QLabel("Стенд:"))
                self.proc_stand = QComboBox()
                self.proc_stand.addItems(["ГОЗ", "Арктика", "C1M"])
                sel_row.addWidget(self.proc_stand)
                sel_row.addStretch()
                proc_layout.addLayout(sel_row)
                
                self.proc_log = QTextEdit()
                self.proc_log.setReadOnly(True)
                self.proc_log.setMaximumHeight(250)
                self.proc_log.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas;")
                proc_layout.addWidget(self.proc_log)
                
                act_row = QHBoxLayout()
                act_row.addStretch()
                act_row.addWidget(QPushButton("ЗАПУСТИТЬ", clicked=self.start_process, styleSheet="background:#4caf50;"))
                act_row.addWidget(QPushButton("ОСТАНОВИТЬ", clicked=self.stop_process, styleSheet="background:#d24a4a;"))
                act_row.addWidget(QPushButton("ПЕРЕЗАПУСТИТЬ", clicked=self.restart_process, styleSheet="background:#ff9800;"))
                act_row.addStretch()
                proc_layout.addLayout(act_row)
                proc_layout.addStretch()
                
                self.tabs.addTab(proc_tab, "ПРОЦЕССЫ")
            
            def create_logs_tab(self):
                log_tab = QWidget()
                log_layout = QVBoxLayout(log_tab)
                
                self.log_text = QTextEdit()
                self.log_text.setReadOnly(True)
                self.log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas;")
                log_layout.addWidget(self.log_text)
                
                log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: self.log_text.clear()))
                
                self.tabs.addTab(log_tab, "ЛОГИ")
            
            def setup_timer(self):
                self.timer = QTimer()
                self.timer.timeout.connect(self.update_all_cards)
                self.timer.start(3000)
                QTimer.singleShot(500, self.update_all_cards)
            
            def update_all_cards(self):
                """Обновляет все карточки стендов"""
                for name, card in stand_cards.items():
                    if name in bc.stands:
                        stand = bc.stands[name]
                        is_connecting = self.connecting_states.get(name, False)
                        card.update_status(stand.status, stand.connected, is_connecting)
                
                # Обновляем статус в хедере
                online = sum(1 for s in bc.stands.values() if s.status == "online")
                connected = sum(1 for s in bc.stands.values() if s.connected)
                self.status_label.setText(f"ONLINE: {online}/4 | CONNECTED: {connected}")
            
            def connect_stand(self, name):
                info = bc.stands[name]
                if info.status != "online":
                    QMessageBox.warning(self, "Ошибка", f"Стенд {name} не в сети!")
                    return
                
                if self.connecting_states.get(name, False):
                    return  # уже подключаемся
                
                self.connecting_states[name] = True
                self.update_all_cards()
                
                # Запускаем поток подключения
                self.thread = ConnectThread(name)
                self.thread.finished.connect(self.on_connect_finished)
                self.thread.start()
            
            def on_connect_finished(self, name, ok, msg):
                """Обработка завершения подключения"""
                self.connecting_states[name] = False
                
                if ok:
                    QMessageBox.information(self, "Успех", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Подключен к {name}")
                else:
                    QMessageBox.critical(self, "Ошибка подключения", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка подключения к {name}: {msg}")
                
                self.update_all_cards()
            
            def disconnect_stand(self, name):
                bc.disconnect(name)
                self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Отключен от {name}")
                self.update_all_cards()
            
            # Методы для файлов стендов
            def browse_stand_files(self, path=None):
                if path:
                    self.files_path.setText(path)
                name = self.files_stand.currentText()
                path = self.files_path.text().strip() or "/"
                
                if name in bc.stands and bc.stands[name].connected:
                    self.files_tree.clear()
                    ok, out, err = bc.execute(name, f"ls -la --time-style=long-iso {path} 2>/dev/null")
                    if ok:
                        for line in out.split('\n'):
                            if line.startswith('total') or not line.strip():
                                continue
                            parts = line.split()
                            if len(parts) >= 8:
                                fname = ' '.join(parts[7:])
                                if fname in ['.', '..']:
                                    continue
                                is_dir = line.startswith('d')
                                item = QTreeWidgetItem([
                                    fname, 
                                    parts[4] if not is_dir else "", 
                                    "Папка" if is_dir else "Файл", 
                                    f"{parts[5]} {parts[6]}" if len(parts) > 6 else ""
                                ])
                                if is_dir:
                                    item.setForeground(0, QColor("#61dafb"))
                                self.files_tree.addTopLevelItem(item)
                        self.files_log.append(f"[OK] {path}")
                    else:
                        self.files_log.append(f"[ОШИБКА] {err}")
                else:
                    self.files_log.append(f"Стенд {name} не подключен")
            
            def cd_stand_folder(self):
                item = self.files_tree.currentItem()
                if item and item.text(2) == "Папка":
                    self.files_path.setText(f"{self.files_path.text().rstrip('/')}/{item.text(0)}")
                    self.browse_stand_files()
            
            def up_stand(self):
                cur = self.files_path.text().rstrip('/')
                if cur != '/':
                    self.files_path.setText(os.path.dirname(cur) or '/')
                    self.browse_stand_files()
            
            # Методы для файлов OrangePi
            def browse_op(self):
                name = self.op_stand.currentText()
                path = self.op_path.text().strip() or "/"
                
                if name in bc.stands and bc.stands[name].connected:
                    self.op_tree.clear()
                    ok, out, err = bc.execute(name, f"ls -la --time-style=long-iso {path} 2>/dev/null")
                    if ok:
                        for line in out.split('\n'):
                            if line.startswith('total') or not line.strip():
                                continue
                            parts = line.split()
                            if len(parts) >= 8:
                                fname = ' '.join(parts[7:])
                                if fname in ['.', '..']:
                                    continue
                                is_dir = line.startswith('d')
                                item = QTreeWidgetItem([
                                    fname, 
                                    parts[4] if not is_dir else "", 
                                    "Папка" if is_dir else "Файл", 
                                    f"{parts[5]} {parts[6]}" if len(parts) > 6 else ""
                                ])
                                if is_dir:
                                    item.setForeground(0, QColor("#61dafb"))
                                self.op_tree.addTopLevelItem(item)
                        self.op_log.append(f"[OK] {path}")
                    else:
                        self.op_log.append(f"[ОШИБКА] {err}")
                else:
                    self.op_log.append(f"Стенд {name} не подключен")
            
            def cd_op(self):
                item = self.op_tree.currentItem()
                if item and item.text(2) == "Папка":
                    self.op_path.setText(f"{self.op_path.text().rstrip('/')}/{item.text(0)}")
                    self.browse_op()
            
            def up_op(self):
                cur = self.op_path.text().rstrip('/')
                if cur != '/':
                    self.op_path.setText(os.path.dirname(cur) or '/')
                    self.browse_op()
            
            # Методы для процессов
            def log_proc(self, msg):
                self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            
            def start_process(self):
                n = self.proc_stand.currentText()
                if bc.stands[n].connected:
                    ok, out, err = bc.execute(n, "cd /home/pkrv/fpo_cfg && nohup ./1po2_1n > /dev/null 2>&1 & echo $!")
                    if ok:
                        self.log_proc(f"{n}: запущен PID: {out.strip()}")
                    else:
                        self.log_proc(f"{n}: Ошибка - {err}")
                else:
                    self.log_proc(f"{n}: Нет подключения")
            
            def stop_process(self):
                n = self.proc_stand.currentText()
                if bc.stands[n].connected:
                    bc.execute(n, "pkill -f 1po2_1n; slay 1po2_1n 2>/dev/null")
                    self.log_proc(f"{n}: остановлен")
                else:
                    self.log_proc(f"{n}: Нет подключения")
            
            def restart_process(self):
                self.stop_process()
                time.sleep(1)
                self.start_process()
        
        app = QApplication(sys.argv)
        
        logo_p = load_logo()
        if logo_p:
            app.setWindowIcon(QIcon(logo_p))
        
        app.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 13px; }
            QPushButton { background-color: #4a4ad2; color: white; border: none; border-radius: 6px; padding: 10px 18px; font-weight: bold; }
            QPushButton:hover { background-color: #5a5ae2; }
            QTabWidget::pane { border: 1px solid #3a3a6a; border-radius: 8px; background: #1e1e32; }
            QTabBar::tab { background: #2a2a4a; color: #8a8aaa; padding: 12px 30px; font-weight: bold; font-size: 14px; min-width: 140px; }
            QTabBar::tab:selected { background: #1e1e32; color: #a0b0ff; border-bottom: 3px solid #4a4ad2; }
        """)
        
        window = MainWindow()
        window_ref = window
        window.show()
        
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"PyQt5 не установлен: {e}")
        if bc:
            bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
