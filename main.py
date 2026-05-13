#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
# ПРОВЕРКА SSH-ИНСТРУМЕНТОВ
# ============================================================

SSH_TOOLS = {
    "sshpass": False,
    "expect": False,
    "ssh": False
}

def check_ssh_tools():
    """Проверяем доступность sshpass и других утилит"""
    try:
        subprocess.run(["sshpass", "-V"], capture_output=True, timeout=2)
        SSH_TOOLS["sshpass"] = True
    except:
        SSH_TOOLS["sshpass"] = False

    try:
        subprocess.run(["expect", "-v"], capture_output=True, timeout=2)
        SSH_TOOLS["expect"] = True
    except:
        SSH_TOOLS["expect"] = False

    try:
        subprocess.run(["ssh", "-V"], capture_output=True, timeout=2)
        SSH_TOOLS["ssh"] = True
    except:
        SSH_TOOLS["ssh"] = False

check_ssh_tools()

# ============================================================
# КЛАСС ДЛЯ АВТОМАТИЗАЦИИ SSH
# ============================================================

class SSHAutomator:
    """Класс для работы с SSH, поддерживающий разные методы авторизации"""
    
    def _get_ssh_options(self, name):
        """Возвращает опции SSH для конкретного стенда"""
        basic_opts = (
            "-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=10 "
            "-o LogLevel=ERROR"
        )
        
        old_opts = (
            "-o HostKeyAlgorithms=+ssh-rsa "
            "-o PubkeyAcceptedKeyTypes=+ssh-rsa "
            "-o MACs=+hmac-md5,hmac-sha1 "
            "-o KexAlgorithms=+diffie-hellman-group1-sha1 "
        )
        
        # Старые стенды (ГОЗ, Арктика, C1M) требуют старых алгоритмов
        if name in ["ГОЗ", "Арктика", "C1M"]:
            return f"{basic_opts} {old_opts}"
        else:
            return basic_opts

# ============================================================
# КОННЕКТОР СТЕНДОВ
# ============================================================

class StandInfo:
    def __init__(self, name, ip, username="pkrv", password="zxcv", stand_type="", port=22):
        self.name = name
        self.ip = ip
        self.username = username
        self.password = password
        self.status = "offline"
        self.connected = False
        self.last_check = None
        self.stand_type = stand_type
        self.port = port

