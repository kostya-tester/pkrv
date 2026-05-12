"""
Bench Manager - полностью автономный файл.
Не требует импорта из папок core/, logger/, gui/.
"""

import sys
import os
import time
import socket
import threading
import subprocess
import hashlib
import tempfile
import shutil
import getpass
import argparse
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime

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
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            self.log_file = log_file
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
    def __init__(self, name, ip, username="pkrv"):
        self.name = name
        self.ip = ip
        self.username = username
        self.status = "offline"
        self.connected = False
        self.last_check = None
    def to_dict(self):
        return {
            'name': self.name, 'ip': self.ip, 'username': self.username,
            'status': self.status, 'connected': self.connected,
            'last_check': self.last_check.strftime('%H:%M:%S') if self.last_check else 'Никогда'
        }

class BenchConnector:
    STANDS = {
        "ГОЗ": {"ip": "192.168.243.248", "username": "pkrv"},
        "Арктика": {"ip": "192.168.243.249", "username": "pkrv"},
        "C1M": {"ip": "192.168.243.254", "username": "pkrv"},
        "OrangePi": {"ip": "192.168.243.46", "username": "orangepi"}
    }
    
    def __init__(self):
        self.logger = LogManager()
        self.stands = {}
        self.connections = {}
        self.passwords = {}
        self.monitoring = False
        self._init_stands()
    
    def _init_stands(self):
        for name, cfg in self.STANDS.items():
            self.stands[name] = StandInfo(name, cfg['ip'], cfg['username'])
    
    def check_availability(self, ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            r = s.connect_ex((ip, 22))
            s.close()
            return r == 0
        except: return False
    
    def start_monitoring(self):
        self.monitoring = True
        def loop():
            while self.monitoring:
                for name, info in self.stands.items():
                    info.last_check = datetime.now()
                    was = info.status
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
        if name not in self.stands: return False
        info = self.stands[name]
        if password is None:
            password = getpass.getpass(f"Пароль для {name} ({info.username}@{info.ip}): ")
        
        # Подключение через системный ssh
        try:
            # Проверяем пароль
            cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {info.username}@{info.ip} "echo OK"'
            env = os.environ.copy()
            if os.name == 'nt':  # Windows
                # Используем plink или встроенный ssh
                pass
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if 'OK' in result.stdout:
                info.connected = True
                self.passwords[name] = password
                self.logger.info(f"Подключен к {name}")
                return True
        except: pass
        return False
    
    def execute(self, name, command, timeout=30):
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
        pwd = self.passwords.get(name, "")
        
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
        print("=" * 50)
        print("СТАТУС СТЕНДОВ")
        print("=" * 50)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name:12} | {info['ip']:16} | {s}")
        bc.stop_monitoring()
        return
    
    if args.console:
        time.sleep(3)
        print("=" * 50)
        print("КОНСОЛЬНЫЙ РЕЖИМ")
        print("=" * 50)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name} ({info['ip']}): {s}")
        print("\nКоманды:")
        print("  bc.connect('ГОЗ')")
        print("  bc.execute('ГОЗ', 'ls -la')")
        import code
        code.interact(local={'bc': bc})
        bc.stop_monitoring()
        return
    
    # GUI - пробуем загрузить PyQt5
    try:
        from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QTabWidget, QTextEdit, QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QHBoxLayout, QMessageBox, QInputDialog, QProgressBar
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QFont, QColor
        
        app = QApplication(sys.argv)
        app.setStyleSheet("QWidget { background: #1a1a2e; color: #e0e0e0; font-size: 12px; }")
        
        window = QMainWindow()
        window.setWindowTitle("Bench Manager")
        window.setGeometry(100, 50, 900, 600)
        
        central = QWidget()
        window.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Заголовок
        title = QLabel("BENCH MANAGER")
        title.setStyleSheet("color: #a0b0ff; font-size: 20px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Вкладки
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # Вкладка стендов
        stands_widget = QWidget()
        stands_layout = QVBoxLayout(stands_widget)
        
        info_label = QLabel("Загрузка стендов...")
        stands_layout.addWidget(info_label)
        
        refresh_btn = QPushButton("ОБНОВИТЬ")
        stands_layout.addWidget(refresh_btn)
        
        def refresh_stands():
            text = ""
            for name, info in bc.get_all_info().items():
                s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
                c = "ПОДКЛЮЧЕН" if info['connected'] else "НЕТ"
                text += f"{name:12} | {info['ip']:16} | {s:8} | {c}\n"
            info_label.setText(text)
        
        refresh_btn.clicked.connect(refresh_stands)
        
        # Кнопка подключения
        connect_btn = QPushButton("ПОДКЛЮЧИТЬСЯ К СТЕНДУ")
        connect_btn.clicked.connect(lambda: bc.connect("ГОЗ"))
        stands_layout.addWidget(connect_btn)
        
        stands_layout.addStretch()
        tabs.addTab(stands_widget, "СТЕНДЫ")
        
        # Вкладка логов
        log_widget = QTextEdit()
        log_widget.setReadOnly(True)
        tabs.addTab(log_widget, "ЛОГИ")
        
        refresh_stands()
        window.show()
        sys.exit(app.exec_())
        
    except ImportError:
        print("PyQt5 не установлен. Запустите: pip install PyQt5")
        print("Или используйте консольный режим: python main.py --console")
        bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
