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
    }
    
    ORANGEPI = {"ip": "192.168.243.46", "username": "orangepi", "password": "", "type": "Orange Pi"}
    
    def __init__(self):
        self.logger = LogManager()
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
        self.logger.info("Мониторинг запущен")
    
    def stop_monitoring(self): self.monitoring = False

    def connect(self, name, password=None):
        """Подключение к стенду с подробным логированием ошибок"""
        if name not in self.stands: 
            self.logger.error(f"Стенд {name} не найден в конфигурации")
            return False
        
        info = self.stands[name]
        if password is None: 
            password = info.password
        
        if not password:
            self.logger.error(f"Нет пароля для стенда {name}")
            return False
        
        self.logger.info(f"=" * 50)
        self.logger.info(f"ПОДКЛЮЧЕНИЕ К {name} ({info.username}@{info.ip})")
        self.logger.info(f"=" * 50)
        
        if name in self.STANDS:
            result = self._connect_with_su(name, info, password)
        else:
            result = self._connect_simple(name, info, password)
        
        if not result:
            self.logger.error(f"НЕ УДАЛОСЬ ПОДКЛЮЧИТЬСЯ к {name}")
            self.logger.error(f"Проверьте:")
            self.logger.error(f"  1. Стенд доступен по SSH: ssh {info.username}@{info.ip}")
            self.logger.error(f"  2. Пароль правильный: {password}")
            self.logger.error(f"  3. Команда su работает на стенде")
        
        return result
    
    def _connect_simple(self, name, info, password):
        """Обычное SSH подключение (OrangePi)"""
        try:
            if os.name == 'nt':
                cmd = f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=5 {info.username}@{info.ip} "echo OK"'
            else:
                cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 {info.username}@{info.ip} 'echo OK'"
            
            self.logger.info(f"Выполняю: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            self.logger.info(f"Код возврата: {result.returncode}")
            self.logger.info(f"STDOUT: {result.stdout.strip()}")
            if result.stderr.strip():
                self.logger.info(f"STDERR: {result.stderr.strip()}")
            
            if 'OK' in result.stdout:
                info.connected = True
                self.logger.info(f"✓ Подключен к {name}")
                return True
            
            self.logger.error(f"✗ Не подключен. Ответ: {result.stdout.strip()}")
            return False
        except subprocess.TimeoutExpired:
            self.logger.error(f"✗ Таймаут подключения к {name} (10 секунд)")
            return False
        except Exception as e:
            self.logger.error(f"✗ Ошибка: {e}")
            return False
    
    def _connect_with_su(self, name, info, password):
        """SSH → su → qconn для ГОЗ/Арктика/C1M с детальным логом"""
        try:
            # Команда внутри стенда: передаём пароль в su, выполняем qconn, проверяем папку
            remote_cmd = f"echo '{password}' | su -c 'qconn && ls /home/pkrv/CVS > /dev/null 2>&1 && echo OK || echo FAIL'"
            
            if os.name == 'nt':
                cmd = f'ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=10 {info.username}@{info.ip} "{remote_cmd}"'
            else:
                cmd = f"sshpass -p '{password}' ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {info.username}@{info.ip} '{remote_cmd}'"
            
            self.logger.info(f"Команда SSH: ssh {info.username}@{info.ip}")
            self.logger.info(f"Удалённая команда: echo *** | su -c 'qconn && ls /home/pkrv/CVS && echo OK'")
            self.logger.info(f"Ожидание ответа (таймаут 20с)...")
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
            
            # Подробный вывод для отладки
            self.logger.info(f"Код возврата: {result.returncode}")
            
            stdout_preview = result.stdout.strip()
            stderr_preview = result.stderr.strip()
            
            if stdout_preview:
                self.logger.info(f"STDOUT (последние 300 символов):")
                self.logger.info(stdout_preview[-300:])
            else:
                self.logger.info(f"STDOUT: (пусто)")
            
            if stderr_preview:
                self.logger.info(f"STDERR:")
                self.logger.info(stderr_preview[-300:])
            
            # Анализируем ответ
            if 'OK' in result.stdout:
                info.connected = True
                self.logger.info(f"✓ Подключен к {name} (su + qconn выполнены успешно)")
                return True
            elif 'FAIL' in result.stdout:
                self.logger.error(f"✗ su или qconn не сработали. Ответ: {stdout_preview[-200:]}")
                return False
            elif 'Permission denied' in result.stdout or 'Permission denied' in result.stderr:
                self.logger.error(f"✗ Ошибка доступа. Неверный пароль?")
                return False
            elif 'Connection refused' in result.stderr:
                self.logger.error(f"✗ SSH-соединение отклонено. Порт 22 закрыт?")
                return False
            elif 'Connection timed out' in result.stderr or 'timed out' in stdout_preview:
                self.logger.error(f"✗ Таймаут соединения. Стенд не отвечает.")
                return False
            elif 'No route to host' in result.stderr:
                self.logger.error(f"✗ Нет маршрута до стенда. Проверьте сеть.")
                return False
            elif 'Host key verification failed' in result.stderr:
                self.logger.error(f"✗ Ключ хоста не совпадает.")
                return False
            else:
                self.logger.error(f"✗ Неизвестная ошибка. Полный ответ:")
                self.logger.error(f"  STDOUT: {stdout_preview}")
                self.logger.error(f"  STDERR: {stderr_preview}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error(f"✗ Таймаут подключения к {name} (20 секунд)")
            self.logger.error(f"  Стенд не ответил за отведённое время")
            return False
        except FileNotFoundError:
            self.logger.error(f"✗ Команда ssh не найдена!")
            self.logger.error(f"  Установите OpenSSH: Добавить компонент → OpenSSH Client")
            return False
        except Exception as e:
            self.logger.error(f"✗ Исключение Python: {type(e).__name__}: {e}")
            return False
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
            self.logger.info(f"Отключен от {name}")
    
    def execute(self, name, command, timeout=30):
        """Выполнение команды через su"""
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = info.password
        
        if name in self.STANDS:
            full_cmd = f"echo '{pwd}' | su -c 'qconn && {command}'"
        else:
            full_cmd = command
        
        if os.name == 'nt':
            cmd = f'ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL {info.username}@{info.ip} "{full_cmd}"'
        else:
            cmd = f"sshpass -p '{pwd}' ssh -tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {info.username}@{info.ip} '{full_cmd}'"
        
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout, r.stderr
        except Exception as e:
            self.logger.error(f"Ошибка выполнения команды: {e}")
            return False, "", str(e)
    
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
            QLineEdit, QMessageBox, QFrame, QScrollArea,
            QTreeWidget, QTreeWidgetItem
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
        
        def load_pixmap(name, width=280, height=180):
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
        
        def load_logo(width=260, height=65):
            paths = [os.path.join(IMAGES_DIR, "logo.png"), os.path.join(BASE_DIR, "gui", "images", "logo.png")]
            for p in paths:
                if os.path.exists(p):
                    pix = QPixmap(p)
                    if not pix.isNull():
                        return pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return None
        
        # ============================================================
        # КАРТОЧКА СТЕНДА
        # ============================================================
        
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
        
        # ============================================================
        # КОМПОНЕНТ ПРОСМОТРА ФАЙЛОВ
        # ============================================================
        
        def create_file_browser(placeholder_path="/home/pkrv/CVS", stand_filter=None):
            widget = QWidget()
            layout = QVBoxLayout(widget)
            
            sel_row = QHBoxLayout()
            sel_row.addStretch()
            sel_row.addWidget(QLabel("Стенд:"))
            stand_combo = QComboBox()
            if stand_filter:
                stand_combo.addItems(stand_filter)
            else:
                stand_combo.addItems(list(bc.STANDS.keys()) + ["OrangePi"])
            stand_combo.setMinimumWidth(180)
            sel_row.addWidget(stand_combo)
            sel_row.addWidget(QLabel("Путь:"))
            path_edit = QLineEdit(placeholder_path)
            path_edit.setMinimumWidth(350)
            sel_row.addWidget(path_edit)
            sel_row.addStretch()
            layout.addLayout(sel_row)
            
            if stand_filter:
                quick_row = QHBoxLayout()
                quick_row.addStretch()
                for folder_path, folder_label in [
                    ("/home/pkrv/CVS", "📁 CVS"),
                    ("/tmp", "📁 /tmp"),
                    ("/fead_hd", "📁 fead_hd")
                ]:
                    btn = QPushButton(folder_label)
                    btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; background-color: #3a3a6a; } QPushButton:hover { background-color: #5a5a9a; }")
                    btn.clicked.connect(lambda checked, p=folder_path: (path_edit.setText(p), browse_files()))
                    quick_row.addWidget(btn)
                quick_row.addStretch()
                layout.addLayout(quick_row)
            
            tree = QTreeWidget()
            tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
            tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; font-size: 12px; } QTreeWidget::item { padding: 5px; } QTreeWidget::item:hover { background: #3a3a6a; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }")
            layout.addWidget(tree)
            
            log_edit = QTextEdit()
            log_edit.setReadOnly(True)
            log_edit.setMaximumHeight(50)
            layout.addWidget(log_edit)
            
            def browse_files():
                name = stand_combo.currentText()
                path = path_edit.text().strip() or "/"
                if name in bc.stands and bc.stands[name].connected:
                    tree.clear()
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
                                tree.addTopLevelItem(item)
                        log_edit.append(f"[OK] {path}")
                    else:
                        log_edit.append(f"[ОШИБКА] {err}")
                else:
                    log_edit.append(f"[ОШИБКА] Стенд {name} не подключен")
            
            def cd_folder():
                item = tree.currentItem()
                if item and item.text(2) == "Папка":
                    path_edit.setText(f"{path_edit.text().rstrip('/')}/{item.text(0)}")
                    browse_files()
            
            def go_up():
                cur = path_edit.text().rstrip('/')
                if cur != '/':
                    path_edit.setText(os.path.dirname(cur) or '/')
                    browse_files()
            
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(QPushButton("ОТКРЫТЬ", clicked=browse_files, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
            btn_row.addWidget(QPushButton("ЗАЙТИ В ПАПКУ", clicked=cd_folder, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
            btn_row.addWidget(QPushButton("↑ НАВЕРХ", clicked=go_up, styleSheet="QPushButton{font-size:13px; padding:10px 20px;}"))
            btn_row.addStretch()
            layout.addLayout(btn_row)
            
            return widget
        
        # ============================================================
        # ОКНО
        # ============================================================
        
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
        
        # ============================================================
        # HEADER (БЕЛЫЙ)
        # ============================================================
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
        logo_header.setAlignment(Qt.AlignCenter)
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
        
        # ============================================================
        # ВКЛАДКИ
        # ============================================================
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
            if bc.connect(name):
                QMessageBox.information(window, "Успех", f"Подключен к {name}\n(выполнено: su + qconn)")
            else:
                # Показываем детальную ошибку
                QMessageBox.critical(window, "Ошибка подключения", 
                    f"Не удалось подключиться к {name}.\n\n"
                    f"Проверьте консоль (логи) для деталей.\n"
                    f"Убедитесь, что:\n"
                    f"1. Стенд доступен: ssh pkrv@{info.ip}\n"
                    f"2. Пароль правильный\n"
                    f"3. Команда su работает на стенде")
            update_cards()
        
        def disconnect_stand(name):
            bc.disconnect(name)
            update_cards()
        
        # ---- ВКЛАДКА 1: СТЕНДЫ ----
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
        
        # ---- ВКЛАДКА 2: ORANGEPI ----
        orange_tab = QWidget()
        orange_layout = QVBoxLayout(orange_tab)
        orange_layout.setAlignment(Qt.AlignCenter)
        
        orange_title = QLabel("OrangePi")
        orange_title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        orange_title.setAlignment(Qt.AlignCenter)
        orange_layout.addWidget(orange_title)
        
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
        
        # ---- ВКЛАДКА 3: ФАЙЛЫ СТЕНДОВ ----
        files_tab = create_file_browser("/home/pkrv/CVS", stand_filter=main_stands)
        tabs.addTab(files_tab, "ФАЙЛЫ СТЕНДОВ")
        
        # ---- ВКЛАДКА 4: ФАЙЛЫ ORANGEPI ----
        op_files_tab = create_file_browser("/", stand_filter=["OrangePi"])
        tabs.addTab(op_files_tab, "ФАЙЛЫ ORANGEPI")
        
        # ---- ВКЛАДКА 5: ПРОЦЕССЫ ----
        proc_tab = QWidget()
        proc_layout = QVBoxLayout(proc_tab)
        
        proc_title = QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ")
        proc_title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        proc_title.setAlignment(Qt.AlignCenter)
        proc_layout.addWidget(proc_title)
        
        sel_row = QHBoxLayout()
        sel_row.addStretch()
        sel_row.addWidget(QLabel("Стенд:"))
        proc_stand = QComboBox()
        proc_stand.addItems(main_stands)
        proc_stand.setMinimumWidth(180)
        sel_row.addWidget(proc_stand)
        sel_row.addStretch()
        proc_layout.addLayout(sel_row)
        
        proc_log = QTextEdit()
        proc_log.setReadOnly(True)
        proc_log.setMaximumHeight(250)
        proc_log.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 12px;")
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
        act_row.addWidget(QPushButton("ЗАПУСТИТЬ", clicked=start_1po2, styleSheet="QPushButton{background:#4caf50; font-size:13px; padding:10px 20px;}"))
        act_row.addWidget(QPushButton("ОСТАНОВИТЬ", clicked=stop_1po2, styleSheet="QPushButton{background:#d24a4a; font-size:13px; padding:10px 20px;}"))
        act_row.addWidget(QPushButton("ПЕРЕЗАПУСТИТЬ", clicked=restart_1po2, styleSheet="QPushButton{background:#ff9800; font-size:13px; padding:10px 20px;}"))
        act_row.addStretch()
        proc_layout.addLayout(act_row)
        proc_layout.addStretch()
        
        tabs.addTab(proc_tab, "ПРОЦЕССЫ")
        
        # ---- ВКЛАДКА 6: ЛОГИ ----
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas; font-size: 12px;")
        log_layout.addWidget(log_text)
        log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: log_text.clear()))
        tabs.addTab(log_tab, "ЛОГИ")
        
        # Таймеры
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
