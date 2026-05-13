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
        "-o MACs=+hmac-md5,hmac-sha1 "
        "-o KexAlgorithms=+diffie-hellman-group1-sha1 "
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

    def _ssh_command(self, name, remote_cmd, use_tty=False, timeout=30):
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
    
    def _scp_copy(self, name, local_path, remote_path):
        """Копирование файла через SCP"""
        info = self.stands[name]
        opts = self.OLD_SSH_OPTS if name in self.STANDS else self.NORMAL_SSH_OPTS
        cmd = f'scp {opts} "{local_path}" {info.username}@{info.ip}:"{remote_path}" 2>&1'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

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
                remote_cmd = f"export LANG=C && export LC_ALL=C && echo '{password}' | su -c 'qconn && ls /home/pkrv/CVS > /dev/null 2>&1 && echo OK || echo FAIL'"
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
        full_cmd = f"export LANG=C && export LC_ALL=C && echo '{pwd}' | su -c 'qconn && {command}'" if name in self.STANDS else command
        code, stdout, stderr = self._ssh_command(name, full_cmd, use_tty=True, timeout=timeout)
        return code == 0, stdout, stderr
    
    def get_all_info(self):
        return {name: {"name": s.name, "ip": s.ip, "username": s.username,
                       "status": s.status, "connected": s.connected,
                       "type": s.stand_type} for name, s in self.stands.items()}
    
    def deploy_files(self, name, mode="move", local_dir=None):
        """
        Деплой файлов на стенд
        mode: "move" - переименование старых файлов, "remove" - удаление, "copy" - бэкап
        local_dir - директория с локальными файлами (по умолчанию текущая)
        """
        if name not in self.STANDS:
            return False, f"Стенд {name} не найден"
        
        if not self.stands[name].connected:
            return False, "Нет подключения к стенду"
        
        info = self.stands[name]
        if local_dir is None:
            local_dir = os.getcwd()
        
        results = []
        results.append(f"=== Деплой файлов на {name} ===")
        results.append(f"Режим: {mode}")
        results.append("")
        
        # 1. Проверка локальных файлов
        results.append("[1/6] Проверяю локальные файлы...")
        mpo_path = os.path.join(local_dir, "mpo")
        kc_path = os.path.join(local_dir, "KC_mpo.txt")
        cfg_path = os.path.join(local_dir, "1po2_1n.cfg")
        
        if not os.path.exists(mpo_path):
            return False, "Файл mpo не найден в текущей папке"
        results.append("  + Файл mpo найден")
        
        if os.path.exists(kc_path):
            results.append("  + Файл KC_mpo.txt найден")
        else:
            results.append("  ! Файл KC_mpo.txt не найден (будет использован существующий на сервере)")
        
        if os.path.exists(cfg_path):
            results.append("  + Файл 1po2_1n.cfg найден")
        else:
            results.append("  ! Файл 1po2_1n.cfg не найден (будет использован существующий на сервере)")
        results.append("")
        
        # 2. Бэкап файлов с сервера (только в режиме copy)
        backup_dir = None
        if mode == "copy":
            results.append("[2/6] Режим copy: копирую файлы с сервера в локальную папку...")
            backup_dir = os.path.join(local_dir, "back", datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(backup_dir, exist_ok=True)
            results.append(f"  + Создана папка для бэкапа: {backup_dir}")
            
            # Копируем mpo
            ok, err = self._scp_copy(name, f"{info.username}@{info.ip}:/home/pkrv/CVS/mpo", 
                                      os.path.join(backup_dir, "mpo").replace("\\", "/"))
            if ok:
                results.append("  + mpo скопирован с сервера")
            else:
                results.append("  ! mpo не найден на сервере или не удалось скопировать")
            
            # Копируем KC_mpo.txt
            ok, err = self._scp_copy(name, f"{info.username}@{info.ip}:/home/pkrv/CVS/KC_mpo.txt",
                                      os.path.join(backup_dir, "KC_mpo.txt").replace("\\", "/"))
            if ok:
                results.append("  + KC_mpo.txt скопирован с сервера")
            else:
                results.append("  ! KC_mpo.txt не найден на сервере или не удалось скопировать")
            
            # Копируем 1po2_1n.cfg
            ok, err = self._scp_copy(name, f"{info.username}@{info.ip}:/fpo_cfg/1po2_1n.cfg",
                                      os.path.join(backup_dir, "1po2_1n.cfg").replace("\\", "/"))
            if ok:
                results.append("  + 1po2_1n.cfg скопирован с сервера")
            else:
                results.append("  ! 1po2_1n.cfg не найден на сервере или не удалось скопировать")
            
            results.append(f"  + Бэкап сохранён в {backup_dir}")
            results.append("")
        
        # 3. Обработка старых файлов на сервере
        step_num = "2" if mode == "copy" else "2"
        results.append(f"[{step_num}/6] Подготовка сервера: обработка старых файлов...")
        
        if mode == "remove":
            remote_cleanup_cmd = """
if [ -f /home/pkrv/CVS/mpo ]; then
    rm -f /home/pkrv/CVS/mpo
    echo '  Старый файл mpo удалён'
fi
if [ -f /home/pkrv/CVS/KC_mpo.txt ]; then
    rm -f /home/pkrv/CVS/KC_mpo.txt
    echo '  Старый файл KC_mpo.txt удалён'
fi
if [ -f /fpo_cfg/1po2_1n.cfg ]; then
    rm -f /fpo_cfg/1po2_1n.cfg
    echo '  Старый файл 1po2_1n.cfg удалён'
fi
"""
        else:  # move or copy
            remote_cleanup_cmd = """
if [ -f /home/pkrv/CVS/mpo ]; then
    mv /home/pkrv/CVS/mpo /home/pkrv/CVS/mpo_old
    echo '  Найден старый mpo, переименован в mpo_old'
else
    echo '  Старый файл mpo отсутствует'
fi
if [ -f /home/pkrv/CVS/KC_mpo.txt ]; then
    mv /home/pkrv/CVS/KC_mpo.txt /home/pkrv/CVS/KC_mpo.txt_old
    echo '  Найден старый KC_mpo.txt, переименован в KC_mpo.txt_old'
fi
if [ -f /fpo_cfg/1po2_1n.cfg ]; then
    mv /fpo_cfg/1po2_1n.cfg /fpo_cfg/1po2_1n.cfg_old
    echo '  Найден старый 1po2_1n.cfg, переименован в 1po2_1n.cfg_old'
fi
"""
        
        code, stdout, stderr = self._ssh_command(name, remote_cleanup_cmd, use_tty=False, timeout=15)
        results.append(stdout)
        if stderr:
            results.append(f"  Ошибки: {stderr}")
        results.append("")
        
        # 4. Копирование новых файлов
        step_num = "3" if mode == "copy" else "3"
        results.append(f"[{step_num}/6] Копирование новых файлов на сервер...")
        
        # Копируем mpo
        ok, err = self._scp_copy(name, mpo_path, "/home/pkrv/CVS/mpo")
        if ok:
            results.append("  + Новый файл mpo скопирован")
        else:
            results.append(f"  ОШИБКА: Не удалось скопировать файл mpo - {err}")
            return False, "\n".join(results)
        
        # Копируем KC_mpo.txt
        if os.path.exists(kc_path):
            ok, err = self._scp_copy(name, kc_path, "/home/pkrv/CVS/KC_mpo.txt")
            if ok:
                results.append("  + KC_mpo.txt скопирован")
            else:
                results.append(f"  ! Не удалось скопировать KC_mpo.txt - {err}")
        
        # Копируем 1po2_1n.cfg
        if os.path.exists(cfg_path):
            ok, err = self._scp_copy(name, cfg_path, "/fpo_cfg/1po2_1n.cfg")
            if ok:
                results.append("  + 1po2_1n.cfg скопирован в /fpo_cfg")
            else:
                results.append(f"  ! Не удалось скопировать 1po2_1n.cfg - {err}")
        else:
            results.append("  ! Файл 1po2_1n.cfg отсутствует локально")
        results.append("")
        
        # 5. Настройка окружения на сервере
        step_num = "4" if mode == "copy" else "4"
        results.append(f"[{step_num}/6] Настройка окружения на сервере...")
        
        remote_setup_cmd = """
# qconn если не запущен
if ! pgrep qconn > /dev/null; then
    su -c "qconn" &
    sleep 1
    echo "  + qconn запущен"
else
    echo "  + qconn уже работает"
fi

# Создание /fpo_cfg
if [ ! -d "/fpo_cfg" ]; then
    mkdir -p /fpo_cfg
    echo "  + Создана директория /fpo_cfg"
else
    echo "  + Директория /fpo_cfg существует"
fi

# Проверка файла конфигурации
if [ -f "/fpo_cfg/1po2_1n.cfg" ]; then
    echo "  + Файл 1po2_1n.cfg присутствует в /fpo_cfg"
else
    echo "  ! Внимание: файл 1po2_1n.cfg отсутствует в /fpo_cfg"
fi

# Ссылка /fea_hd
if [ ! -L "/fea_hd" ]; then
    [ -e "/fea_hd" ] && rm -rf /fea_hd
    ln -s /fs/ssd0/fea_hd /fea_hd
    echo "  + Создана ссылка /fea_hd -> /fs/ssd0/fea_hd"
else
    echo "  + Ссылка /fea_hd уже существует"
fi

# Ссылка /tmp_hd
if [ ! -L "/tmp_hd" ]; then
    [ -e "/tmp_hd" ] && rm -rf /tmp_hd
    ln -s /fs/ssd0/tmp_hd /tmp_hd
    echo "  + Создана ссылка /tmp_hd -> /fs/ssd0/tmp_hd"
else
    echo "  + Ссылка /tmp_hd уже существует"
fi

# Переход в директорию CVS
cd /home/pkrv/CVS || exit 1

# Обновление символьной ссылки
if [ -L "1po2_1n" ]; then
    rm 1po2_1n
    echo "  + Удалена старая ссылка 1po2_1n"
fi

ln -s mpo 1po2_1n
echo "  + Создана ссылка 1po2_1n -> mpo"

# Права на выполнение
chmod +x mpo
echo "  + Выданы права на выполнение файлу mpo"

# Синхронизация
sync
echo "  + Выполнена синхронизация"
"""
        
        code, stdout, stderr = self._ssh_command(name, remote_setup_cmd, use_tty=False, timeout=30)
        results.append(stdout)
        if stderr:
            results.append(f"  Ошибки: {stderr}")
        
        if code != 0:
            results.append("")
            results.append("  ОШИБКА: Не удалось выполнить настройку на сервере")
            return False, "\n".join(results)
        
        results.append("")
        results.append("=== ДЕПЛОЙ ЗАВЕРШЕН УСПЕШНО ===")
        
        return True, "\n".join(results)
    
    def diagnose_connection(self, name):
        """Диагностика проблем подключения (с таймаутами)"""
        results = []
        
        # 1. Проверка сети
        info = self.stands[name]
        results.append(f"=== Диагностика {name} ({info.ip}) ===")
        results.append(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        results.append("")
        
        # Ping с таймаутом
        try:
            if sys.platform == "win32":
                ping_result = subprocess.run(
                    f"ping -n 1 -w 2000 {info.ip}",
                    shell=True, 
                    capture_output=True, 
                    text=True, 
                    timeout=3
                )
            else:
                ping_result = subprocess.run(
                    f"ping -c 1 -W 2 {info.ip}",
                    shell=True, 
                    capture_output=True, 
                    text=True, 
                    timeout=3
                )
            
            if ping_result.returncode == 0:
                results.append("  Ping: OK")
            else:
                results.append("  Ping: FAIL (хост не отвечает)")
        except subprocess.TimeoutExpired:
            results.append("  Ping: TIMEOUT")
        except Exception as e:
            results.append(f"  Ping: ERROR - {str(e)}")
        
        # Проверка SSH порта
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            port_result = sock.connect_ex((info.ip, 22))
            sock.close()
            if port_result == 0:
                results.append("  Port 22: OPEN")
            else:
                results.append(f"  Port 22: CLOSED (код: {port_result})")
        except Exception as e:
            results.append(f"  Port 22: ERROR - {str(e)}")
        
        results.append("")
        results.append("--- SSH подключение ---")
        
        # 2. Проверка SSH с разными опциями
        cmd = f'ssh {self.OLD_SSH_OPTS} {info.username}@{info.ip} "exit 0" 2>&1'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8)
            if r.returncode == 0:
                results.append("  SSH (OLD): OK")
            else:
                error_msg = r.stderr[:100] if r.stderr else r.stdout[:100]
                results.append(f"  SSH (OLD): FAIL - {error_msg}")
        except subprocess.TimeoutExpired:
            results.append("  SSH (OLD): TIMEOUT")
        except Exception as e:
            results.append(f"  SSH (OLD): ERROR - {str(e)}")
        
        results.append("")
        results.append("--- Авторизация ---")
        
        # 3. Проверка su с паролем (только для основных стендов)
        if name in self.STANDS:
            cmd = f'ssh {self.OLD_SSH_OPTS} {info.username}@{info.ip} "echo \'{info.password}\' | su -c \'whoami\' 2>&1"'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                if "root" in r.stdout:
                    results.append("  su: OK (получен root)")
                else:
                    out_part = r.stdout[:100] if r.stdout else ""
                    err_part = r.stderr[:100] if r.stderr else ""
                    results.append(f"  su: FAIL - {out_part} {err_part}")
            except subprocess.TimeoutExpired:
                results.append("  su: TIMEOUT")
            except Exception as e:
                results.append(f"  su: ERROR - {str(e)}")
        
        results.append("")
        results.append("--- Проверка qconn ---")
        
        # 4. Проверка qconn
        if name in self.STANDS:
            cmd = f'ssh {self.OLD_SSH_OPTS} {info.username}@{info.ip} "echo \'{info.password}\' | su -c \'which qconn\' 2>&1"'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                if r.stdout.strip():
                    results.append(f"  qconn: FOUND ({r.stdout.strip()[:50]})")
                else:
                    results.append("  qconn: NOT FOUND")
            except subprocess.TimeoutExpired:
                results.append("  qconn: TIMEOUT")
            except Exception as e:
                results.append(f"  qconn: ERROR - {str(e)}")
        
        results.append("")
        results.append("--- Проверка целевой папки ---")
        
        # 5. Проверка доступа к папке CVS
        if name in self.STANDS:
            cmd = f'ssh {self.OLD_SSH_OPTS} {info.username}@{info.ip} "echo \'{info.password}\' | su -c \'test -d /home/pkrv/CVS && echo OK || echo FAIL\' 2>&1"'
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                if "OK" in r.stdout:
                    results.append("  CVS папка: OK")
                else:
                    results.append(f"  CVS папка: FAIL - {r.stderr[:80]}")
            except subprocess.TimeoutExpired:
                results.append("  CVS папка: TIMEOUT")
            except Exception as e:
                results.append(f"  CVS папка: ERROR - {str(e)}")
        
        results.append("")
        results.append("=== ДИАГНОСТИКА ЗАВЕРШЕНА ===")
        
        return "\n".join(results)

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
            QLineEdit, QMessageBox, QFrame, QTreeWidget, QTreeWidgetItem,
            QGroupBox, QRadioButton, QButtonGroup
        )
        from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
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
        
        class DiagnosticThread(QThread):
            """Поток для выполнения диагностики"""
            result_ready = pyqtSignal(str)
            status_update = pyqtSignal(str)
            finished = pyqtSignal()
            
            def __init__(self, name):
                super().__init__()
                self.name = name
            
            def run(self):
                try:
                    self.status_update.emit("Проверка сети...")
                    result = bc.diagnose_connection(self.name)
                    self.result_ready.emit(result)
                    self.status_update.emit("Диагностика завершена")
                except Exception as e:
                    self.result_ready.emit(f"Ошибка при диагностике:\n{str(e)}")
                    self.status_update.emit(f"Ошибка: {str(e)[:50]}")
                finally:
                    self.finished.emit()
        
        class DeployThread(QThread):
            """Поток для выполнения деплоя"""
            result_ready = pyqtSignal(str)
            status_update = pyqtSignal(str)
            finished = pyqtSignal()
            
            def __init__(self, name, mode, local_dir):
                super().__init__()
                self.name = name
                self.mode = mode
                self.local_dir = local_dir
            
            def run(self):
                try:
                    self.status_update.emit(f"Деплой в режиме {self.mode}...")
                    ok, result = bc.deploy_files(self.name, self.mode, self.local_dir)
                    self.result_ready.emit(result)
                    self.status_update.emit("Деплой завершен" if ok else "Деплой провален")
                except Exception as e:
                    self.result_ready.emit(f"Ошибка при деплое:\n{str(e)}")
                    self.status_update.emit(f"Ошибка: {str(e)[:50]}")
                finally:
                    self.finished.emit()
        
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
                self.create_deploy_tab()
                self.create_logs_tab()
                self.create_diagnostics_tab()
            
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
                for path, label in [("/home/pkrv/CVS", "CVS"), ("/tmp", "/tmp"), ("/fead_hd", "fead_hd")]:
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
                btn_row.addWidget(QPushButton("ВВЕРХ", clicked=self.up_stand))
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
                op_btn.addWidget(QPushButton("ВВЕРХ", clicked=self.up_op))
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
            
            def create_deploy_tab(self):
                """Вкладка деплоя файлов"""
                deploy_tab = QWidget()
                deploy_layout = QVBoxLayout(deploy_tab)
                
                # Выбор стенда
                stand_row = QHBoxLayout()
                stand_row.addStretch()
                stand_row.addWidget(QLabel("Стенд:"))
                self.deploy_stand = QComboBox()
                self.deploy_stand.addItems(["ГОЗ", "Арктика", "C1M"])
                stand_row.addWidget(self.deploy_stand)
                stand_row.addStretch()
                deploy_layout.addLayout(stand_row)
                
                # Выбор режима
                mode_group = QGroupBox("Режим деплоя")
                mode_layout = QHBoxLayout()
                self.deploy_mode_move = QRadioButton("Move (переименовать старые)")
                self.deploy_mode_move.setChecked(True)
                self.deploy_mode_remove = QRadioButton("Remove (удалить старые)")
                self.deploy_mode_copy = QRadioButton("Copy (бэкап на локальный ПК)")
                
                mode_layout.addWidget(self.deploy_mode_move)
                mode_layout.addWidget(self.deploy_mode_remove)
                mode_layout.addWidget(self.deploy_mode_copy)
                mode_group.setLayout(mode_layout)
                deploy_layout.addWidget(mode_group)
                
                # Путь к локальным файлам
                path_row = QHBoxLayout()
                path_row.addWidget(QLabel("Папка с файлами:"))
                self.deploy_path = QLineEdit(os.getcwd())
                self.deploy_path.setMinimumWidth(400)
                path_row.addWidget(self.deploy_path)
                path_row.addWidget(QPushButton("...", clicked=self.select_deploy_path, maximumWidth=30))
                deploy_layout.addLayout(path_row)
                
                # Кнопки
                btn_row = QHBoxLayout()
                btn_row.addStretch()
                self.deploy_btn = QPushButton("ЗАПУСТИТЬ ДЕПЛОЙ")
                self.deploy_btn.setMinimumHeight(40)
                self.deploy_btn.setStyleSheet("background-color: #ff9800; font-size: 14px; font-weight: bold;")
                self.deploy_btn.clicked.connect(self.run_deploy)
                btn_row.addWidget(self.deploy_btn)
                btn_row.addStretch()
                deploy_layout.addLayout(btn_row)
                
                # Вывод лога
                self.deploy_log = QTextEdit()
                self.deploy_log.setReadOnly(True)
                self.deploy_log.setFont(QFont("Consolas", 10))
                self.deploy_log.setStyleSheet("background: #0d0d1a; color: #00ff00;")
                deploy_layout.addWidget(self.deploy_log)
                
                self.deploy_status = QLabel("Готов к деплою")
                self.deploy_status.setStyleSheet("color: #888; font-size: 11px;")
                deploy_layout.addWidget(self.deploy_status)
                
                self.tabs.addTab(deploy_tab, "ДЕПЛОЙ")
            
            def create_logs_tab(self):
                log_tab = QWidget()
                log_layout = QVBoxLayout(log_tab)
                
                self.log_text = QTextEdit()
                self.log_text.setReadOnly(True)
                self.log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas;")
                log_layout.addWidget(self.log_text)
                
                log_layout.addWidget(QPushButton("ОЧИСТИТЬ", clicked=lambda: self.log_text.clear()))
                
                self.tabs.addTab(log_tab, "ЛОГИ")
            
            def create_diagnostics_tab(self):
                """Вкладка диагностики"""
                diag_tab = QWidget()
                diag_layout = QVBoxLayout(diag_tab)
                
                self.diag_stand = QComboBox()
                self.diag_stand.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
                diag_layout.addWidget(self.diag_stand)
                
                self.diag_text = QTextEdit()
                self.diag_text.setReadOnly(True)
                self.diag_text.setFont(QFont("Consolas", 10))
                diag_layout.addWidget(self.diag_text)
                
                self.diag_status = QLabel("Готов к диагностике")
                self.diag_status.setStyleSheet("color: #888; font-size: 11px;")
                diag_layout.addWidget(self.diag_status)
                
                self.diag_btn = QPushButton("ЗАПУСТИТЬ ДИАГНОСТИКУ")
                self.diag_btn.clicked.connect(self.run_diagnostic)
                diag_layout.addWidget(self.diag_btn)
                
                self.tabs.addTab(diag_tab, "ДИАГНОСТИКА")
            
            def select_deploy_path(self):
                """Выбор папки с файлами для деплоя"""
                from PyQt5.QtWidgets import QFileDialog
                folder = QFileDialog.getExistingDirectory(self, "Выберите папку с файлами mpo, KC_mpo.txt, 1po2_1n.cfg")
                if folder:
                    self.deploy_path.setText(folder)
            
            def run_deploy(self):
                """Запуск деплоя"""
                name = self.deploy_stand.currentText()
                
                # Проверка подключения
                if not bc.stands[name].connected:
                    QMessageBox.warning(self, "Ошибка", f"Стенд {name} не подключен! Сначала подключитесь к стенду.")
                    return
                
                # Определяем режим
                if self.deploy_mode_move.isChecked():
                    mode = "move"
                elif self.deploy_mode_remove.isChecked():
                    mode = "remove"
                else:
                    mode = "copy"
                
                local_dir = self.deploy_path.text()
                if not os.path.exists(local_dir):
                    QMessageBox.warning(self, "Ошибка", f"Папка {local_dir} не существует!")
                    return
                
                # Блокируем кнопки
                self.deploy_stand.setEnabled(False)
                self.deploy_btn.setEnabled(False)
                self.deploy_log.clear()
                self.deploy_status.setText(f"Выполняется деплой на {name} в режиме {mode}...")
                self.deploy_status.setStyleSheet("color: #ff9800; font-size: 11px;")
                
                # Запускаем поток деплоя
                self.deploy_thread = DeployThread(name, mode, local_dir)
                self.deploy_thread.result_ready.connect(self.on_deploy_result)
                self.deploy_thread.status_update.connect(self.on_deploy_status)
                self.deploy_thread.finished.connect(self.on_deploy_finished)
                self.deploy_thread.start()
            
            def on_deploy_result(self, result):
                """Получение результата деплоя"""
                self.deploy_log.setText(result)
            
            def on_deploy_status(self, status):
                """Обновление статуса деплоя"""
                self.deploy_status.setText(status)
            
            def on_deploy_finished(self):
                """Окончание деплоя"""
                self.deploy_stand.setEnabled(True)
                self.deploy_btn.setEnabled(True)
                if "УСПЕШНО" in self.deploy_log.toPlainText():
                    self.deploy_status.setStyleSheet("color: #4caf50; font-size: 11px;")
            
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
                    return
                
                self.connecting_states[name] = True
                self.update_all_cards()
                
                # Запускаем поток подключения
                self.connect_thread = ConnectThread(name)
                self.connect_thread.finished.connect(self.on_connect_finished)
                self.connect_thread.start()
            
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
            
            def run_diagnostic(self):
                """Запуск диагностики в отдельном потоке"""
                self.diag_stand.setEnabled(False)
                self.diag_btn.setEnabled(False)
                self.diag_text.clear()
                self.diag_status.setText("Выполняется диагностика...")
                self.diag_status.setStyleSheet("color: #ff9800; font-size: 11px;")
                
                name = self.diag_stand.currentText()
                
                self.diag_thread = DiagnosticThread(name)
                self.diag_thread.result_ready.connect(self.on_diagnostic_result)
                self.diag_thread.status_update.connect(self.on_diagnostic_status)
                self.diag_thread.finished.connect(self.on_diagnostic_finished)
                self.diag_thread.start()
            
            def on_diagnostic_result(self, result):
                self.diag_text.setText(result)
            
            def on_diagnostic_status(self, status):
                self.diag_status.setText(status)
            
            def on_diagnostic_finished(self):
                self.diag_stand.setEnabled(True)
                self.diag_btn.setEnabled(True)
                if "Ошибка" not in self.diag_status.text() and "завершена" not in self.diag_status.text():
                    self.diag_status.setStyleSheet("color: #4caf50; font-size: 11px;")
            
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
            QGroupBox { border: 1px solid #3a3a6a; border-radius: 8px; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QRadioButton { color: #e0e0e0; spacing: 8px; }
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
