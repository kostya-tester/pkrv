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
import shutil
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

def check_ssh_tools():
    """Проверяем доступность sshpass и других утилит"""
    tools = {}
    
    # Проверяем sshpass
    try:
        subprocess.run(["sshpass", "-V"], capture_output=True, timeout=2)
        tools["sshpass"] = True
    except:
        tools["sshpass"] = False
    
    # Проверяем expect
    try:
        subprocess.run(["expect", "-v"], capture_output=True, timeout=2)
        tools["expect"] = True
    except:
        tools["expect"] = False
    
    # Проверяем обычный ssh
    try:
        subprocess.run(["ssh", "-V"], capture_output=True, timeout=2)
        tools["ssh"] = True
    except:
        tools["ssh"] = False
    
    return tools

SSH_TOOLS = check_ssh_tools()

# ============================================================
# КЛАСС ДЛЯ АВТОМАТИЗАЦИИ SSH
# ============================================================

class SSHAutomator:
    """Класс для работы с SSH, поддерживающий разные методы авторизации"""
    
    def __init__(self):
        self.password_files = {}
    
    def _create_password_file(self, name, password):
        """Создаёт временный файл с паролем для sshpass"""
        import tempfile
        if name not in self.password_files:
            fd, path = tempfile.mkstemp(prefix=f"sshpass_{name}_", suffix=".txt", text=True)
            os.close(fd)
            with open(path, "w") as f:
                f.write(password)
            self.password_files[name] = path
        return self.password_files[name]
    
    def _cleanup(self):
        """Удаляет временные файлы паролей"""
        for path in self.password_files.values():
            try:
                os.unlink(path)
            except:
                pass
        self.password_files.clear()
    
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
    
    def __init__(self):
        self.stands = {}
        self.monitoring = False
        self.ssh_automator = SSHAutomator()
        self._init_stands()
    
    def __del__(self):
        self.ssh_automator._cleanup()
    
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
        """Запуск мониторинга доступности"""
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

    def _get_ssh_opts(self, name):
        """Возвращает опции SSH"""
        return self.ssh_automator._get_ssh_options(name)
    
    def _ssh_command(self, name, remote_cmd, use_tty=False, timeout=30, password=None):
        """
        Выполнение SSH команды с автоматической авторизацией.
        Использует sshpass для передачи пароля.
        """
        info = self.stands[name]
        pwd = password or info.password
        opts = self._get_ssh_opts(name)
        
        if use_tty:
            tty_opt = "-tt"
        else:
            tty_opt = ""
        
        if SSH_TOOLS.get("sshpass"):
            cmd = f'sshpass -p "{pwd}" ssh {opts} {tty_opt} {info.username}@{info.ip} "{remote_cmd}"'
        else:
            expect_script = f'''
            spawn ssh {opts} {tty_opt} {info.username}@{info.ip} "{remote_cmd}"
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
            r = subprocess.run(
                cmd, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=timeout,
                env={**os.environ, 'LANG': 'C', 'LC_ALL': 'C'}
            )
            out = r.stdout if r.stdout else ""
            err = r.stderr if r.stderr else ""
            return r.returncode, out, err
        except subprocess.TimeoutExpired:
            return -1, "", "Таймаут подключения"
        except Exception as e:
            return -1, "", str(e)
    
    def _scp_copy(self, name, local_path, remote_path):
        """Копирование файла через SCP с авторизацией"""
        info = self.stands[name]
        opts = self._get_ssh_opts(name)
        pwd = info.password
        
        if SSH_TOOLS.get("sshpass"):
            cmd = f'sshpass -p "{pwd}" scp {opts} "{local_path}" {info.username}@{info.ip}:"{remote_path}" 2>&1'
        else:
            expect_script = f'''
            spawn scp {opts} "{local_path}" {info.username}@{info.ip}:"{remote_path}"
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
        except Exception as e:
            return False, str(e)

    def connect(self, name, password=None):
        """
        Подключение к стенду с полной авторизацией.
        Для старых стендов: ssh -> su (через sudo)
        """
        try:
            if name not in self.stands:
                return False, f"Стенд {name} не найден"
            
            info = self.stands[name]
            if password is None:
                password = info.password
            
            if not password and info.username != "root":
                return False, f"Нет пароля для стенда {name}"
            
            # Для старых стендов (ГОЗ, Арктика, C1M) нужен su
            if name in self.STANDS:
                # 1. Проверка SSH
                test_cmd = "echo SSH_OK"
                code, stdout, stderr = self._ssh_command(name, test_cmd, timeout=10, password=password)
                
                if code != 0:
                    if "Permission denied" in stdout or "Permission denied" in stderr:
                        return False, f"Неверный логин/пароль для {name}@{info.ip}"
                    return False, f"Не удалось подключиться к {name} ({info.ip})\n{stderr[:200]}"
                
                # 2. Выполняем su через sudo (надёжнее)
                connect_cmd = (
                    f'echo "{password}" | sudo -S -v 2>/dev/null && '
                    f'sudo -u root echo SU_OK'
                )
                code, stdout, stderr = self._ssh_command(name, connect_cmd, use_tty=True, timeout=20, password=password)
                
                if "SU_OK" in stdout:
                    info.connected = True
                    return True, f"Подключен к {name}\n(su выполнен)"
                else:
                    return False, (
                        f"Не удалось выполнить su на {name}\n"
                        f"stdout: {stdout[-300:]}\n"
                        f"stderr: {stderr[-300:]}\n"
                        f"exit code: {code}"
                    )
            else:
                # Для OrangePi и других современных систем
                code, stdout, stderr = self._ssh_command(name, "echo OK", timeout=10, password=password)
                if 'OK' in stdout:
                    info.connected = True
                    return True, f"Подключен к {name}"
                return False, f"Ошибка подключения к {name}\n{stdout[-200:]}{stderr[-200:]}"
                
        except Exception as e:
            return False, f"Критическая ошибка: {str(e)}"
    
    def disconnect(self, name):
        if name in self.stands:
            self.stands[name].connected = False
    
    def execute(self, name, command, timeout=30):
        """
        Выполнение команды на стенде.
        Для старых стендов выполняет команду через sudo su.
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        
        info = self.stands[name]
        pwd = info.password
        
        if name in self.STANDS:
            # Для старых стендов выполняем через sudo su
            command_escaped = command.replace('"', '\\"')
            full_cmd = f'echo "{pwd}" | sudo -S su -c "{command_escaped}"'
            code, stdout, stderr = self._ssh_command(name, full_cmd, use_tty=True, timeout=timeout)
        else:
            # Для современных систем напрямую
            code, stdout, stderr = self._ssh_command(name, command, timeout=timeout)
        
        return code == 0, stdout, stderr
    
    def get_all_info(self):
        return {name: {"name": s.name, "ip": s.ip, "username": s.username,
                       "status": s.status, "connected": s.connected,
                       "type": s.stand_type} for name, s in self.stands.items()}
    
    def deploy_files(self, name, mode="move", local_dir=None):
        """Деплой файлов на стенд"""
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
            
            files_to_backup = [
                ("/home/pkrv/CVS/mpo", "mpo"),
                ("/home/pkrv/CVS/KC_mpo.txt", "KC_mpo.txt"),
                ("/fpo_cfg/1po2_1n.cfg", "1po2_1n.cfg")
            ]
            
            for remote_path, local_name in files_to_backup:
                local_file = os.path.join(backup_dir, local_name)
                cat_cmd = f'cat {remote_path}'
                ok, stdout, stderr = self.execute(name, cat_cmd, timeout=15)
                if ok and stdout:
                    with open(local_file, 'w') as f:
                        f.write(stdout)
                    results.append(f"  + {local_name} скопирован с сервера")
                else:
                    results.append(f"  ! {local_name} не найден на сервере")
            
            results.append(f"  + Бэкап сохранён в {backup_dir}")
            results.append("")
        
        # 3. Обработка старых файлов на сервере
        step = "3" if mode == "copy" else "2"
        results.append(f"[{step}/6] Подготовка сервера: обработка старых файлов...")
        
        if mode == "remove":
            cleanup_cmd = """
                rm -f /home/pkrv/CVS/mpo /home/pkrv/CVS/KC_mpo.txt /fpo_cfg/1po2_1n.cfg
                echo "Старые файлы удалены"
            """
        else:
            cleanup_cmd = """
                [ -f /home/pkrv/CVS/mpo ] && mv /home/pkrv/CVS/mpo /home/pkrv/CVS/mpo_old && echo "mpo->mpo_old" || echo "mpo отсутствует"
                [ -f /home/pkrv/CVS/KC_mpo.txt ] && mv /home/pkrv/CVS/KC_mpo.txt /home/pkrv/CVS/KC_mpo.txt_old && echo "KC_mpo.txt->KC_mpo.txt_old" || echo "KC_mpo.txt отсутствует"
                [ -f /fpo_cfg/1po2_1n.cfg ] && mv /fpo_cfg/1po2_1n.cfg /fpo_cfg/1po2_1n.cfg_old && echo "cfg->cfg_old" || echo "cfg отсутствует"
            """
        
        code, stdout, stderr = self.execute(name, cleanup_cmd, timeout=15)
        results.append(stdout if stdout else "  (пусто)")
        if stderr:
            results.append(f"  Ошибки: {stderr}")
        results.append("")
        
        # 4. Копирование новых файлов
        step = "4" if mode == "copy" else "3"
        results.append(f"[{step}/6] Копирование новых файлов на сервер...")
        
        ok, err = self._scp_copy(name, mpo_path, "/home/pkrv/CVS/mpo")
        if ok:
            results.append("  + Новый файл mpo скопирован")
        else:
            results.append(f"  ОШИБКА: Не удалось скопировать файл mpo - {err}")
            return False, "\n".join(results)
        
        if os.path.exists(kc_path):
            ok, err = self._scp_copy(name, kc_path, "/home/pkrv/CVS/KC_mpo.txt")
            if ok:
                results.append("  + KC_mpo.txt скопирован")
            else:
                results.append(f"  ! Не удалось скопировать KC_mpo.txt - {err}")
        
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
        step = "5" if mode == "copy" else "4"
        results.append(f"[{step}/6] Настройка окружения на сервере...")
        
        setup_cmd = """
            if ! pgrep qconn > /dev/null; then
                nohup qconn > /dev/null 2>&1 &
                sleep 1
                echo "  + qconn запущен"
            else
                echo "  + qconn уже работает"
            fi
            
            [ ! -d "/fpo_cfg" ] && mkdir -p /fpo_cfg && echo "  + Создана /fpo_cfg" || echo "  + /fpo_cfg существует"
            [ -f "/fpo_cfg/1po2_1n.cfg" ] && echo "  + cfg в /fpo_cfg" || echo "  ! cfg отсутствует в /fpo_cfg"
            
            [ ! -L "/fea_hd" ] && { [ -e "/fea_hd" ] && rm -rf /fea_hd; ln -s /fs/ssd0/fea_hd /fea_hd; echo "  + Создана /fea_hd"; } || echo "  + /fea_hd существует"
            [ ! -L "/tmp_hd" ] && { [ -e "/tmp_hd" ] && rm -rf /tmp_hd; ln -s /fs/ssd0/tmp_hd /tmp_hd; echo "  + Создана /tmp_hd"; } || echo "  + /tmp_hd существует"
            
            cd /home/pkrv/CVS || exit 1
            [ -L "1po2_1n" ] && rm 1po2_1n && echo "  + Ссылка 1po2_1n удалена"
            ln -s mpo 1po2_1n && echo "  + Создана ссылка 1po2_1n -> mpo"
            chmod +x mpo && echo "  + Права на mpo"
            sync && echo "  + Синхронизация"
        """
        
        code, stdout, stderr = self.execute(name, setup_cmd, timeout=30)
        results.append(stdout if stdout else "  (пусто)")
        if stderr:
            results.append(f"  Ошибки: {stderr}")
        
        if code != 0:
            results.append("")
            results.append("  ОШИБКА: Не удалось выполнить настройку на сервере")
            return False, "\n".join(results)
        
        # 6. Финальная проверка
        step = "6" if mode == "copy" else "5"
        results.append(f"[{step}/6] Финальная проверка...")
        
        check_cmd = """
            echo "=== Проверка ==="
            ls -la /home/pkrv/CVS/mpo /home/pkrv/CVS/1po2_1n 2>&1
            file /home/pkrv/CVS/mpo
        """
        code, stdout, stderr = self.execute(name, check_cmd, timeout=15)
        results.append(stdout if stdout else "  (пусто)")
        results.append("")
        
        results.append("=== ДЕПЛОЙ ЗАВЕРШЕН УСПЕШНО ===")
        
        return True, "\n".join(results)
    
    def diagnose_connection(self, name):
        """Диагностика проблем подключения"""
        results = []
        info = self.stands[name]
        
        results.append(f"=== Диагностика {name} ({info.ip}) ===")
        results.append(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        results.append(f"SSH инструменты: sshpass={'✓' if SSH_TOOLS.get('sshpass') else '✗'}, expect={'✓' if SSH_TOOLS.get('expect') else '✗'}")
        results.append("")
        
        # 1. Ping
        results.append("--- Сеть ---")
        try:
            ping_param = "-n 1 -w 2000" if sys.platform == "win32" else "-c 1 -W 2"
            ping = subprocess.run(f"ping {ping_param} {info.ip}", shell=True, capture_output=True, text=True, timeout=3)
            results.append(f"  Ping: {'OK' if ping.returncode == 0 else 'FAIL'}")
        except:
            results.append("  Ping: TIMEOUT")
        
        # 2. SSH порт
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            port = sock.connect_ex((info.ip, 22))
            sock.close()
            results.append(f"  Port 22: {'OPEN' if port == 0 else f'CLOSED (код: {port})'}")
        except:
            results.append("  Port 22: ERROR")
        
        # 3. SSH тест
        results.append("")
        results.append("--- SSH ---")
        test_cmd = "echo SSH_OK"
        code, stdout, stderr = self._ssh_command(name, test_cmd, timeout=10)
        if "SSH_OK" in stdout:
            results.append("  SSH: OK")
        else:
            results.append(f"  SSH: FAIL\n  stdout: {stdout[:100]}\n  stderr: {stderr[:100]}")
        
        # 4. su тест (для старых стендов)
        if name in self.STANDS:
            results.append("")
            results.append("--- sudo su ---")
            su_cmd = f'echo "{info.password}" | sudo -S su -c "whoami"'
            code, stdout, stderr = self._ssh_command(name, su_cmd, use_tty=True, timeout=10)
            if "root" in stdout:
                results.append("  sudo su: OK (root)")
            else:
                results.append(f"  sudo su: FAIL\n  stdout: {stdout[:100]}\n  stderr: {stderr[:100]}")
        
        # 5. Проверка доступа к папкам
        if name in self.STANDS:
            results.append("")
            results.append("--- Доступ к папкам ---")
            
            cvs_cmd = 'ls -la /home/pkrv/CVS/ 2>&1 | head -5'
            code, stdout, stderr = self.execute(name, cvs_cmd, timeout=10)
            if code and stdout:
                results.append("  /home/pkrv/CVS/:")
                for line in stdout.split('\n')[:3]:
                    if line.strip():
                        results.append(f"    {line[:60]}")
            else:
                results.append(f"  /home/pkrv/CVS/: НЕТ ДОСТУПА - {stderr[:100]}")
            
            cfg_cmd = 'ls -la /fpo_cfg/ 2>&1 | head -5'
            code, stdout, stderr = self.execute(name, cfg_cmd, timeout=10)
            if code and stdout:
                results.append("  /fpo_cfg/:")
                for line in stdout.split('\n')[:3]:
                    if line.strip():
                        results.append(f"    {line[:60]}")
            else:
                results.append(f"  /fpo_cfg/: НЕТ ДОСТУПА - {stderr[:100]}")
        
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
    parser.add_argument('--info', action='store_true', help='Показать информацию об SSH инструментах')
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v2.0.0")
        return
    
    if args.info:
        print("=== SSH Инструменты ===")
        for tool, available in SSH_TOOLS.items():
            print(f"  {tool}: {'✓ Доступен' if available else '✗ Недоступен'}")
        if not SSH_TOOLS.get('sshpass') and not SSH_TOOLS.get('expect'):
            print("\n⚠️ Нет инструментов для автоматической авторизации!")
            print("Установите sshpass:")
            print("  Linux: apt-get install sshpass")
            print("  macOS: brew install hudochenkov/sshpass/sshpass")
            print("  Windows: используйте WSL или установите sshpass через MSYS2")
        return
    
    bc = BenchConnector()
    bc.start_monitoring()
    
    if args.check or args.console:
        time.sleep(3)
        print("=== Доступные стенды ===")
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name:12} | {info['ip']:16} | {s}")
        
        if args.console:
            print("\n=== Подключение к стендам ===")
            for n in ["ГОЗ", "Арктика", "C1M"]:
                print(f"\n{n}:")
                ok, msg = bc.connect(n)
                print(f"  {'✓' if ok else '✗'} {msg}")
        
        bc.stop_monitoring()
        return
    
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
            QWidget, QPushButton, QTabWidget, QTextEdit, QComboBox,
            QLineEdit, QMessageBox, QFrame, QTreeWidget, QTreeWidgetItem,
            QGroupBox
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
                
                quick_row = QHBoxLayout()
                quick_row.addStretch()
                for path, label in [("/home/pkrv/CVS", "CVS"), ("/tmp", "/tmp"), ("/fead_hd", "fead_hd")]:
                    btn = QPushButton(label)
                    btn.setStyleSheet("QPushButton { font-size: 11px; padding: 6px 12px; background-color: #3a3a6a; }")
                    btn.clicked.connect(lambda checked, p=path: self.browse_stand_files(p))
                    quick_row.addWidget(btn)
                quick_row.addStretch()
                files_layout.addLayout(quick_row)
                
                self.files_tree = QTreeWidget()
                self.files_tree.setHeaderLabels(["Имя", "Размер", "Тип", "Дата"])
                self.files_tree.setStyleSheet("QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; } QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; }")
                self.files_tree.itemDoubleClicked.connect(self.cd_stand_folder)
                files_layout.addWidget(self.files_tree)
                
                self.files_log = QTextEdit()
                self.files_log.setReadOnly(True)
                self.files_log.setMaximumHeight(80)
                files_layout.addWidget(self.files_log)
                
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
                self.op_log.setMaximumHeight(80)
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
                deploy_tab = QWidget()
                deploy_layout = QVBoxLayout(deploy_tab)
                
                sel_group = QGroupBox("Параметры деплоя")
                sel_layout = QVBoxLayout()
                
                stand_row = QHBoxLayout()
                stand_row.addWidget(QLabel("Стенд:"))
                self.deploy_stand = QComboBox()
                self.deploy_stand.addItems(["ГОЗ", "Арктика", "C1M"])
                stand_row.addWidget(self.deploy_stand)
                stand_row.addStretch()
                sel_layout.addLayout(stand_row)
                
                mode_row = QHBoxLayout()
                mode_row.addWidget(QLabel("Режим:"))
                self.deploy_mode = QComboBox()
                self.deploy_mode.addItems(["move (переименовать старые)", "remove (удалить старые)", "copy (бэкап на ПК)"])
                mode_row.addWidget(self.deploy_mode)
                mode_row.addStretch()
                sel_layout.addLayout(mode_row)
                
                path_row = QHBoxLayout()
                path_row.addWidget(QLabel("Папка с файлами:"))
                self.deploy_path = QLineEdit(os.getcwd())
                path_row.addWidget(self.deploy_path)
                browse_btn = QPushButton("Обзор")
                browse_btn.clicked.connect(self.browse_deploy_path)
                path_row.addWidget(browse_btn)
                sel_layout.addLayout(path_row)
                
                sel_group.setLayout(sel_layout)
                deploy_layout.addWidget(sel_group)
                
                self.deploy_log = QTextEdit()
                self.deploy_log.setReadOnly(True)
                self.deploy_log.setFont(QFont("Consolas", 10))
                self.deploy_log.setStyleSheet("background: #0d0d1a; color: #00ff00;")
                deploy_layout.addWidget(self.deploy_log)
                
                btn_row = QHBoxLayout()
                btn_row.addStretch()
                self.deploy_btn = QPushButton("ЗАПУСТИТЬ ДЕПЛОЙ")
                self.deploy_btn.setStyleSheet("background-color: #ff9800; font-size: 14px; font-weight: bold; padding: 12px 30px;")
                self.deploy_btn.clicked.connect(self.run_deploy)
                btn_row.addWidget(self.deploy_btn)
                btn_row.addStretch()
                deploy_layout.addLayout(btn_row)
                
                self.tabs.addTab(deploy_tab, "ДЕПЛОЙ")
            
            def create_logs_tab(self):
                log_tab = QWidget()
                log_layout = QVBoxLayout(log_tab)
                
                self.log_text = QTextEdit()
                self.log_text.setReadOnly(True)
                self.log_text.setStyleSheet("background: #0d0d1a; color: #00ff00; font-family: Consolas;")
                log_layout.addWidget(self.log_text)
                
                clear_btn = QPushButton("ОЧИСТИТЬ")
                clear_btn.clicked.connect(self.log_text.clear)
                log_layout.addWidget(clear_btn)
                
                self.tabs.addTab(log_tab, "ЛОГИ")
            
            def create_diagnostics_tab(self):
                diag_tab = QWidget()
                diag_layout = QVBoxLayout(diag_tab)
                
                sel_row = QHBoxLayout()
                sel_row.addStretch()
                sel_row.addWidget(QLabel("Стенд:"))
                self.diag_stand = QComboBox()
                self.diag_stand.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
                sel_row.addWidget(self.diag_stand)
                sel_row.addStretch()
                diag_layout.addLayout(sel_row)
                
                self.diag_text = QTextEdit()
                self.diag_text.setReadOnly(True)
                self.diag_text.setFont(QFont("Consolas", 10))
                self.diag_text.setStyleSheet("background: #0d0d1a; color: #00ff00;")
                diag_layout.addWidget(self.diag_text)
                
                btn_row = QHBoxLayout()
                btn_row.addStretch()
                self.diag_btn = QPushButton("ЗАПУСТИТЬ ДИАГНОСТИКУ")
                self.diag_btn.setStyleSheet("background-color: #2196f3; font-size: 14px; font-weight: bold; padding: 12px 30px;")
                self.diag_btn.clicked.connect(self.run_diagnostic)
                btn_row.addWidget(self.diag_btn)
                btn_row.addStretch()
                diag_layout.addLayout(btn_row)
                
                self.tabs.addTab(diag_tab, "ДИАГНОСТИКА")
            
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
                
                self.connect_thread = ConnectThread(name)
                self.connect_thread.finished.connect(self.on_connect_finished)
                self.connect_thread.start()
            
            def on_connect_finished(self, name, ok, msg):
                self.connecting_states[name] = False
                
                if ok:
                    QMessageBox.information(self, "Успех", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Подключен к {name}")
                    if name == self.files_stand.currentText():
                        QTimer.singleShot(500, self.browse_stand_files)
                else:
                    QMessageBox.critical(self, "Ошибка подключения", msg)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Ошибка подключения к {name}: {msg[:100]}")
                
                self.update_all_cards()
            
            def disconnect_stand(self, name):
                bc.disconnect(name)
                self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Отключен от {name}")
                self.files_tree.clear()
                self.files_log.setText("Стенд отключен")
                self.update_all_cards()
            
            def run_diagnostic(self):
                self.diag_btn.setEnabled(False)
                self.diag_stand.setEnabled(False)
                self.diag_text.clear()
                
                name = self.diag_stand.currentText()
                self.diag_btn.setText("ДИАГНОСТИКА ВЫПОЛНЯЕТСЯ...")
                
                self.diag_thread = DiagnosticThread(name)
                self.diag_thread.result_ready.connect(self.diag_text.setText)
                self.diag_thread.finished.connect(self.on_diag_finished)
                self.diag_thread.start()
            
            def on_diag_finished(self):
                self.diag_btn.setText("ЗАПУСТИТЬ ДИАГНОСТИКУ")
                self.diag_btn.setEnabled(True)
                self.diag_stand.setEnabled(True)
            
            def run_deploy(self):
                name = self.deploy_stand.currentText()
                
                if not bc.stands[name].connected:
                    QMessageBox.warning(self, "Ошибка", f"Стенд {name} не подключен! Сначала подключитесь к стенду.")
                    return
                
                mode_map = {
                    "move (переименовать старые)": "move",
                    "remove (удалить старые)": "remove",
                    "copy (бэкап на ПК)": "copy"
                }
                mode = mode_map.get(self.deploy_mode.currentText(), "move")
                
                local_dir = self.deploy_path.text().strip()
                if not os.path.exists(local_dir):
                    QMessageBox.warning(self, "Ошибка", f"Папка {local_dir} не существует!")
                    return
                
                self.deploy_btn.setEnabled(False)
                self.deploy_stand.setEnabled(False)
                self.deploy_mode.setEnabled(False)
                self.deploy_path.setEnabled(False)
                self.deploy_log.clear()
                self.deploy_btn.setText("ДЕПЛОЙ ВЫПОЛНЯЕТСЯ...")
                
                self.deploy_thread = DeployThread(name, mode, local_dir)
                self.deploy_thread.result_ready.connect(self.deploy_log.setText)
                self.deploy_thread.finished.connect(self.on_deploy_finished)
                self.deploy_thread.start()
            
            def on_deploy_finished(self):
                self.deploy_btn.setText("ЗАПУСТИТЬ ДЕПЛОЙ")
                self.deploy_btn.setEnabled(True)
                self.deploy_stand.setEnabled(True)
                self.deploy_mode.setEnabled(True)
                self.deploy_path.setEnabled(True)
            
            def browse_deploy_path(self):
                from PyQt5.QtWidgets import QFileDialog
                folder = QFileDialog.getExistingDirectory(
                    self, 
                    "Выберите папку с файлами mpo, KC_mpo.txt, 1po2_1n.cfg",
                    self.deploy_path.text()
                )
                if folder:
                    self.deploy_path.setText(folder)
            
            def browse_stand_files(self, path=None):
                if path:
                    self.files_path.setText(path)
                
                name = self.files_stand.currentText()
                path = self.files_path.text().strip() or "/"
                
                if name not in bc.stands:
                    self.files_log.setText(f"Ошибка: Стенд {name} не найден")
                    return
                
                if not bc.stands[name].connected:
                    self.files_log.setText(f"Стенд {name} не подключен! Нажмите ПОДКЛЮЧИТЬ")
                    self.files_tree.clear()
                    return
                
                self.files_tree.clear()
                self.files_log.setText(f"Загрузка {path}...")
                QApplication.processEvents()
                
                ok, out, err = bc.execute(name, f'ls -la --time-style=long-iso "{path}" 2>&1', timeout=15)
                
                if ok:
                    lines = out.split('\n')
                    item_count = 0
                    
                    for line in lines:
                        if line.startswith('total') or not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) >= 8:
                            fname = ' '.join(parts[7:])
                            if fname in ['.', '..']:
                                continue
                            is_dir = line.startswith('d')
                            is_link = '->' in line
                            
                            item = QTreeWidgetItem([
                                fname, 
                                parts[4] if not is_dir else "", 
                                "Папка" if is_dir else ("Ссылка" if is_link else "Файл"), 
                                f"{parts[5]} {parts[6]}" if len(parts) > 6 else ""
                            ])
                            
                            if is_dir:
                                item.setForeground(0, QColor("#61dafb"))
                            elif is_link:
                                item.setForeground(0, QColor("#90ee90"))
                            
                            self.files_tree.addTopLevelItem(item)
                            item_count += 1
                    
                    self.files_log.setText(f"✓ {path} - найдено {item_count} элементов")
                else:
                    error_msg = err if err else out[:200]
                    self.files_log.setText(f"✗ Ошибка: {error_msg}")
            
            def cd_stand_folder(self):
                item = self.files_tree.currentItem()
                if item and item.text(2) == "Папка":
                    current_path = self.files_path.text().rstrip('/')
                    new_path = f"{current_path}/{item.text(0)}"
                    self.files_path.setText(new_path)
                    self.browse_stand_files()
            
            def up_stand(self):
                cur = self.files_path.text().rstrip('/')
                if cur and cur != '/':
                    parent = os.path.dirname(cur)
                    if not parent:
                        parent = '/'
                    self.files_path.setText(parent)
                    self.browse_stand_files()
            
            def browse_op(self):
                name = self.op_stand.currentText()
                path = self.op_path.text().strip() or "/"
                
                if name not in bc.stands:
                    self.op_log.setText(f"Ошибка: Стенд {name} не найден")
                    return
                
                if not bc.stands[name].connected:
                    self.op_log.setText(f"Стенд {name} не подключен! Нажмите ПОДКЛЮЧИТЬ")
                    self.op_tree.clear()
                    return
                
                self.op_tree.clear()
                self.op_log.setText(f"Загрузка {path}...")
                QApplication.processEvents()
                
                ok, out, err = bc.execute(name, f'ls -la --time-style=long-iso "{path}" 2>&1', timeout=15)
                
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
                    
                    self.op_log.setText(f"✓ {path}")
                else:
                    self.op_log.setText(f"✗ Ошибка: {err[:100]}")
            
            def cd_op(self):
                item = self.op_tree.currentItem()
                if item and item.text(2) == "Папка":
                    current_path = self.op_path.text().rstrip('/')
                    new_path = f"{current_path}/{item.text(0)}"
                    self.op_path.setText(new_path)
                    self.browse_op()
            
            def up_op(self):
                cur = self.op_path.text().rstrip('/')
                if cur and cur != '/':
                    parent = os.path.dirname(cur)
                    if not parent:
                        parent = '/'
                    self.op_path.setText(parent)
                    self.browse_op()
            
            def start_process(self):
                n = self.proc_stand.currentText()
                if bc.stands[n].connected:
                    ok, out, err = bc.execute(
                        n, 
                        "cd /home/pkrv/fpo_cfg && nohup ./1po2_1n > /dev/null 2>&1 & echo PID: $!"
                    )
                    if ok:
                        self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ {n}: процесс запущен ({out.strip()})")
                    else:
                        self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {n}: {err[:100]}")
                else:
                    self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠ {n}: не подключен")
            
            def stop_process(self):
                n = self.proc_stand.currentText()
                if bc.stands[n].connected:
                    ok, out, err = bc.execute(n, "pkill -f 1po2_1n 2>&1; slay 1po2_1n 2>&1; echo DONE")
                    self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ {n}: процесс остановлен")
                else:
                    self.proc_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠ {n}: не подключен")
            
            def restart_process(self):
                self.stop_process()
                time.sleep(2)
                self.start_process()
        
        app = QApplication(sys.argv)
        
        logo_p = load_logo()
        if logo_p:
            app.setWindowIcon(QIcon(logo_p))
        
        app.setStyleSheet("""
            QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 13px; }
            QPushButton { background-color: #4a4ad2; color: white; border: none; border-radius: 6px; padding: 10px 18px; font-weight: bold; }
            QPushButton:hover { background-color: #5a5ae2; }
            QPushButton:disabled { background-color: #555; color: #999; }
            QTabWidget::pane { border: 1px solid #3a3a6a; border-radius: 8px; background: #1e1e32; }
            QTabBar::tab { background: #2a2a4a; color: #8a8aaa; padding: 12px 30px; font-weight: bold; font-size: 14px; min-width: 140px; }
            QTabBar::tab:selected { background: #1e1e32; color: #a0b0ff; border-bottom: 3px solid #4a4ad2; }
            QGroupBox { border: 1px solid #3a3a6a; border-radius: 8px; margin-top: 10px; font-weight: bold; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #a0b0ff; }
            QComboBox { background: #2a2a4a; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 4px; padding: 5px 10px; min-width: 150px; }
            QComboBox:hover { border-color: #4a4ad2; }
            QLineEdit { background: #2a2a4a; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 4px; padding: 5px 10px; }
            QLineEdit:hover { border-color: #4a4ad2; }
            QTreeWidget { background: #1e1e32; color: #e0e0e0; border: 1px solid #3a3a6a; border-radius: 5px; }
            QTreeWidget::item:hover { background: #2a2a4a; }
            QTreeWidget::item:selected { background: #3a3a6a; color: #a0b0ff; }
            QHeaderView::section { background: #2a2a4a; color: #a0b0ff; padding: 6px; border: 1px solid #3a3a6a; }
            QTextEdit { background: #0d0d1a; color: #00ff00; font-family: Consolas; border: 1px solid #3a3a6a; border-radius: 5px; padding: 8px; }
        """)
        
        window = MainWindow()
        window_ref = window
        window.show()
        
        sys.exit(app.exec_())
        
    except ImportError as e:
        print(f"⚠ PyQt5 не установлен: {e}")
        print("Установите PyQt5: pip install PyQt5")
        if bc:
            bc.stop_monitoring()
        sys.exit(1)
    except Exception as e:
        print(f"⚠ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        if bc:
            bc.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()
