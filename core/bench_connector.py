import sys
import os
import socket
import time
import threading
import getpass
import subprocess
import tempfile
import shutil
import platform
import urllib.request
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime


# ============================================================
# ВСТРОЕННЫЙ ЛОГГЕР
# ============================================================

class LogManager:
    """Логгер без внешних зависимостей"""
    
    def __init__(self):
        self.log_level = "INFO"
        self.log_file = None
        self.log_dir = "logs"
    
    def setup(self, level="INFO", log_file=None):
        self.log_level = level
        if log_file:
            self.log_file = log_file
        else:
            os.makedirs(self.log_dir, exist_ok=True)
            self.log_file = os.path.join(self.log_dir, "bench_manager.log")
    
    def _write(self, level, msg):
        text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
        print(text)
        if self.log_file:
            try:
                os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(text + '\n')
            except:
                pass
    
    def info(self, msg): self._write("INFO", msg)
    def error(self, msg): self._write("ERROR", msg)
    def warning(self, msg): self._write("WARNING", msg)
    def debug(self, msg):
        if self.log_level == "DEBUG":
            self._write("DEBUG", msg)


# ============================================================
# ОПРЕДЕЛЕНИЕ ОС
# ============================================================

def get_os_type():
    """Определяет тип операционной системы"""
    system = platform.system()
    if system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    elif system == "Darwin":
        return "macos"
    else:
        return "unknown"

OS_TYPE = get_os_type()


# ============================================================
# ПОИСК SSH НА WINDOWS
# ============================================================

