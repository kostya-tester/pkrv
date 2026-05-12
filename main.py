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
# ЛОГГЕР
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

# ============================================================
# КОННЕКТОР СТЕНДОВ (SSH → su → qconn)
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
    def to_dict(self):
        return {
            'name': self.name, 'ip': self.ip, 'username': self.username,
            'status': self.status, 'connected': self.connected,
            'type': self.stand_type,
            'last_check': self.last_check.strftime('%H:%M:%S') if self.last_check else 'Никогда'
        }

class BenchConnector:
    # Основные стенды (ГОЗ, Арктика, C1M) - с su и qconn
    STANDS = {
        "ГОЗ": {"ip": "192.168.243.248", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "need_su": True},
        "Арктика": {"ip": "192.168.243.249", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "need_su": True},
        "C1M": {"ip": "192.168.243.254", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "need_su": True},
    }
    
    # OrangePi отдельно
    ORANGEPI = {"ip": "192.168.243.46", "username": "orangepi", "password": "", "type": "Orange Pi", "need_su": False}
    
    def __init__(self):
        self.logger = LogManager()
        self.stands = {}
        self.monitoring = False
        self._init_stands()
    
    def _init_stands(self):
        for name, cfg in self.STANDS.items():
            self.stands[name] = StandInfo(name, cfg['ip'], cfg['username'], cfg.get('password', ''), cfg.get('type', ''))
        # OrangePi добавляем отдельно
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
        self.logger.info("Мониторинг запущен")
    
    def stop_monitoring(self): self.monitoring = False

    def connect(self, name, password=None):
        """Подключение: SSH → su (пароль) → qconn"""
        if name not in self.stands: return False
        info = self.stands[name]
        if password is None: password = info.password
        if not password: return False
        
        self.logger.info(f"Подключение к {name} ({info.username}@{info.ip})...")
        
        # Для основных стендов: ssh → su → qconn
        if name in self.STANDS:
            return self._connect_with_su_qconn(name, info, password)
        else:
            # OrangePi - обычное подключение
            return self._connect_simple(name, info, password)
    
    def _connect_simple(self, name, info, password):
        """Обычное SSH подключение (для OrangePi)"""
        try:
            if os.name == 'nt':
                cmd = f'echo {password} | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=5 {info.username}@{info.ip} "echo OK"'
            else:
                cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 {info.username}@{info.ip} 'echo OK'"
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if 'OK' in result.stdout:
                info.connected = True
                self.logger.info(f"Подключен к {name}")
                return True
            return False
        except: return False
    
    def _connect_with_su_qconn(self, name, info, password):
        """Подключение с su и qconn для ГОЗ/Арктика/C1M"""
        try:
            # Создаем команду: ssh → su → qconn → проверка
            remote_script = f"""
su -c 'qconn; ls /home/pkrv/CVS > /dev/null 2>&1 && echo OK || echo FAIL'
"""
            # Экранируем для передачи через ssh
            escaped_script = remote_script.replace("'", "'\"'\"'")
            
            if os.name == 'nt':
                cmd = f'echo {password} | ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=5 {info.username}@{info.ip} "{escaped_script}"'
            else:
                cmd = f"sshpass -p '{password}' ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 {info.username}@{info.ip} '{escaped_script}'"
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if 'OK' in result.stdout:
                info.connected = True
                self.logger.info(f"Подключен к {name} (su + qconn выполнены)")
                return True
            else:
                self.logger.error(f"Ошибка подключения к {name}: {result.stdout.strip()[-100:]}")
                return False
        except Exception as e:
            self.logger.error(f"Ошибка подключения к {name}: {e}")
            return False
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        """Выполнение команды на стенде через su"""
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = info.password
        
        # Для основных стендов - через su
        if name in self.STANDS:
            full_cmd = f"su -c 'qconn; {command}'"
        else:
            full_cmd = command
        
        escaped_cmd = full_cmd.replace("'", "'\"'\"'")
        
        if os.name == 'nt':
            cmd = f'echo {pwd} | ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL {info.username}@{info.ip} "{escaped_cmd}"'
        else:
            cmd = f"sshpass -p '{pwd}' ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {info.username}@{info.ip} '{escaped_cmd}'"
        
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout, r.stderr
        except: return False, "", "Ошибка"
    
    def get_cvs_contents(self, name):
        """Получает содержимое папки /home/pkrv/CVS"""
        return self.execute(name, "ls -la /home/pkrv/CVS")
    
    def get_all_info(self):
        return {name: s.to_dict() for name, s in self.stands.items()}

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
                bc.connect(n)
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
            QLineEdit, QGroupBox, QMessageBox,
            QFrame, QGridLayout, QScrollArea, QTreeWidget, QTreeWidgetItem
        )
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QPixmap, QIcon, QColor
        
        # ============================================================
        # КАРТИНКИ
        # ============================================================
        
        STAND_IMAGES = {
            "ГОЗ": "goz.png", "Арктика": "arktika.png",
            "C1M": "c1m.png", "OrangePi": "orangepi.png"
        }
        
        def load_pixmap(name, width=200, height=130):
            paths = [
                os.path.join(IMAGES_DIR, name),
                os.path.join(BASE_DIR, "gui", "images", name),
            ]
            for p in paths:
                if os.path.exists(p):
                    pix = QPixmap(p)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap(width, height)
            pix.fill(QColor("#2a2a4a"))
            return pix
        
        def load_logo(width=170, height=50):
            paths = [os.path.join(IMAGES_DIR, "logo.png"), os.path.join(BASE_DIR, "gui", "images", "logo.png")]
            for p in paths:
                if os.path.exists(p):
                    pix = QPixmap(p)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return None
        
        # ============================================================
        # КАРТОЧКА СТЕНДА (с кнопками внутри)
        # ============================================================
        
        class StandCard(QFrame):
            def __init__(self, name, ip, username, stand_type):
                super().__init__()
                self.stand_name = name
                self.setMinimumSize(240, 420)
                self.setMaximumSize(300, 460)
                self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 12px; }")
                
                layout = QVBoxLayout(self)
                layout.setSpacing(5)
                
                # Картинка
                img_name = STAND_IMAGES.get(name, "logo.png")
                img_label = QLabel()
                img_label.setPixmap(load_pixmap(img_name, 210, 130))
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet("background: transparent; border: none;")
                layout.addWidget(img_label)
                
                # Название
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("color: #cdd6f4; font-size: 16px; font-weight: bold; background: transparent;")
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
                
                self.indicator = QLabel("●")
                self.indicator.setStyleSheet("color: #f44336; font-size: 12px; background: transparent;")
                self.indicator.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.indicator)
                
                layout.addSpacing(8)
                
                # Кнопки подключения/отключения (внутри карточки)
                self.connect_btn = QPushButton("ПОДКЛЮЧИТЬ")
                self.connect_btn.setStyleSheet("QPushButton { background-color: #4caf50; font-size: 10px; padding: 6px; } QPushButton:hover { background-color: #66bb6a; }")
                layout.addWidget(self.connect_btn)
                
                self.disconnect_btn = QPushButton("ОТКЛЮЧИТЬ")
                self.disconnect_btn.setStyleSheet("QPushButton { background-color: #d24a4a; font-size: 10px; padding: 6px; } QPushButton:hover { background-color: #e25a5a; }")
                self.disconnect_btn.setEnabled(False)
                layout.addWidget(self.disconnect_btn)
                
                layout.addStretch()
            
            def update_status(self, status, connected):
                if status == "online":
                    self.status_lbl.setText("ONLINE")
                    self.status_lbl.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #4caf50; font-size: 12px; background: transparent;")
                    border = "#4caf50" if connected else "#ff9800"
                    self.setStyleSheet(f"QFrame {{ background-color: #252545; border: 2px solid {border}; border-radius: 12px; }}")
                    self.connect_btn.setEnabled(not connected)
                    self.disconnect_btn.setEnabled(connected)
                elif status == "connecting":
                    self.status_lbl.setText("CONNECTING...")
                    self.status_lbl.setStyleSheet("color: #ff9800; font-size: 12px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #ff9800; font-size: 12px; background: transparent;")
                else:
                    self.status_lbl.setText("OFFLINE")
                    self.status_lbl.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold; background: transparent;")
                    self.indicator.setStyleSheet("color: #f44336; font-size: 12px; background: transparent;")
                    self.setStyleSheet("QFrame { background-color: #252545; border: 2px solid #3a3a6a; border-radius: 12px; }")
                    self.connect_btn.setEnabled(status == "online")
                    self.disconnect_btn.setEnabled(False)
        
        # ============================================================
        # ОКНО
        # ============================================================
        
        app = QApplication(sys.argv)
        logo_p = load_logo()
        if logo_p: app.setWindowIcon(QIcon(logo_p))
        
        app.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 12px; }
            QPushButton { background-color: #4a4ad2; color: white; border: none; border-radius: 5px; padding: 8px 14px; font-weight: bold; }
            QPushButton:hover { background-color: #5a5ae2; }
            QTabWidget::pane { border: 1px solid #3a3a6a; border-radius: 5px; background: #1e1e32; }
            QTabBar::tab { background: #2a2a4a; color: #8a8aaa; padding: 10px 25px; font-weight: bold; font-size: 13px; min-width: 120px; }
            QTabBar::tab:selected { background: #1e1e32; color: #a0b0ff; border-bottom: 3px solid #4a4ad2; }
        """)
        
        window = QMainWindow()
        window.setWindowTitle("Bench Manager Pro")
        window.setGeometry(100, 50, 900, 700)
        
        central = QWidget()
        window.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        
        # ============================================================
        # HEADER (БЕЛЫЙ)
        # ============================================================
        header = QFrame()
        header.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 10px; }")
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        
        logo_header = QLabel()
        lp = load_logo()
        if lp: logo_header.setPixmap(lp)
        else: logo_header.setText("BENCH MANAGER")
        logo_header.setStyleSheet("background: transparent;")
        header_layout.addWidget(logo_header)
        header_layout.addStretch()
        
        title_lbl = QLabel("BENCH MANAGER PRO")
        title_lbl.setStyleSheet("color: #1a1a4a; font-size: 20px; font-weight: bold; background: transparent;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        
        status_indicator = QLabel("ЗАГРУЗКА...")
        status_indicator.setStyleSheet("color: #666; font-size: 11px; font-weight: bold; background: transparent;")
        header_layout.addWidget(status_indicator)
        
        main_layout.addWidget(header)
        
        # ============================================================
        # ВКЛАДКИ
        # ============================================================
        tabs = QTabWidget()
        main_layout.addWidget(tabs)
        
        # ---- ВКЛАДКА 1: СТЕНДЫ (ГОЗ, Арктика, C1M) ----
        stands_tab = QWidget()
        stands_layout = QVBoxLayout(stands_tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        cards_widget = QWidget()
        cards_grid = QGridLayout(cards_widget)
        cards_grid.setSpacing(15)
        
        stand_cards = {}
        main_stands = ["ГОЗ", "Арктика", "C1M"]
        
        for i, name in enumerate(main_stands):
            info = bc.stands[name]
            card = StandCard(name, info.ip, info.username, info.stand_type)
            cards_grid.addWidget(card, 0, i, Qt.AlignCenter)
            stand_cards[name] = card
            
            # Подключаем кнопки
            card.connect_btn.clicked.connect(lambda checked, n=name: connect_stand(n))
            card.disconnect_btn.clicked.connect(lambda checked, n=name: disconnect_stand(n))
        
        scroll.setWidget(cards_widget)
        stands_layout.addWidget(scroll)
        
        # Маленькая кнопка обновления снизу
        refresh_btn = QPushButton("ОБНОВИТЬ СТАТУС")
        refresh_btn.setMaximumWidth(200)
        refresh_btn.setStyleSheet("QPushButton { font-size: 10px; padding: 5px 10px; }")
        stands_layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
        
        tabs.addTab(stands_tab, "СТЕНДЫ")
        
        # ---- ВКЛАДКА 2: ORANGEPI ----
        orange_tab = QWidget()
        orange_layout = QVBoxLayout(orange_tab)
        
        orange_title = QLabel("OrangePi")
        orange_title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        orange_title.setAlignment(Qt.AlignCenter)
        orange_layout.addWidget(orange_title)
        
        # Карточка OrangePi
        op_info = bc.stands["OrangePi"]
        op_card = StandCard("OrangePi", op_info.ip, op_info.username, op_info.stand_type)
        op_card.connect_btn.clicked.connect(lambda: connect_stand("OrangePi"))
        op_card.disconnect_btn.clicked.connect(lambda: disconnect_stand("OrangePi"))
        stand_cards["OrangePi"] = op_card
        
        orange_layout.addWidget(op_card, alignment=Qt.AlignCenter)
        orange_layout.addStretch()
        
        refresh_op_btn = QPushButton("ОБНОВИТЬ СТАТУС")
        refresh_op_btn.setMaximumWidth(200)
        refresh_op_btn.setStyleSheet("QPushButton { font-size: 10px; padding: 5px 10px; }")
        refresh_op_btn.clicked.connect(update_cards)
        orange_layout.addWidget(refresh_op_btn, alignment=Qt.AlignCenter)
        
        tabs.addTab(orange_tab, "ORANGEPI")
        
        # ---- ВКЛАДКА 3: ПРОЦЕССЫ ----
        proc_tab = QWidget()
        proc_layout = QVBoxLayout(proc_tab)
        
        proc_title = QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ")
        proc_title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        proc_title.setAlignment(Qt.AlignCenter)
        proc_layout.addWidget(proc_title)
        
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
        proc_log.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 11px;")
        proc_layout.addWidget(proc_log)
        
        def log_proc(msg):
            proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        
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
        
        def restart_1po2():
            stop_1po2()
            time.sleep(1)
            start_1po2()
        
        act_row = QHBoxLayout()
        act_row.addStretch()
        QPushButton("ЗАПУСТИТЬ", clicked=start_1po2, styleSheet="QPushButton{background:#4caf50;}").setParent(act_row.widget())
        act_row.addWidget(QPushButton("ЗАПУСТИТЬ", clicked=start_1po2, styleSheet="QPushButton{background:#4caf50;}"))
        act_row.addWidget(QPushButton("ОСТАНОВИТЬ", clicked=stop_1po2, styleSheet="QPushButton{background:#d24a4a;}"))
        act_row.addWidget(QPushButton("ПЕРЕЗАПУСТИТЬ", clicked=restart_1po2, styleSheet="QPushButton{background:#ff9800;}"))
        act_row.addStretch()
        proc_layout.addLayout(act_row)
        proc_layout.addStretch()
        
        tabs.addTab(proc_tab, "ПРОЦЕССЫ")
        
        # ---- ВКЛАДКА 4: ПЛАТЫ (ПРОСМОТР ФАЙЛОВ) ----
        board_tab = QWidget()
        board_layout = QVBoxLayout(board_tab)
        
        board_title = QLabel("ПРОСМОТР ФАЙЛОВ НА ПЛАТЕ")
        board_title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        board_title.setAlignment(Qt.AlignCenter)
        board_layout.addWidget(board_title)
        
        board_sel = QHBoxLayout()
        board_sel.addStretch()
        board_sel.addWidget(QLabel("Стенд:"))
        board_stand = QComboBox()
        board_stand.addItems(main_stands + ["OrangePi"])
        board_sel.addWidget(board_stand)
        board_sel.addWidget(QLabel("Путь:"))
        board_path = QLineEdit("/home/pkrv/CVS")
        board_sel.addWidget(board_path)
        board_sel.addStretch()
        board_layout.addLayout(board_sel)
        
        board_tree = QTreeWidget()
        board_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
        board_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; } QTreeWidget::item:hover { background: #3a3a6a; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 5px; }")
        board_layout.addWidget(board_tree)
        
        board_log = QTextEdit()
        board_log.setReadOnly(True)
        board_log.setMaximumHeight(60)
        board_layout.addWidget(board_log)
        
        def browse_files():
            name = board_stand.currentText()
            path = board_path.text().strip() or "/"
            if bc.stands[name].connected:
                board_tree.clear()
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
                            board_tree.addTopLevelItem(item)
                    board_log.append(f"[OK] {path}")
                else: board_log.append(f"[ОШИБКА] {err}")
            else: board_log.append(f"[ОШИБКА] Нет подключения к {name}")
        
        def cd_folder():
            item = board_tree.currentItem()
            if item and item.text(2) == "Папка":
                board_path.setText(f"{board_path.text().rstrip('/')}/{item.text(0)}")
                browse_files()
        
        board_btn_row = QHBoxLayout()
        board_btn_row.addStretch()
        board_btn_row.addWidget(QPushButton("ОТКРЫТЬ", clicked=browse_files))
        board_btn_row.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=cd_folder))
        board_btn_row.addWidget(QPushButton("↑ НАВЕРХ", clicked=lambda: (board_path.setText(os.path.dirname(board_path.text().rstrip('/')) or '/'), browse_files())))
        board_btn_row.addStretch()
        board_layout.addLayout(board_btn_row)
        
        tabs.addTab(board_tab, "ПЛАТЫ")
        
        # ---- ВКЛАДКА 5: ЛОГИ ----
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 11px;")
        log_layout.addWidget(log_text)
        log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: log_text.clear()))
        tabs.addTab(log_tab, "ЛОГИ")
        
        # ============================================================
        # ФУНКЦИИ
        # ============================================================
        
        def update_cards():
            for name, card in stand_cards.items():
                if name in bc.stands:
                    info = bc.stands[name]
                    card.update_status(info.status, info.connected)
            online = sum(1 for s in bc.stands.values() if s.status == "online")
            connected = sum(1 for s in bc.stands.values() if s.connected)
            status_indicator.setText(f"ONLINE: {online}/4 | CONNECTED: {connected}")
        
        def connect_stand(name):
            info = bc.stands[name]
            if info.status != "online":
                QMessageBox.warning(window, "Ошибка", f"Стенд {name} не в сети!")
                return
            stand_cards[name].update_status("connecting", False)
            QApplication.processEvents()
            if bc.connect(name):
                QMessageBox.information(window, "Успех", f"Подключен к {name}")
            else:
                QMessageBox.critical(window, "Ошибка", f"Не удалось подключиться к {name}")
            update_cards()
        
        def disconnect_stand(name):
            bc.disconnect(name)
            update_cards()
        
        refresh_btn.clicked.connect(update_cards)
        refresh_op_btn.clicked.connect(update_cards)
        
        # Таймер
        timer = QTimer()
        timer.timeout.connect(update_cards)
        timer.start(3000)
        QTimer.singleShot(500, update_cards)
        QTimer.singleShot(2000, lambda: [bc.connect(n) for n in main_stands if bc.stands[n].status == "online"] or update_cards())
        
        window.show()
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"PyQt5: {e}")
        bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