class BenchConnector:
    STANDS = {
        "ГОЗ": {"ip": "192.168.243.248", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "port": 22},
        "Арктика": {"ip": "192.168.243.249", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "port": 22},
        "C1M": {"ip": "192.168.243.254", "username": "pkrv", "password": "zxcv", "type": "Основной стенд", "port": 22},
    }
    
    ORANGEPI = {"ip": "192.168.243.46", "username": "orangepi", "password": "", "type": "Orange Pi", "port": 22}
    
    def __init__(self):
        self.stands = {}
        self.monitoring = False
        self.ssh_automator = SSHAutomator()
        self._init_stands()
    
    def _init_stands(self):
        for name, cfg in self.STANDS.items():
            self.stands[name] = StandInfo(
                name, cfg['ip'], cfg['username'], 
                cfg.get('password', ''), cfg.get('type', ''),
                cfg.get('port', 22)
            )
        self.stands["OrangePi"] = StandInfo(
            "OrangePi", self.ORANGEPI['ip'], self.ORANGEPI['username'],
            self.ORANGEPI.get('password', ''), self.ORANGEPI.get('type', ''),
            self.ORANGEPI.get('port', 22)
        )
    
    def check_availability(self, ip, port=22):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            r = s.connect_ex((ip, port))
            s.close()
            return r == 0
        except: 
            return False
    
    def start_monitoring(self):
        """Запуск мониторинга доступности"""
        if self.monitoring: 
            return
        self.monitoring = True
        def loop():
            while self.monitoring:
                for name, info in self.stands.items():
                    if self.check_availability(info.ip, info.port):
                        info.status = "online"
                    else:
                        info.status = "offline"
                        info.connected = False
                time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()
    
    def stop_monitoring(self): 
        self.monitoring = False

    def _get_ssh_opts(self, name):
        """Возвращает опции SSH"""
        return self.ssh_automator._get_ssh_options(name)
    
    def _ssh_command(self, name, remote_cmd, use_tty=False, timeout=30, password=None):
        """
        Выполнение SSH команды с автоматической авторизацией.
        """
        info = self.stands[name]
        pwd = password or info.password
        opts = self._get_ssh_opts(name)
        tty_opt = "-tt" if use_tty else ""
        port_opt = f"-p {info.port}" if info.port != 22 else ""
        
        # Пробуем sshpass
        if SSH_TOOLS.get("sshpass") and pwd:
            cmd = f'sshpass -p "{pwd}" ssh {opts} {port_opt} {tty_opt} {info.username}@{info.ip} "{remote_cmd}"'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                return r.returncode, r.stdout, r.stderr
            except:
                pass
        
        # Пробуем expect
        if SSH_TOOLS.get("expect") and pwd:
            expect_script = f'''
            spawn ssh {opts} {port_opt} {tty_opt} {info.username}@{info.ip} "{remote_cmd}"
            expect {{
                "password:" {{ send "{pwd}\\r"; exp_continue }}
                "yes/no" {{ send "yes\\r"; exp_continue }}
                eof
            }}
            catch wait result
            exit [lindex $result 3]
            '''
            cmd = f'echo "{expect_script}" | expect -f -'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                return r.returncode, r.stdout, r.stderr
            except:
                pass
        
        # Если ничего нет - используем обычный ssh
        cmd = f'ssh {opts} {port_opt} {tty_opt} {info.username}@{info.ip} "{remote_cmd}"'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except Exception as e:
            return -1, "", str(e)
    
    def _scp_copy(self, name, local_path, remote_path):
        """Копирование файла через SCP с авторизацией"""
        info = self.stands[name]
        opts = self._get_ssh_opts(name)
        pwd = info.password
        port_opt = f"-P {info.port}" if info.port != 22 else ""
        
        if SSH_TOOLS.get("sshpass") and pwd:
            cmd = f'sshpass -p "{pwd}" scp {opts} {port_opt} "{local_path}" {info.username}@{info.ip}:"{remote_path}" 2>&1'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                return r.returncode == 0, r.stderr if r.stderr else r.stdout
            except:
                pass
        
        if SSH_TOOLS.get("expect") and pwd:
            expect_script = f'''
            spawn scp {opts} {port_opt} "{local_path}" {info.username}@{info.ip}:"{remote_path}"
            expect {{
                "password:" {{ send "{pwd}\\r"; exp_continue }}
                "yes/no" {{ send "yes\\r"; exp_continue }}
                eof
            }}
            catch wait result
            exit [lindex $result 3]
            '''
            cmd = f'echo "{expect_script}" | expect -f -'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                return r.returncode == 0, r.stderr if r.stderr else r.stdout
            except:
                pass
        
        cmd = f'scp {opts} {port_opt} "{local_path}" {info.username}@{info.ip}:"{remote_path}"'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return r.returncode == 0, r.stderr if r.stderr else r.stdout
        except Exception as e:
            return False, str(e)

    def connect(self, name, password=None):
        """
        Подключение к стенду с полной авторизацией.
        Для старых стендов: ssh -> sudo su
        """
        try:
            if name not in self.stands:
                return False, f"Стенд {name} не найден"
            
            info = self.stands[name]
            if password is None:
                password = info.password
            
            if not password and info.username != "root":
                return False, f"Нет пароля для стенда {name}"
            
            # Для старых стендов (ГОЗ, Арктика, C1M)
            if name in self.STANDS:
                # 1. Проверяем SSH доступ
                test_cmd = "echo SSH_OK"
                code, stdout, stderr = self._ssh_command(name, test_cmd, timeout=10, password=password)
                
                if code != 0:
                    if "Permission denied" in stdout or "Permission denied" in stderr:
                        return False, f"Неверный логин/пароль для {name}@{info.ip}"
                    return False, f"Не удалось подключиться к {name} ({info.ip})\n{stderr[:200]}"
                
                # 2. Выполняем sudo для получения прав
                connect_cmd = f'echo "{password}" | sudo -S echo SU_OK'
                code, stdout, stderr = self._ssh_command(name, connect_cmd, use_tty=False, timeout=20, password=password)
                
                if "SU_OK" in stdout:
                    info.connected = True
                    return True, f"Подключен к {name}\n(права sudo получены)"
                else:
                    return False, (
                        f"Не удалось выполнить sudo на {name}\n"
                        f"stdout: {stdout[-300:]}\n"
                        f"stderr: {stderr[-300:]}"
                    )
            else:
                # Для OrangePi и других современных систем
                code, stdout, stderr = self._ssh_command(name, "echo OK", timeout=10, password=password)
                if code == 0:
                    info.connected = True
                    return True, f"Подключен к {name}"
                return False, f"Ошибка подключения к {name}\n{stdout[-200:]}{stderr[-200:]}"
                
        except Exception as e:
            return False, f"Критическая ошибка: {str(e)}"
    
    def auto_connect_all_stands(self):
        """Функция для автоматического подключения всех стендов"""
        results = {}
        for name in self.stands:
            print(f"Попытка подключения: {name}")
            try:
                success, message = self.connect(name)
                if success:
                    print(f"Статус {name}: Успешно")
                    results[name] = True
                else:
                    print(f"Статус {name}: Ошибка - {message}")
                    results[name] = False
                    results['Error'] = message
            except Exception as e:
                print(f"Статус {name}: Ошибка исключения - {str(e)}")
                results[name] = False
                results['Error'] = str(e)
        return results
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        """
        Выполнение команды на стенде.
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        
        info = self.stands[name]
        pwd = info.password
        
        if name in self.STANDS:
            full_cmd = f'echo "{pwd}" | sudo -S bash -c "{command}"'
            code, stdout, stderr = self._ssh_command(name, full_cmd, use_tty=False, timeout=timeout, password=pwd)
        else:
            code, stdout, stderr = self._ssh_command(name, command, timeout=timeout, password=pwd)
        
        return code == 0, stdout, stderr
    
    def get_all_info(self):
        return {name: {"name": s.name, "ip": s.ip, "username": s.username,
                       "status": s.status, "connected": s.connected,
                       "type": s.stand_type, "port": s.port} for name, s in self.stands.items()}
    
    def list_files(self, name, remote_path="/", password=None):
        """Показать содержимое папки на стенде"""
        if name not in self.stands:
            return False, f"Стенд {name} не найден"
        
        cmd = f"ls -la {remote_path} 2>&1"
        code, stdout, stderr = self.execute(name, cmd, timeout=10)
        
        if code == 0:
            return True, f"Содержимое {remote_path}:\n\n{stdout.strip()}"
        else:
            return False, f"Не удалось прочитать {remote_path}:\n{stderr}"
    
    def delete_file(self, name, remote_path, password=None):
        """Удалить файл на стенде"""
        if name not in self.stands:
            return False, f"Стенд {name} не найден"
        
        cmd = f"rm -f {remote_path} && echo OK"
        code, stdout, stderr = self.execute(name, cmd, timeout=10)
        
        if code == 0 and "OK" in stdout:
            return True, f"Файл {remote_path} удалён"
        else:
            return False, f"Не удалось удалить {remote_path}:\n{stderr}"
    
    def deploy_files(self, name, mode="move", local_dir=None):
        """Деплой файлов на стенд"""
        if name not in self.STANDS:
            return False, f"Стенд {name} не найден"
        
        if not self.stands[name].connected:
            return False, "Нет подключения к стенду"
        
        if local_dir is None:
            local_dir = os.getcwd()
        
        results = []
        results.append(f"=== Деплой файлов на {name} ===")
        results.append(f"Режим: {mode}")
        results.append("")
        
        # 1. Проверка локальных файлов
        results.append("[1/4] Проверяю локальные файлы...")
        mpo_path = os.path.join(local_dir, "mpo")
        
        if not os.path.exists(mpo_path):
            return False, "Файл mpo не найден в текущей папке"
        results.append("  + Файл mpo найден")
        results.append("")
        
        # 2. Копирование файлов
        results.append("[2/4] Копирование файлов на сервер...")
        
        ok, err = self._scp_copy(name, mpo_path, "/home/pkrv/CVS/mpo")
        if ok:
            results.append("  + mpo скопирован")
        else:
            results.append(f"  ОШИБКА: {err}")
            return False, "\n".join(results)
        results.append("")
        
        # 3. Настройка прав
        results.append("[3/4] Настройка прав...")
        setup_cmd = "chmod +x /home/pkrv/CVS/mpo && sync"
        code, stdout, stderr = self.execute(name, setup_cmd, timeout=10)
        results.append("  + Права установлены")
        results.append("")
        
        # 4. Проверка
        results.append("[4/4] Проверка...")
        check_cmd = "ls -la /home/pkrv/CVS/mpo"
        code, stdout, stderr = self.execute(name, check_cmd, timeout=10)
        if code:
            results.append("  + Файл на месте")
        else:
            results.append("  ! Ошибка проверки")
        
        results.append("")
        results.append("=== ДЕПЛОЙ ЗАВЕРШЕН ===")
        
        return True, "\n".join(results)
    
    def diagnose_connection(self, name):
        """Диагностика проблем подключения"""
        results = []
        info = self.stands[name]
        
        results.append(f"=== Диагностика {name} ({info.ip}:{info.port}) ===")
        results.append(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        results.append(f"sshpass: {'есть' if SSH_TOOLS.get('sshpass') else 'нет'}")
        results.append(f"expect: {'есть' if SSH_TOOLS.get('expect') else 'нет'}")
        results.append("")
        
        # Ping
        results.append("--- Сеть ---")
        try:
            ping_param = "-n 1 -w 2000" if sys.platform == "win32" else "-c 1 -W 2"
            ping = subprocess.run(f"ping {ping_param} {info.ip}", shell=True, capture_output=True, text=True, timeout=3)
            results.append(f"  Ping: {'OK' if ping.returncode == 0 else 'FAIL'}")
        except:
            results.append("  Ping: TIMEOUT")
        
        # SSH порт
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            port = sock.connect_ex((info.ip, info.port))
            sock.close()
            results.append(f"  Port {info.port}: {'OPEN' if port == 0 else 'CLOSED'}")
        except:
            results.append(f"  Port {info.port}: ERROR")
        
        # SSH тест
        results.append("")
        results.append("--- SSH ---")
        test_cmd = "echo SSH_OK"
        code, stdout, stderr = self._ssh_command(name, test_cmd, timeout=10)
        if code == 0 and "SSH_OK" in stdout:
            results.append("  SSH: OK")
        else:
            results.append(f"  SSH: FAIL\n  stdout: {stdout[:100]}\n  stderr: {stderr[:100]}")
        
        results.append("")
        results.append("=== ДИАГНОСТИКА ЗАВЕРШЕНА ===")
        
        return "\n".join(results)


# ============================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================================

bc = None
stand_cards = {}


# ============================================================
# MAIN
# ============================================================

def main():
    global bc, stand_cards
    
    parser = argparse.ArgumentParser(description="Bench Manager")
    parser.add_argument('--console', '-c', action='store_true', help='Консольный режим с автоподключением')
    parser.add_argument('--check', action='store_true', help='Проверить статус стендов')
    parser.add_argument('--version', '-v', action='store_true', help='Версия')
    parser.add_argument('--info', action='store_true', help='Информация об SSH инструментах')
    parser.add_argument('--stand', '-s', type=str, help='Подключиться к конкретному стенду (имя)')
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v2.0")
        return
    
    if args.info:
        print("=== SSH Инструменты ===")
        print(f"  sshpass: {'есть' if SSH_TOOLS.get('sshpass') else 'нет'}")
        print(f"  expect: {'есть' if SSH_TOOLS.get('expect') else 'нет'}")
        print(f"  ssh: {'есть' if SSH_TOOLS.get('ssh') else 'нет'}")
        if not SSH_TOOLS.get('sshpass') and not SSH_TOOLS.get('expect'):
            print("\nРекомендуется установить sshpass для автоматического ввода пароля")
            print("  Windows: choco install sshpass")
            print("  Linux: sudo apt install sshpass")
            print("  Mac: brew install sshpass")
        return
    
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(2)
    
    # Консольный режим с автоподключением всех стендов
    if args.console:
        print("\n=== АВТОМАТИЧЕСКОЕ ПОДКЛЮЧЕНИЕ КО ВСЕМ СТЕНДАМ ===\n")
        results = bc.auto_connect_all_stands()
        print("\n=== ИТОГОВЫЕ РЕЗУЛЬТАТЫ ===")
        for name, success in results.items():
            if name != 'Error':
                print(f"  {name}: {'✓ УСПЕШНО' if success else '✗ ОШИБКА'}")
        if 'Error' in results:
            print(f"\nПоследняя ошибка: {results['Error']}")
        bc.stop_monitoring()
        return
    
    # Подключение к конкретному стенду
    if args.stand:
        print(f"\n=== ПОДКЛЮЧЕНИЕ К СТЕНДУ {args.stand} ===\n")
        ok, msg = bc.connect(args.stand)
        print(f"Результат: {'✓ УСПЕШНО' if ok else '✗ ОШИБКА'}")
        print(f"Сообщение: {msg}")
        bc.stop_monitoring()
        return
    
    # Проверка статуса стендов
    if args.check:
        time.sleep(3)
        print("\n=== ДОСТУПНЫЕ СТЕНДЫ ===\n")
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name:12} | {info['ip']:16}:{info['port']} | {s}")
        bc.stop_monitoring()
        return
    
    # GUI режим
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
            QWidget, QPushButton, QTabWidget, QTextEdit, QComboBox,
            QLineEdit, QMessageBox, QFrame, QTreeWidget, QTreeWidgetItem,
            QGroupBox
        )
        from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
        from PyQt5.QtGui import QPixmap, QIcon, QColor, QFont
        
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
            def __init__(self, name, ip, username, stand_type, port=22):
                super().__init__()
                self.stand_name = name
                self.setFixedSize(340, 480)
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
                name_lbl.setStyleSheet("color: #cdd6f4; font-size: 20px; font-weight: bold;")
                name_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(name_lbl)
                
                ip_lbl = QLabel(f"{username}@{ip}:{port}")
                ip_lbl.setStyleSheet("color: #8a8aaa; font-size: 12px;")
                ip_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(ip_lbl)
                
                if stand_type:
                    type_lbl = QLabel(stand_type)
                    type_lbl.setStyleSheet("color: #6a6aaa; font-size: 10px;")
                    type_lbl.setAlignment(Qt.AlignCenter)
                    layout.addWidget(type_lbl)
                
                layout.addSpacing(20)
                
                self.status_lbl = QLabel("OFFLINE")
                self.status_lbl.setStyleSheet("color: #f44336; font-size: 16px; font-weight: bold;")
                self.status_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.status_lbl)
                
                self.connect_btn = QPushButton("ПОДКЛЮЧИТЬ")
                self.connect_btn.setStyleSheet("background-color: #4caf50;")
                self.connect_btn.setMinimumHeight(35)
                layout.addWidget(self.connect_btn)
                
                self.disconnect_btn = QPushButton("ОТКЛЮЧИТЬ")
                self.disconnect_btn.setStyleSheet("background-color: #d24a4a;")
                self.disconnect_btn.setEnabled(False)
                self.disconnect_btn.setMinimumHeight(35)
                layout.addWidget(self.disconnect_btn)
                
                layout.addStretch()
            
            def update_status(self, status, connected, is_connecting=False):
                if is_connecting:
                    self.status_lbl.setText("CONNECTING...")
                    self.status_lbl.setStyleSheet("color: #ff9800; font-size: 16px; font-weight: bold;")
                    self.connect_btn.setEnabled(False)
                    self.disconnect_btn.setEnabled(False)
                elif status == "online":
                    self.status_lbl.setText("ONLINE")
                    self.status_lbl.setStyleSheet("color: #4caf50; font-size: 16px; font-weight: bold;")
                    self.connect_btn.setEnabled(not connected)
                    self.disconnect_btn.setEnabled(connected)
                else:
                    self.status_lbl.setText("OFFLINE")
                    self.status_lbl.setStyleSheet("color: #f44336; font-size: 16px; font-weight: bold;")
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
        
        class DiagnosticThread(QThread):
            finished = pyqtSignal(str, str)
            
            def __init__(self, name):
                super().__init__()
                self.name = name
            
            def run(self):
                result = bc.diagnose_connection(self.name)
                self.finished.emit(self.name, result)
        
        class DeployThread(QThread):
            finished = pyqtSignal(str, bool, str)
            
            def __init__(self, name, mode, local_dir):
                super().__init__()
                self.name = name
                self.mode = mode
                self.local_dir = local_dir
            
            def run(self):
                ok, msg = bc.deploy_files(self.name, self.mode, self.local_dir)
                self.finished.emit(self.name, ok, msg)
        
        class MainWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self.connecting_states = {}
                self.init_ui()
                self.setup_timer()
            
            def init_ui(self):
                self.setWindowTitle("Bench Manager")
                self.setGeometry(100, 100, 1200, 800)
                
                central = QWidget()
                self.setCentralWidget(central)
                layout = QVBoxLayout(central)
                layout.setSpacing(10)
                layout.setContentsMargins(15, 15, 15, 15)
                
                header = QLabel("BENCH MANAGER")
                header.setStyleSheet("font-size: 28px; font-weight: bold; color: #a0b0ff; padding: 15px;")
                header.setAlignment(Qt.AlignCenter)
                layout.addWidget(header)
                
                self.status_label = QLabel("ЗАГРУЗКА...")
                self.status_label.setStyleSheet("color: #888; font-size: 12px;")
                self.status_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(self.status_label)
                
                self.tabs = QTabWidget()
                layout.addWidget(self.tabs)
                
                self.create_stands_tab()
                self.create_deploy_tab()
                self.create_logs_tab()
                self.create_diagnostics_tab()
            
            def create_stands_tab(self):
                tab = QWidget()
                layout = QVBoxLayout(tab)
                layout.setAlignment(Qt.AlignCenter)
                
                cards_widget = QWidget()
                cards_layout = QHBoxLayout(cards_widget)
                cards_layout.setSpacing(25)
                cards_layout.setAlignment(Qt.AlignCenter)
                
                for name in ["ГОЗ", "Арктика", "C1M", "OrangePi"]:
                    info = bc.stands[name]
                    card = StandCard(name, info.ip, info.username, info.stand_type, info.port)
                    card.connect_btn.clicked.connect(lambda checked, n=name: self.connect_stand(n))
                    card.disconnect_btn.clicked.connect(lambda checked, n=name: self.disconnect_stand(n))
                    cards_layout.addWidget(card)
                    stand_cards[name] = card
                
                layout.addWidget(cards_widget, alignment=Qt.AlignCenter)
                
                refresh_btn = QPushButton("ОБНОВИТЬ")
                refresh_btn.setMaximumWidth(200)
                refresh_btn.clicked.connect(self.update_all_cards)
                layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
                
                self.tabs.addTab(tab, "СТЕНДЫ")
            
            def create_deploy_tab(self):
                tab = QWidget()
                layout = QVBoxLayout(tab)
                
                group = QGroupBox("Параметры деплоя")
                group_layout = QVBoxLayout()
                
                stand_row = QHBoxLayout()
                stand_row.addWidget(QLabel("Стенд:"))
                self.deploy_stand = QComboBox()
                self.deploy_stand.addItems(["ГОЗ", "Арктика", "C1M"])
                stand_row.addWidget(self.deploy_stand)
                stand_row.addStretch()
                group_layout.addLayout(stand_row)
                
                mode_row = QHBoxLayout()
                mode_row.addWidget(QLabel("Режим:"))
                self.deploy_mode = QComboBox()
                self.deploy_mode.addItems(["move (переименовать)", "remove (удалить)", "copy (бэкап)"])
                mode_row.addWidget(self.deploy_mode)
                mode_row.addStretch()
                group_layout.addLayout(mode_row)
                
                path_row = QHBoxLayout()
                path_row.addWidget(QLabel("Папка:"))
                self.deploy_path = QLineEdit(os.getcwd())
                path_row.addWidget(self.deploy_path)
                browse_btn = QPushButton("Обзор")
                browse_btn.clicked.connect(self.browse_deploy_path)
                path_row.addWidget(browse_btn)
                group_layout.addLayout(path_row)
                
                group.setLayout(group_layout)
                layout.addWidget(group)
                
                self.deploy_log = QTextEdit()
                self.deploy_log.setReadOnly(True)
                layout.addWidget(self.deploy_log)
                
                self.deploy_btn = QPushButton("ЗАПУСТИТЬ ДЕПЛОЙ")
                self.deploy_btn.setStyleSheet("background-color: #ff9800; font-size: 14px;")
                self.deploy_btn.setMinimumHeight(40)
                self.deploy_btn.clicked.connect(self.run_deploy)
                layout.addWidget(self.deploy_btn)
                
                self.tabs.addTab(tab, "ДЕПЛОЙ")
            
            def create_logs_tab(self):
                tab = QWidget()
                layout = QVBoxLayout(tab)
                
                self.log_text = QTextEdit()
                self.log_text.setReadOnly(True)
                layout.addWidget(self.log_text)
                
                clear_btn = QPushButton("ОЧИСТИТЬ")
                clear_btn.clicked.connect(self.log_text.clear)
                layout.addWidget(clear_btn)
                
                self.tabs.addTab(tab, "ЛОГИ")
            
            def create_diagnostics_tab(self):
                tab = QWidget()
                layout = QVBoxLayout(tab)
                
                sel_row = QHBoxLayout()
                sel_row.addStretch()
                sel_row.addWidget(QLabel("Стенд:"))
                self.diag_stand = QComboBox()
                self.diag_stand.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
                sel_row.addWidget(self.diag_stand)
                sel_row.addStretch()
                layout.addLayout(sel_row)
                
                self.diag_text = QTextEdit()
                self.diag_text.setReadOnly(True)
                self.diag_text.setFont(QFont("Consolas", 10))
                layout.addWidget(self.diag_text)
                
                self.diag_btn = QPushButton("ЗАПУСТИТЬ ДИАГНОСТИКУ")
                self.diag_btn.setStyleSheet("background-color: #2196f3;")
                self.diag_btn.setMinimumHeight(40)
                self.diag_btn.clicked.connect(self.run_diagnostic)
                layout.addWidget(self.diag_btn)
                
                self.tabs.addTab(tab, "ДИАГНОСТИКА")
            
            def setup_timer(self):
                self.timer = QTimer()
                self.timer.timeout.connect(self.update_all_cards)
                self.timer.start(3000)
                QTimer.singleShot(500, self.update_all_cards)
            
            def update_all_cards(self):
                for name, card in stand_cards.items():
                    if name in bc.stands:
                        stand = bc.stands[name]
                        is_connecting = self.connecting_states.get(name, False)
                        card.update_status(stand.status, stand.connected, is_connecting)
                
                online = sum(1 for s in bc.stands.values() if s.status == "online")
                connected = sum(1 for s in bc.stands.values() if s.connected)
                self.status_label.setText(f"ONLINE: {online}/4 | ПОДКЛЮЧЕНО: {connected}")
            
            def connect_stand(self, name):
                info = bc.stands[name]
                if info.status != "online":
                    QMessageBox.warning(self, "Ошибка", f"Стенд {name} не в сети!")
                    return
                
                if self.connecting_states.get(name, False):
                    return
                
                self.connecting_states[name] = True
                self.update_all_cards()
                
                self.connect_thread = ConnectThread(name)
                self.connect_thread.finished.connect(self.on_connect_finished)
                self.connect_thread.start()
            
            def on_connect_finished(self, name, ok, msg):
                self.connecting_states[name] = False
                
                if ok:
                    QMessageBox.information(self, "Успех", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Подключен к {name}")
                else:
                    QMessageBox.critical(self, "Ошибка", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка: {msg[:100]}")
                
                self.update_all_cards()
            
            def disconnect_stand(self, name):
                bc.disconnect(name)
                self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Отключен от {name}")
                self.update_all_cards()
            
            def browse_deploy_path(self):
                from PyQt5.QtWidgets import QFileDialog
                folder = QFileDialog.getExistingDirectory(self, "Выберите папку с файлами", self.deploy_path.text())
                if folder:
                    self.deploy_path.setText(folder)
            
            def run_deploy(self):
                name = self.deploy_stand.currentText()
                
                if not bc.stands[name].connected:
                    QMessageBox.warning(self, "Ошибка", f"Стенд {name} не подключен!")
                    return
                
                mode_map = {
                    "move (переименовать)": "move",
                    "remove (удалить)": "remove",
                    "copy (бэкап)": "copy"
                }
                mode = mode_map.get(self.deploy_mode.currentText(), "move")
                local_dir = self.deploy_path.text()
                
                if not os.path.exists(local_dir):
                    QMessageBox.warning(self, "Ошибка", f"Папка {local_dir} не существует!")
                    return
                
                self.deploy_btn.setEnabled(False)
                self.deploy_log.clear()
                self.deploy_btn.setText("ДЕПЛОЙ...")
                
                self.deploy_thread = DeployThread(name, mode, local_dir)
                self.deploy_thread.finished.connect(self.on_deploy_finished)
                self.deploy_thread.start()
            
            def on_deploy_finished(self, name, ok, msg):
                self.deploy_log.setText(msg)
                self.deploy_btn.setText("ЗАПУСТИТЬ ДЕПЛОЙ")
                self.deploy_btn.setEnabled(True)
                
                if ok:
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Деплой на {name} успешен")
                else:
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Деплой на {name} провален")
            
            def run_diagnostic(self):
                name = self.diag_stand.currentText()
                self.diag_btn.setEnabled(False)
                self.diag_text.clear()
                self.diag_btn.setText("ДИАГНОСТИКА...")
                
                self.diag_thread = DiagnosticThread(name)
                self.diag_thread.finished.connect(self.on_diagnostic_finished)
                self.diag_thread.start()
            
            def on_diagnostic_finished(self, name, result):
                self.diag_text.setText(result)
                self.diag_btn.setText("ЗАПУСТИТЬ ДИАГНОСТИКУ")
                self.diag_btn.setEnabled(True)
        
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
            QGroupBox { border: 1px solid #3a3a6a; border-radius: 8px; margin-top: 10px; padding-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #a0b0ff; }
            QComboBox, QLineEdit { background: #2a2a4a; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 4px; padding: 5px 10px; }
            QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; }
            QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }
            QTextEdit { background: #0d0d1a; color: #00ff00; font-family: Consolas; border: 1px solid #3a3a6a; border-radius: 5px; }
        """)
        
        if not SSH_TOOLS.get('sshpass') and not SSH_TOOLS.get('expect'):
            QMessageBox.information(None, "Внимание", 
                "Не установлены sshpass или expect.\n\n"
                "При подключении к стендам пароль нужно будет вводить вручную.\n\n"
                "Для автоматической авторизации установите sshpass:\n"
                "  Windows: choco install sshpass\n"
                "  Linux: sudo apt install sshpass\n"
                "  Mac: brew install sshpass")
        
        window = MainWindow()
        window.show()
        
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"Ошибка: PyQt5 не установлен - {e}")
        print("Установите: pip install PyQt5")
        sys.exit(1)

if __name__ == "__main__":
    main()