class WindowsSSHFinder:
    """Ищет доступный SSH-клиент на Windows"""
    
    def __init__(self, logger):
        self.logger = logger
        self.ssh_path = None
        self.scp_path = None
        self.ssh_type = None  # "openssh", "plink", "paramiko"
        self.tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
        
    def find(self) -> bool:
        """Ищет доступный SSH-клиент. Возвращает True если нашел."""
        
        # 1. Проверяем встроенный OpenSSH (Windows 10/11)
        if self._find_openssh():
            return True
        
        # 2. Проверяем plink.exe в папке tools
        if self._find_plink():
            return True
        
        # 3. Проверяем paramiko
        if self._find_paramiko():
            return True
        
        return False
    
    def _find_openssh(self) -> bool:
        """Проверяет наличие встроенного OpenSSH"""
        paths_to_check = [
            "ssh.exe",
            os.path.expandvars(r"%SystemRoot%\System32\OpenSSH\ssh.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\ssh.exe"),
            os.path.expandvars(r"%ProgramFiles%\OpenSSH\ssh.exe"),
        ]
        
        for path in paths_to_check:
            try:
                result = subprocess.run([path, "-V"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 or "OpenSSH" in result.stderr:
                    self.ssh_path = path
                    # Ищем scp рядом
                    scp_path = path.replace("ssh.exe", "scp.exe")
                    if os.path.exists(scp_path):
                        self.scp_path = scp_path
                    else:
                        self.scp_path = path.replace("ssh.exe", "scp.exe")
                    self.ssh_type = "openssh"
                    self.logger.info(f"Найден OpenSSH: {path}")
                    return True
            except:
                pass
        
        return False
    
    def _find_plink(self) -> bool:
        """Проверяет наличие plink.exe"""
        plink_path = os.path.join(self.tools_dir, "plink.exe")
        pscp_path = os.path.join(self.tools_dir, "pscp.exe")
        
        if os.path.exists(plink_path):
            self.ssh_path = plink_path
            self.scp_path = pscp_path if os.path.exists(pscp_path) else plink_path
            self.ssh_type = "plink"
            self.logger.info(f"Найден plink: {plink_path}")
            return True
        
        # Ищем в PATH
        try:
            result = subprocess.run(["where", "plink.exe"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                self.ssh_path = result.stdout.strip().split('\n')[0]
                self.scp_path = self.ssh_path.replace("plink.exe", "pscp.exe")
                self.ssh_type = "plink"
                self.logger.info(f"Найден plink: {self.ssh_path}")
                return True
        except:
            pass
        
        return False
    
    def _find_paramiko(self) -> bool:
        """Проверяет наличие paramiko"""
        try:
            import paramiko
            self.ssh_type = "paramiko"
            self.logger.info("Найден paramiko (Python-библиотека)")
            return True
        except ImportError:
            return False
    
    def download_plink(self) -> bool:
        """Скачивает plink.exe и pscp.exe"""
        self.logger.info("Скачивание PuTTY утилит (plink.exe, pscp.exe)...")
        
        os.makedirs(self.tools_dir, exist_ok=True)
        
        plink_url = "https://the.earth.li/~sgtatham/putty/latest/w64/plink.exe"
        pscp_url = "https://the.earth.li/~sgtatham/putty/latest/w64/pscp.exe"
        
        try:
            self.logger.info("Скачивание plink.exe...")
            urllib.request.urlretrieve(plink_url, os.path.join(self.tools_dir, "plink.exe"))
            
            self.logger.info("Скачивание pscp.exe...")
            urllib.request.urlretrieve(pscp_url, os.path.join(self.tools_dir, "pscp.exe"))
            
            self.ssh_path = os.path.join(self.tools_dir, "plink.exe")
            self.scp_path = os.path.join(self.tools_dir, "pscp.exe")
            self.ssh_type = "plink"
            
            self.logger.info("PuTTY утилиты успешно скачаны")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка скачивания: {e}")
            return False


# ============================================================
# SSH-КЛИЕНТ (КРОССПЛАТФОРМЕННЫЙ)
# ============================================================

class SSHConnection:
    """Управляет SSH-соединением (Windows/Linux/macOS)"""
    
    def __init__(self, ip: str, username: str, password: str = None,
                 ssh_path: str = None, scp_path: str = None, ssh_type: str = None):
        self.ip = ip
        self.username = username
        self.password = password
        self.ssh_path = ssh_path or "ssh"
        self.scp_path = scp_path or "scp"
        self.ssh_type = ssh_type or "openssh"
        self.logger = LogManager()
    
    def execute(self, command: str, timeout: int = 30) -> Tuple[bool, str, str]:
        """Выполняет команду на удаленном стенде"""
        
        if self.ssh_type == "plink":
            return self._execute_plink(command, timeout)
        elif self.ssh_type == "paramiko":
            return self._execute_paramiko(command, timeout)
        else:
            return self._execute_openssh(command, timeout)
    
    def _execute_openssh(self, command: str, timeout: int) -> Tuple[bool, str, str]:
        """Выполнение через OpenSSH"""
        # Создаем временный файл для пароля
        tmp_password_file = None
        
        try:
            if self.password:
                # Создаем файл с паролем для sshpass (Linux/macOS)
                # На Windows используем встроенный OpenSSH с интерактивным вводом
                if OS_TYPE == "windows":
                    return self._execute_windows_ssh(command, timeout)
                else:
                    # Проверяем sshpass
                    if self._has_sshpass():
                        cmd = [
                            'sshpass', '-p', self.password,
                            self.ssh_path,
                            '-o', 'StrictHostKeyChecking=no',
                            '-o', 'UserKnownHostsFile=NUL' if OS_TYPE == "windows" else '-o', 'UserKnownHostsFile=/dev/null',
                            '-o', 'ConnectTimeout=10',
                            f'{self.username}@{self.ip}',
                            command
                        ]
                    else:
                        return self._execute_with_expect(command, timeout)
            else:
                cmd = [
                    self.ssh_path,
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'UserKnownHostsFile=NUL' if OS_TYPE == "windows" else '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=10',
                    '-o', 'BatchMode=yes',
                    f'{self.username}@{self.ip}',
                    command
                ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=(OS_TYPE == "windows"))
            return result.returncode == 0, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return False, "", "Таймаут выполнения"
        except Exception as e:
            return False, "", str(e)
    
    def _execute_windows_ssh(self, command: str, timeout: int) -> Tuple[bool, str, str]:
        """Выполнение через OpenSSH на Windows с паролем"""
        # Windows OpenSSH не поддерживает передачу пароля через аргументы
        # Используем echo для передачи пароля через stdin
        try:
            full_cmd = f'echo {self.password} | {self.ssh_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=10 {self.username}@{self.ip} "{command}"'
            
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=True
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Таймаут выполнения"
        except Exception as e:
            return False, "", str(e)
    
    def _execute_plink(self, command: str, timeout: int) -> Tuple[bool, str, str]:
        """Выполнение через plink.exe"""
        try:
            cmd = [
                self.ssh_path,
                '-ssh',
                '-pw', self.password if self.password else '',
                '-batch',
                '-no-antispoof',
                f'{self.username}@{self.ip}',
                command
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
            return result.returncode == 0, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return False, "", "Таймаут выполнения"
        except Exception as e:
            return False, "", str(e)
    
    def _execute_paramiko(self, command: str, timeout: int) -> Tuple[bool, str, str]:
        """Выполнение через paramiko"""
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=self.ip,
                username=self.username,
                password=self.password,
                timeout=10
            )
            
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            stdout_str = stdout.read().decode('utf-8', errors='ignore')
            stderr_str = stderr.read().decode('utf-8', errors='ignore')
            ssh.close()
            
            return True, stdout_str, stderr_str
            
        except Exception as e:
            return False, "", str(e)
    
    def _execute_with_expect(self, command: str, timeout: int) -> Tuple[bool, str, str]:
        """Выполнение через expect (Linux/macOS)"""
        import tempfile
        
        expect_script = f"""#!/usr/bin/expect -f
set timeout {timeout}
spawn {self.ssh_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {self.username}@{self.ip} "{command}"
expect {{
    "password:" {{
        send "{self.password}\\r"
        expect eof
    }}
    "yes/no" {{
        send "yes\\r"
        expect "password:"
        send "{self.password}\\r"
        expect eof
    }}
    eof
}}
catch wait result
exit [lindex $result 3]
"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
                f.write(expect_script)
                script_path = f.name
            
            os.chmod(script_path, 0o700)
            result = subprocess.run([script_path], capture_output=True, text=True, timeout=timeout + 5)
            os.unlink(script_path)
            
            return result.returncode == 0, result.stdout, result.stderr
        except Exception as e:
            if os.path.exists(script_path):
                os.unlink(script_path)
            return False, "", str(e)
    
    def _has_sshpass(self) -> bool:
        """Проверяет наличие sshpass"""
        try:
            if OS_TYPE == "windows":
                subprocess.run(["where", "sshpass"], capture_output=True, timeout=2)
            else:
                subprocess.run(["which", "sshpass"], capture_output=True, timeout=2)
            return True
        except:
            return False
    
    def upload_file(self, local_path: str, remote_path: str, timeout: int = 60) -> bool:
        """Загружает файл на стенд"""
        try:
            if self.ssh_type == "plink":
                cmd = [
                    self.scp_path,
                    '-pw', self.password if self.password else '',
                    '-batch',
                    local_path,
                    f'{self.username}@{self.ip}:{remote_path}'
                ]
            elif self.ssh_type == "paramiko":
                return self._upload_paramiko(local_path, remote_path)
            else:
                if self._has_sshpass() and self.password:
                    cmd = [
                        'sshpass', '-p', self.password,
                        self.scp_path,
                        '-o', 'StrictHostKeyChecking=no',
                        '-o', 'UserKnownHostsFile=/dev/null',
                        local_path,
                        f'{self.username}@{self.ip}:{remote_path}'
                    ]
                else:
                    cmd = [
                        self.scp_path,
                        '-o', 'StrictHostKeyChecking=no',
                        '-o', 'UserKnownHostsFile=/dev/null',
                        '-o', 'BatchMode=yes',
                        local_path,
                        f'{self.username}@{self.ip}:{remote_path}'
                    ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=(OS_TYPE == "windows"))
            return result.returncode == 0
            
        except Exception as e:
            return False
    
    def _upload_paramiko(self, local_path: str, remote_path: str) -> bool:
        """Загрузка через paramiko SFTP"""
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=self.ip, username=self.username, password=self.password, timeout=10)
            
            sftp = ssh.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            ssh.close()
            return True
        except:
            return False
    
    def download_file(self, remote_path: str, local_path: str, timeout: int = 60) -> bool:
        """Скачивает файл со стенда"""
        try:
            if self.ssh_type == "plink":
                cmd = [
                    self.scp_path,
                    '-pw', self.password if self.password else '',
                    '-batch',
                    f'{self.username}@{self.ip}:{remote_path}',
                    local_path
                ]
            elif self.ssh_type == "paramiko":
                return self._download_paramiko(remote_path, local_path)
            else:
                if self._has_sshpass() and self.password:
                    cmd = [
                        'sshpass', '-p', self.password,
                        self.scp_path,
                        '-o', 'StrictHostKeyChecking=no',
                        '-o', 'UserKnownHostsFile=/dev/null',
                        f'{self.username}@{self.ip}:{remote_path}',
                        local_path
                    ]
                else:
                    cmd = [
                        self.scp_path,
                        '-o', 'StrictHostKeyChecking=no',
                        '-o', 'UserKnownHostsFile=/dev/null',
                        '-o', 'BatchMode=yes',
                        f'{self.username}@{self.ip}:{remote_path}',
                        local_path
                    ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=(OS_TYPE == "windows"))
            return result.returncode == 0
            
        except Exception as e:
            return False
    
    def _download_paramiko(self, remote_path: str, local_path: str) -> bool:
        """Скачивание через paramiko SFTP"""
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=self.ip, username=self.username, password=self.password, timeout=10)
            
            sftp = ssh.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            ssh.close()
            return True
        except:
            return False


# ============================================================
# КЛАСС ИНФОРМАЦИИ О СТЕНДЕ
# ============================================================

class StandInfo:
    """Информация о стенде"""
    
    def __init__(self, name: str, ip: str, username: str = "pkrv", folders: Dict = None):
        self.name = name
        self.ip = ip
        self.username = username
        self.status = "offline"
        self.last_check = None
        self.connected = False
        self.stand_type = self._detect_type()
        self.requires_password = True
        self.folders = folders or {}
    
    def _detect_type(self) -> str:
        ip_to_type = {
            "192.168.243.248": "ГОЗ",
            "192.168.243.249": "Арктика",
            "192.168.243.254": "C1M",
            "192.168.243.46": "OrangePi"
        }
        return ip_to_type.get(self.ip, "Неизвестный")
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'ip': self.ip,
            'username': self.username,
            'status': self.status,
            'type': self.stand_type,
            'connected': self.connected,
            'last_check': self.last_check.strftime('%H:%M:%S') if self.last_check else 'Никогда',
            'requires_password': self.requires_password
        }


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================

class BenchConnector:
    """
    Модуль для взаимодействия со стендами.
    Работает на Windows, Linux, macOS без установки Python-библиотек.
    На Windows автоматически скачивает plink.exe при необходимости.
    """
    
    STANDS_CONFIG = {
        "ГОЗ": {
            "ip": "192.168.243.248",
            "username": "pkrv",
            "folders": {
                "cvs": "/home/pkrv/CVS",
                "tmp": "/tmp",
                "config": "fpo_cfg"
            }
        },
        "Арктика": {
            "ip": "192.168.243.249",
            "username": "pkrv",
            "folders": {
                "cvs": "/home/pkrv/CVS",
                "tmp": "/tmp",
                "config": "fpo_cfg"
            }
        },
        "C1M": {
            "ip": "192.168.243.254",
            "username": "pkrv",
            "folders": {
                "cvs": "/home/pkrv/CVS",
                "tmp": "/tmp",
                "config": "fpo_cfg"
            }
        },
        "OrangePi": {
            "ip": "192.168.243.46",
            "username": "orangepi",
            "folders": {}
        }
    }
    
    def __init__(self, config: Dict = None, check_interval: int = 5,
                 password_provider: Callable[[str], str] = None):
        
        self.logger = LogManager()
        self.logger.setup(level="INFO")
        
        self.stands: Dict[str, StandInfo] = {}
        self.connections: Dict[str, SSHConnection] = {}
        self.check_interval = check_interval
        self.monitoring_active = False
        self.monitor_thread = None
        self.callbacks = []
        self.password_provider = password_provider or self._default_password_provider
        self.passwords_cache: Dict[str, str] = {}
        
        # Инициализация SSH на Windows
        self.ssh_finder = None
        if OS_TYPE == "windows":
            self.ssh_finder = WindowsSSHFinder(self.logger)
            if not self.ssh_finder.find():
                self.logger.warning("SSH-клиент не найден!")
                self.logger.warning("Попытка скачать plink.exe...")
                if not self.ssh_finder.download_plink():
                    self.logger.error("Не удалось получить SSH-клиент.")
                    self.logger.error("Установите OpenSSH или paramiko вручную.")
        
        self._initialize_stands()
        self.logger.info(f"BenchConnector инициализирован (ОС: {OS_TYPE})")
    
    def _initialize_stands(self):
        for stand_name, stand_config in self.STANDS_CONFIG.items():
            stand_info = StandInfo(
                name=stand_name,
                ip=stand_config['ip'],
                username=stand_config['username'],
                folders=stand_config.get('folders', {})
            )
            self.stands[stand_name] = stand_info
    
    def set_password_provider(self, provider: Callable[[str], str]):
        self.password_provider = provider
    
    def _default_password_provider(self, stand_name: str) -> str:
        stand_info = self.stands.get(stand_name)
        username = stand_info.username if stand_info else "pkrv"
        if OS_TYPE == "windows":
            import msvcrt
            print(f"Пароль для {stand_name} ({username}): ", end='', flush=True)
            password = ''
            while True:
                ch = msvcrt.getch()
                if ch == b'\r' or ch == b'\n':
                    print()
                    break
                elif ch == b'\x08':
                    if password:
                        password = password[:-1]
                        print('\b \b', end='', flush=True)
                else:
                    password += ch.decode('utf-8')
                    print('*', end='', flush=True)
            return password
        else:
            return getpass.getpass(f"Пароль для {stand_name} ({username}): ")
    
    def _get_password(self, stand_name: str) -> str:
        if stand_name in self.passwords_cache:
            return self.passwords_cache[stand_name]
        password = self.password_provider(stand_name)
        if password:
            self.passwords_cache[stand_name] = password
        return password
    
    def clear_password_cache(self, stand_name: str = None):
        if stand_name:
            self.passwords_cache.pop(stand_name, None)
        else:
            self.passwords_cache.clear()
    
    def register_callback(self, callback):
        self.callbacks.append(callback)
    
    def _notify_callbacks(self, stand_name: str = None):
        for callback in self.callbacks:
            try:
                if stand_name and stand_name in self.stands:
                    callback(stand_name, self.stands[stand_name].to_dict())
                else:
                    callback(None, self.get_all_stands_info())
            except:
                pass
    
    def start_monitoring(self):
        if self.monitoring_active:
            return
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Мониторинг стендов запущен")
    
    def stop_monitoring(self):
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
    
    def _monitoring_loop(self):
        while self.monitoring_active:
            for stand_name, stand_info in self.stands.items():
                try:
                    previous_status = stand_info.status
                    is_available = self.check_stand_availability(stand_info.ip)
                    
                    if is_available and previous_status != "online":
                        stand_info.status = "online"
                        stand_info.last_check = datetime.now()
                        self.logger.info(f"Стенд {stand_name} ({stand_info.ip}) в сети")
                        self._notify_callbacks(stand_name)
                        
                    elif not is_available and previous_status != "offline":
                        stand_info.status = "offline"
                        stand_info.connected = False
                        stand_info.last_check = datetime.now()
                        self.connections.pop(stand_name, None)
                        self.passwords_cache.pop(stand_name, None)
                        self.logger.warning(f"Стенд {stand_name} ({stand_info.ip}) недоступен")
                        self._notify_callbacks(stand_name)
                    
                    stand_info.last_check = datetime.now()
                except:
                    pass
            
            time.sleep(self.check_interval)
    
    def check_stand_availability(self, ip: str, timeout: int = 2) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, 22))
            sock.close()
            return result == 0
        except:
            return False
    
    def _get_ssh_connection(self, stand_name: str, password: str) -> SSHConnection:
        """Создает SSH-соединение с учетом ОС"""
        stand_info = self.stands[stand_name]
        
        ssh_path = "ssh"
        scp_path = "scp"
        ssh_type = "openssh"
        
        if self.ssh_finder:
            ssh_path = self.ssh_finder.ssh_path or "ssh"
            scp_path = self.ssh_finder.scp_path or "scp"
            ssh_type = self.ssh_finder.ssh_type or "openssh"
        
        return SSHConnection(
            ip=stand_info.ip,
            username=stand_info.username,
            password=password,
            ssh_path=ssh_path,
            scp_path=scp_path,
            ssh_type=ssh_type
        )
    
    def connect_to_stand(self, stand_name: str, password: str = None) -> bool:
        if stand_name not in self.stands:
            self.logger.error(f"Неизвестный стенд: {stand_name}")
            return False
        
        if password is None:
            password = self._get_password(stand_name)
            if not password:
                return False
        
        stand_info = self.stands[stand_name]
        self.logger.info(f"Подключение к {stand_name} ({stand_info.username}@{stand_info.ip})...")
        
        conn = self._get_ssh_connection(stand_name, password)
        success, stdout, stderr = conn.execute("echo OK", timeout=15)
        
        if success and 'OK' in stdout:
            self.connections[stand_name] = conn
            stand_info.connected = True
            stand_info.status = "online"
            self.passwords_cache[stand_name] = password
            self.logger.info(f"Подключен к {stand_name}")
            self._notify_callbacks(stand_name)
            return True
        else:
            self.logger.error(f"Ошибка подключения к {stand_name}: {stderr}")
            stand_info.connected = False
            self.passwords_cache.pop(stand_name, None)
            self._notify_callbacks(stand_name)
            return False
    
    def disconnect_from_stand(self, stand_name: str):
        if stand_name in self.stands:
            self.stands[stand_name].connected = False
            self.connections.pop(stand_name, None)
            self.logger.info(f"Отключен от {stand_name}")
            self._notify_callbacks(stand_name)
    
    def disconnect_all(self):
        for stand_name in list(self.stands.keys()):
            self.disconnect_from_stand(stand_name)
    
    def is_connected(self, stand_name: str) -> bool:
        return stand_name in self.connections and self.stands[stand_name].connected
    
    def execute_command(self, stand_name: str, command: str, timeout: int = 30) -> Tuple[bool, str, str]:
        if stand_name not in self.connections:
            return False, "", "Нет подключения"
        return self.connections[stand_name].execute(command, timeout)
    
    # ============================================================
    # РАБОТА С ПАПКАМИ
    # ============================================================
    
    def get_folder_contents(self, stand_name: str, folder_path: str) -> List[Dict]:
        if stand_name not in self.connections:
            return []
        
        success, stdout, stderr = self.execute_command(
            stand_name,
            f"ls -la --time-style=long-iso {folder_path} 2>/dev/null || dir {folder_path}"
        )
        
        if not success:
            return []
        
        files = []
        for line in stdout.strip().split('\n'):
            if not line.startswith('total') and line.strip():
                parts = line.split()
                if len(parts) >= 8:
                    name = ' '.join(parts[7:])
                    files.append({
                        'name': name,
                        'size': int(parts[4]) if parts[4].isdigit() else 0,
                        'date': parts[5] if len(parts) > 5 else '',
                        'time': parts[6] if len(parts) > 6 else '',
                        'is_dir': line.startswith('d'),
                        'permissions': parts[0] if parts else ''
                    })
        return files
    
    def get_cvs_checksums(self, stand_name: str) -> Dict[str, str]:
        stand_config = self.get_stand_config(stand_name)
        if not stand_config or 'cvs' not in stand_config.get('folders', {}):
            return {}
        
        cvs_path = stand_config['folders']['cvs']
        success, stdout, stderr = self.execute_command(
            stand_name,
            f"cd {cvs_path} 2>/dev/null && md5sum * 2>/dev/null || echo ''"
        )
        
        if not success or not stdout.strip():
            return {}
        
        checksums = {}
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    filename = ' '.join(parts[1:])
                    checksums[filename] = parts[0]
        return checksums
    
    def get_cvs_files(self, stand_name: str) -> List[Dict]:
        stand_config = self.get_stand_config(stand_name)
        if not stand_config or 'cvs' not in stand_config.get('folders', {}):
            return []
        return self.get_folder_contents(stand_name, stand_config['folders']['cvs'])
    
    def get_tmp_files(self, stand_name: str) -> List[Dict]:
        stand_config = self.get_stand_config(stand_name)
        if not stand_config or 'tmp' not in stand_config.get('folders', {}):
            return []
        return self.get_folder_contents(stand_name, stand_config['folders']['tmp'])
    
    def archive_and_download_tmp(self, stand_name: str, files: List[str] = None,
                                  save_path: str = None) -> Optional[str]:
        if stand_name not in self.connections:
            return None
        
        stand_config = self.get_stand_config(stand_name)
        tmp_path = stand_config['folders']['tmp']
        conn = self.connections[stand_name]
        
        archive_name = f"tmp_archive_{stand_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        remote_archive = f"/tmp/{archive_name}"
        
        if files:
            files_str = ' '.join(f'"{f}"' for f in files)
            cmd = f"cd {tmp_path} && tar -czf {remote_archive} {files_str} 2>/dev/null"
        else:
            cmd = f"cd {tmp_path} && tar -czf {remote_archive} . 2>/dev/null"
        
        success, stdout, stderr = conn.execute(cmd, timeout=60)
        
        if not success:
            return None
        
        if save_path is None:
            save_path = os.path.join(os.getcwd(), "downloads", archive_name)
        
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        if conn.download_file(remote_archive, save_path, timeout=120):
            conn.execute(f"rm -f {remote_archive}")
            self.logger.info(f"Архив скачан: {save_path}")
            return save_path
        else:
            conn.execute(f"rm -f {remote_archive}")
            return None
    
    def check_config_file(self, stand_name: str, filename: str = "1po2_1n.cfg") -> Dict:
        stand_config = self.get_stand_config(stand_name)
        if not stand_config:
            return {'exists': False, 'error': 'Конфигурация стенда не найдена'}
        
        config_path = stand_config['folders'].get('config', 'fpo_cfg')
        
        success, stdout, stderr = self.execute_command(
            stand_name,
            f"test -f {config_path}/{filename} && echo 'FOUND' || echo 'NOT_FOUND'"
        )
        
        exists = success and 'FOUND' in stdout
        
        result = {
            'exists': exists,
            'filename': filename,
            'path': config_path,
            'full_path': f"{config_path}/{filename}",
            'message': f"Файл {filename} {'найден' if exists else 'ОТСУТСТВУЕТ'} на {stand_name}"
        }
        
        if not exists:
            self.logger.warning(result['message'])
        else:
            self.logger.info(result['message'])
        
        return result
    
    def check_all_configs(self, filename: str = "1po2_1n.cfg") -> Dict[str, Dict]:
       
