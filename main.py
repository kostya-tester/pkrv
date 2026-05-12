"""
Bench Manager - полностью автономный файл с GUI и картинками.
Использует plink.exe для старых стендов (ГОЗ/Арктика/C1M).
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

PLINK_PATH = None
if getattr(sys, 'frozen', False):
    plink_candidate = os.path.join(sys._MEIPASS, "plink.exe")
    if os.path.exists(plink_candidate):
        PLINK_PATH = plink_candidate
else:
    for p in [os.path.join(APP_DIR, "plink.exe"), os.path.join(APP_DIR, "tools", "plink.exe")]:
        if os.path.exists(p):
            PLINK_PATH = p
            break

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
        threading.Thread(target=loop, daemon=True).start()
    
    def stop_monitoring(self): self.monitoring = False

    def _ssh_cmd(self, name, remote_cmd, tty=False, timeout=10):
        """Выполняет SSH команду. Для старых стендов использует plink.exe."""
        info = self.stands[name]
        
        if name in self.STANDS and PLINK_PATH:
            if tty:
                cmd = f'echo y | "{PLINK_PATH}" -ssh -pw {info.password} -batch -t {info.username}@{info.ip} "{remote_cmd}"'
            else:
                cmd = f'echo y | "{PLINK_PATH}" -ssh -pw {info.password} -batch {info.username}@{info.ip} "{remote_cmd}"'
        else:
            opts = self.NORMAL_SSH_OPTS
            if tty:
                opts = "-tt " + opts
            cmd = f'ssh {opts} {info.username}@{info.ip} "{remote_cmd}"'
        
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, -1, "", "Таймаут подключения")
        except Exception as e:
            return subprocess.CompletedProcess(cmd, -1, "", str(e))

    def connect(self, name, password=None):
        if name not in self.stands: 
            return False, f"Стенд {name} не найден"
        info = self.stands[name]
        if password is None: 
            password = info.password
        if not password:
            return False, f"Нет пароля для стенда {name}"
        if name in self.STANDS:
            return self._connect_with_su(name, info, password)
        else:
            return self._connect_simple(name, info, password)
    
    def _connect_simple(self, name, info, password):
        try:
            result = self._ssh_cmd(name, "echo OK", tty=False, timeout=10)
            if 'OK' in result.stdout:
                info.connected = True
                return True, f"Подключен к {name}"
            return False, f"Не удалось подключиться.\n\nОтвет:\n{result.stdout.strip()[-200:]}\n\nSTDERR:\n{result.stderr.strip()[-200:]}"
        except Exception as e:
            return False, f"Ошибка: {e}"
    
    def _connect_with_su(self, name, info, password):
        try:
            remote_cmd = f"echo '{password}' | su -c 'qconn && ls /home/pkrv/CVS > /dev/null 2>&1 && echo OK || echo FAIL'"
            result = self._ssh_cmd(name, remote_cmd, tty=True, timeout=20)
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            
            if 'OK' in stdout:
                info.connected = True
                return True, f"Подключен к {name}\n(su + qconn выполнены)"
            
            error_msg = f"Не удалось подключиться к {name}.\n\nХост: {info.username}@{info.ip}\n\n"
            if 'FAIL' in stdout:
                error_msg += "Пароль SSH принят, но su или qconn не сработали."
            elif 'Permission denied' in stdout or 'Permission denied' in stderr:
                error_msg += "Неверный логин или пароль SSH."
            else:
                if stdout: error_msg += f"Ответ сервера:\n{stdout[-400:]}"
                if stderr: error_msg += f"\n\nSTDERR:\n{stderr[-400:]}"
            return False, error_msg
        except Exception as e:
            return False, f"Ошибка: {type(e).__name__}: {e}"
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = info.password
        if name in self.STANDS:
            full_cmd = f"echo '{pwd}' | su -c 'qconn && {command}'"
        else:
            full_cmd = command
        try:
            result = self._ssh_cmd(name, full_cmd, tty=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except:
            return False, "", "Ошибка выполнения"
    
    def get_all_info(self):
        return {name: {"name": s.name, "ip": s.ip, "username": s.username,
                       "status": s.status, "connected": s.connected,
                       "type": s.stand_type} for name, s in self.stands.items()}

# ============================================================
# MAIN
# ============================================================

def main():
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
        from PyQt5.QtCore import Qt, QTimer
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
                self.connect_btn.setStyleSheet("QPushButton { background-color: #4caf50; font-size: 12px; padding: 8px; border-radius: 6px; } QPushButton:hover { background-color: #66bb6a; }")
                layout.addWidget(self.connect_btn)
                self.disconnect_btn = QPushButton("ОТКЛЮЧИТЬ")
                self.disconnect_btn.setMinimumHeight(35)
                self.disconnect_btn.setStyleSheet("QPushButton { background-color: #d24a4a; font-size: 12px; padding: 8px; border-radius: 6px; } QPushButton:hover { background-color: #e25a5a; }")
                self.disconnect_btn.setEnabled(False)
                layout.addWidget(self.disconnect_btn)
                layout.addStretch()
            
            def update_status(self, status, connected):
                if status == "online":
                    self.status_lbl.setText("ONLINE")
                    self.status_lbl.setStyleSheet("color: #4caf50; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #4caf50; font-size: 16px; background: transparent;")
                    border = "#4caf50" if connected else "#ff9800"
                    self.setStyleSheet(f"QFrame {{ background-color: #252545; border: 3px solid {border}; border-radius: 15px; }}")
                    self.connect_btn.setEnabled(not connected)
                    self.disconnect_btn.setEnabled(connected)
                elif status == "connecting":
                    self.status_lbl.setText("CONNECTING...")
                    self.status_lbl.setStyleSheet("color: #ff9800; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #ff9800; font-size: 16px; background: transparent;")
                else:
                    self.status_lbl.setText("OFFLINE")
                    self.status_lbl.setStyleSheet("color: #f44336; font-size: 14px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #f44336; font-size: 16px; background: transparent;")
                    self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 15px; }")
                    self.connect_btn.setEnabled(status == "online")
                    self.disconnect_btn.setEnabled(False)
        
        app = QApplication(sys.argv)
        logo_p = load_logo()
        if logo_p: app.setWindowIcon(QIcon(logo_p))
        
        app.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 13px; }
            QPushButton { background-color: #4a4ad2; color: white; border: none; border-radius: 6px; padding: 10px 18px; font-weight: bold; }
            QPushButton:hover { background-color: #5a5ae2; }
            QTabWidget::pane { border: 1px solid #3a3a6a; border-radius: 8px; background: #1e1e32; }
            QTabBar::tab { background: #2a2a4a; color: #8a8aaa; padding: 12px 30px; font-weight: bold; font-size: 14px; min-width: 140px; }
            QTabBar::tab:selected { background: #1e1e32; color: #a0b0ff; border-bottom: 3px solid #4a4ad2; }
        """)
        
        window = QMainWindow()
        window.setWindowTitle("Bench Manager Pro")
        window.setGeometry(50, 30, 1300, 850)
        central = QWidget()
        window.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
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
        self_status = QLabel("ЗАГРУЗКА...")
        self_status.setStyleSheet("color: #666; font-size: 13px; font-weight: bold; background: transparent;")
        header_layout.addWidget(self_status)
        main_layout.addWidget(header)
        
        tabs = QTabWidget()
        main_layout.addWidget(tabs)
        stand_cards = {}
        main_stands = ["ГОЗ", "Арктика", "C1M"]
        
        def update_cards():
            for name, card in stand_cards.items():
                if name in bc.stands:
                    info = bc.stands[name]
                    card.update_status(info.status, info.connected)
            online = sum(1 for s in bc.stands.values() if s.status == "online")
            connected = sum(1 for s in bc.stands.values() if s.connected)
            self_status.setText(f"ONLINE: {online}/4 | CONNECTED: {connected}")
        
        def connect_stand(name):
            info = bc.stands[name]
            if info.status != "online":
                QMessageBox.warning(window, "Ошибка", f"Стенд {name} не в сети!")
                return
            stand_cards[name].update_status("connecting", False)
            QApplication.processEvents()
            ok, msg = bc.connect(name)
            if ok:
                QMessageBox.information(window, "Успех", msg)
            else:
                QMessageBox.critical(window, "Ошибка подключения", msg)
            update_cards()
        
        def disconnect_stand(name):
            bc.disconnect(name)
            update_cards()
        
        # Вкладка СТЕНДЫ
        stands_tab = QWidget()
        stands_layout = QVBoxLayout(stands_tab)
        stands_layout.setAlignment(Qt.AlignCenter)
        cards_widget = QWidget()
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setSpacing(25)
        cards_layout.setAlignment(Qt.AlignCenter)
        for name in main_stands:
            info = bc.stands[name]
            card = StandCard(name, info.ip, info.username, info.stand_type)
            cards_layout.addWidget(card)
            stand_cards[name] = card
            card.connect_btn.clicked.connect(lambda checked, n=name: connect_stand(n))
            card.disconnect_btn.clicked.connect(lambda checked, n=name: disconnect_stand(n))
        stands_layout.addWidget(cards_widget, alignment=Qt.AlignCenter)
        refresh_btn = QPushButton("ОБНОВИТЬ СТАТУС")
        refresh_btn.setMaximumWidth(220)
        refresh_btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; }")
        refresh_btn.clicked.connect(update_cards)
        stands_layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
        tabs.addTab(stands_tab, "СТЕНДЫ")
        
        # Вкладка ORANGEPI
        orange_tab = QWidget()
        orange_layout = QVBoxLayout(orange_tab)
        orange_layout.setAlignment(Qt.AlignCenter)
        orange_layout.addWidget(QLabel("OrangePi", alignment=Qt.AlignCenter, styleSheet="color: #a0b0ff; font-size: 18px; font-weight: bold;"))
        op_info = bc.stands["OrangePi"]
        op_card = StandCard("OrangePi", op_info.ip, op_info.username, op_info.stand_type)
        op_card.connect_btn.clicked.connect(lambda: connect_stand("OrangePi"))
        op_card.disconnect_btn.clicked.connect(lambda: disconnect_stand("OrangePi"))
        stand_cards["OrangePi"] = op_card
        orange_layout.addWidget(op_card, alignment=Qt.AlignCenter)
        orange_layout.addStretch()
        refresh_op_btn = QPushButton("ОБНОВИТЬ СТАТУС")
        refresh_op_btn.setMaximumWidth(220)
        refresh_op_btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; }")
        refresh_op_btn.clicked.connect(update_cards)
        orange_layout.addWidget(refresh_op_btn, alignment=Qt.AlignCenter)
        tabs.addTab(orange_tab, "ORANGEPI")
        
        # Вкладка ФАЙЛЫ СТЕНДОВ
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        files_sel = QHBoxLayout()
        files_sel.addStretch()
        files_sel.addWidget(QLabel("Стенд:"))
        files_stand = QComboBox()
        files_stand.addItems(main_stands)
        files_sel.addWidget(files_stand)
        files_sel.addWidget(QLabel("Путь:"))
        files_path = QLineEdit("/home/pkrv/CVS")
        files_path.setMinimumWidth(350)
        files_sel.addWidget(files_path)
        files_sel.addStretch()
        files_layout.addLayout(files_sel)
        quick_row = QHBoxLayout()
        quick_row.addStretch()
        for path, label in [("/home/pkrv/CVS", "📁 CVS"), ("/tmp", "📁 /tmp"), ("/fead_hd", "📁 fead_hd")]:
            btn = QPushButton(label)
            btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; background-color: #3a3a6a; } QPushButton:hover { background-color: #5a5a9a; }")
            btn.clicked.connect(lambda checked, p=path: (files_path.setText(p), browse_stand_files()))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        files_layout.addLayout(quick_row)
        files_tree = QTreeWidget()
        files_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
        files_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; font-size: 12px; } QTreeWidget::item { padding: 5px; } QTreeWidget::item:hover { background: #3a3a6a; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }")
        files_layout.addWidget(files_tree)
        files_log = QTextEdit()
        files_log.setReadOnly(True)
        files_log.setMaximumHeight(50)
        files_layout.addWidget(files_log)
        def browse_stand_files():
            name = files_stand.currentText()
            path = files_path.text().strip() or "/"
            if name in bc.stands and bc.stands[name].connected:
                files_tree.clear()
                ok, out, err = bc.execute(name, f"ls -la --time-style=long-iso {path} 2>/dev/null")
                if ok:
                    for line in out.split('\n'):
                        if line.startswith('total') or not line.strip(): continue
                        parts = line.split()
                        if len(parts) >= 8:
                            fname = ' '.join(parts[7:])
                            if fname in ['.', '..']: continue
                            is_dir = line.startswith('d')
                            item = QTreeWidgetItem([fname, parts[4] if not is_dir else "", "Папка" if is_dir else "Файл", f"{parts[5]} {parts[6]}" if len(parts)>6 else ""])
                            if is_dir: item.setForeground(0, QColor("#61dafb"))
                            files_tree.addTopLevelItem(item)
                    files_log.append(f"[OK] {path}")
                else:
                    files_log.append(f"[ОШИБКА] {err}")
            else:
                files_log.append(f"[ОШИБКА] Стенд {name} не подключен")
        def cd_stand_folder():
            item = files_tree.currentItem()
            if item and item.text(2) == "Папка":
                files_path.setText(f"{files_path.text().rstrip('/')}/{item.text(0)}")
                browse_stand_files()
        def up_stand():
            cur = files_path.text().rstrip('/')
            if cur != '/':
                files_path.setText(os.path.dirname(cur) or '/')
                browse_stand_files()
        files_btn_row = QHBoxLayout()
        files_btn_row.addStretch()
        files_btn_row.addWidget(QPushButton("ОТКРЫТЬ", clicked=browse_stand_files, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        files_btn_row.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=cd_stand_folder, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        files_btn_row.addWidget(QPushButton("↑ НАВЕРХ", clicked=up_stand, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        files_btn_row.addStretch()
        files_layout.addLayout(files_btn_row)
        tabs.addTab(files_tab, "ФАЙЛЫ СТЕНДОВ")
        
        # Вкладка ФАЙЛЫ ORANGEPI
        op_files_tab = QWidget()
        op_files_layout = QVBoxLayout(op_files_tab)
        op_files_sel = QHBoxLayout()
        op_files_sel.addStretch()
        op_files_sel.addWidget(QLabel("Стенд:"))
        op_files_stand = QComboBox()
        op_files_stand.addItems(["OrangePi"])
        op_files_sel.addWidget(op_files_stand)
        op_files_sel.addWidget(QLabel("Путь:"))
        op_files_path = QLineEdit("/")
        op_files_path.setMinimumWidth(350)
        op_files_sel.addWidget(op_files_path)
        op_files_sel.addStretch()
        op_files_layout.addLayout(op_files_sel)
        op_files_tree = QTreeWidget()
        op_files_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
        op_files_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; font-size: 12px; } QTreeWidget::item { padding: 5px; } QTreeWidget::item:hover { background: #3a3a6a; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }")
        op_files_layout.addWidget(op_files_tree)
        op_files_log = QTextEdit()
        op_files_log.setReadOnly(True)
        op_files_log.setMaximumHeight(50)
        op_files_layout.addWidget(op_files_log)
        def browse_op_files():
            name = op_files_stand.currentText()
            path = op_files_path.text().strip() or "/"
            if name in bc.stands and bc.stands[name].connected:
                op_files_tree.clear()
                ok, out, err = bc.execute(name, f"ls -la --time-style=long-iso {path} 2>/dev/null")
                if ok:
                    for line in out.split('\n'):
                        if line.startswith('total') or not line.strip(): continue
                        parts = line.split()
                        if len(parts) >= 8:
                            fname = ' '.join(parts[7:])
                            if fname in ['.', '..']: continue
                            is_dir = line.startswith('d')
                            item = QTreeWidgetItem([fname, parts[4] if not is_dir else "", "Папка" if is_dir else "Файл", f"{parts[5]} {parts[6]}" if len(parts)>6 else ""])
                            if is_dir: item.setForeground(0, QColor("#61dafb"))
                            op_files_tree.addTopLevelItem(item)
                    op_files_log.append(f"[OK] {path}")
                else:
                    op_files_log.append(f"[ОШИБКА] {err}")
            else:
                op_files_log.append(f"[ОШИБКА] Стенд {name} не подключен")
        def cd_op_folder():
            item = op_files_tree.currentItem()
            if item and item.text(2) == "Папка":
                op_files_path.setText(f"{op_files_path.text().rstrip('/')}/{item.text(0)}")
                browse_op_files()
        def up_op():
            cur = op_files_path.text().rstrip('/')
            if cur != '/':
                op_files_path.setText(os.path.dirname(cur) or '/')
                browse_op_files()
        op_btn_row = QHBoxLayout()
        op_btn_row.addStretch()
        op_btn_row.addWidget(QPushButton("ОТКРЫТЬ", clicked=browse_op_files, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        op_btn_row.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=cd_op_folder, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        op_btn_row.addWidget(QPushButton("↑ НАВЕРХ", clicked=up_op, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
        op_btn_row.addStretch()
        op_files_layout.addLayout(op_btn_row)
        tabs.addTab(op_files_tab, "ФАЙЛЫ ORANGEPI")
        
        # Вкладка ПРОЦЕССЫ
        proc_tab = QWidget()
        proc_layout = QVBoxLayout(proc_tab)
        proc_layout.addWidget(QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ", alignment=Qt.AlignCenter, styleSheet="color: #a0b0ff; font-size: 18px; font-weight: bold;"))
        sel_row = QHBoxLayout()
        sel_row.addStretch()
        sel_row.addWidget(QLabel("Стенд:"))
        proc_stand = QComboBox()
        proc_stand.addItems(main_stands)
        sel_row.addWidget(proc_stand)
        sel_row.addStretch()
        proc_layout.addLayout(sel_row)
        proc_log = QTextEdit()
        proc_log.setReadOnly(True)
        proc_log.setMaximumHeight(250)
        proc_log.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 12px;")
        proc_layout.addWidget(proc_log)
        def log_proc(msg): proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        def start_1po2():
            name = proc_stand.currentText()
            if bc.stands[name].connected:
                ok, out, err = bc.execute(name, "cd /home/pkrv/fpo_cfg && nohup ./1po2_1n > /dev/null 2>&1 & echo $!")
                if ok: log_proc(f"{name}: 1po2_1n запущен (PID: {out.strip()})")
                else: log_proc(f"{name}: Ошибка - {err}")
            else: log_proc(f"{name}: Нет подключения")
        def stop_1po2():
            name = proc_stand.currentText()
            if bc.stands[name].connected:
                bc.execute(name, "pkill -f 1po2_1n; slay 1po2_1n 2>/dev/null")
                log_proc(f"{name}: 1po2_1n остановлен")
            else: log_proc(f"{name}: Нет подключения")
        def restart_1po2(): stop_1po2(); time.sleep(1); start_1po2()
        act_row = QHBoxLayout()
        act_row.addStretch()
        act_row.addWidget(QPushButton("ЗАПУСТИТЬ", clicked=start_1po2, styleSheet="QPushButton{background:#4caf50; font-size:13px; padding:10px 20px;}"))
        act_row.addWidget(QPushButton("ОСТАНОВИТЬ", clicked=stop_1po2, styleSheet="QPushButton{background:#d24a4a; font-size:13px; padding:10px 20px;}"))
        act_row.addWidget(QPushButton("ПЕРЕЗАПУСТИТЬ", clicked=restart_1po2, styleSheet="QPushButton{background:#ff9800; font-size:13px; padding:10px 20px;}"))
        act_row.addStretch()
        proc_layout.addLayout(act_row)
        proc_layout.addStretch()
        tabs.addTab(proc_tab, "ПРОЦЕССЫ")
        
        # Вкладка ЛОГИ
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 12px;")
        log_layout.addWidget(log_text)
        log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: log_text.clear()))
        tabs.addTab(log_tab, "ЛОГИ")
        
        timer = QTimer()
        timer.timeout.connect(update_cards)
        timer.start(3000)
        QTimer.singleShot(500, update_cards)
        
        window.show()
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"PyQt5 не установлен: {e}")
        bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
