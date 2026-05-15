#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bench Manager v4.0
- Dark industrial GUI (PyQt5)
- Автоматически получает права su -> qconn при подключении
- Папки: /home/pkrv/CVS, /tmp, /fead_hd, /fs/ (для ГОЗ, С1М, Арктика)
- Папка: cd / (для Orange Pi) + просмотр содержимого файлов
- Браузер папок через SSH (ls), не через SFTP
- Иконки стендов: goz.png, arktika.png, c1m.png, orangepi.png, logo.png
- Пароли из .env / config.yaml
"""

import sys
import os
import time
import socket
import threading
import argparse
import subprocess
from datetime import datetime

# ============================================================
# ПУТИ
# ============================================================
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    APP_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR  = BASE_DIR

IMAGES_DIR  = os.path.join(BASE_DIR, "gui", "images")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
ENV_PATH    = os.path.join(APP_DIR,  ".env")

# ============================================================
# ИКОНКИ
# ============================================================
BOARD_ICON_MAP = {
    "arktika" : "arktika.png",
    "c1m"     : "c1m.png",
    "goz"     : "goz.png",
    "orangepi": "orangepi.png",
}
DEFAULT_ICON = "logo.png"

# Папки по типу платы
BOARD_FOLDERS = {
    "goz"     : ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "c1m"     : ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "arktika" : ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "orangepi": ["/"],
}
DEFAULT_FOLDERS = ["/home/pkrv/CVS", "/tmp"]

# Типы плат которым нужен su qconn
QCONN_TYPES = {"goz", "c1m", "arktika"}


def _icon_path(filename: str) -> str:
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.exists(path) else ""


def _board_icon_path(board_type: str) -> str:
    key      = (board_type or "").strip().lower()
    filename = BOARD_ICON_MAP.get(key, DEFAULT_ICON)
    path     = _icon_path(filename)
    return path or _icon_path(DEFAULT_ICON)


def _board_folders(board_type: str) -> list:
    key = (board_type or "").strip().lower()
    return BOARD_FOLDERS.get(key, DEFAULT_FOLDERS)


# ============================================================
# PARAMIKO
# ============================================================
try:
    import paramiko
    from paramiko.ssh_exception import AuthenticationException, SSHException
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

def _load_env_file():
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


def load_config() -> dict:
    _load_env_file()

    if not HAS_YAML:
        print("WARNING: pyyaml не установлен, используем дефолтный конфиг")
        return _default_config()

    if not os.path.exists(CONFIG_PATH):
        print(f"WARNING: config.yaml не найден: {CONFIG_PATH}")
        return _default_config()

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    for stand in cfg.get("stands", []):
        name_key = stand.get("name", "").upper().replace(" ", "_")
        env_key  = f"BENCH_PASSWORD_{name_key}"
        password = os.environ.get(env_key, "") or stand.get("password", "")
        if not password:
            print(f"WARNING: пароль для '{stand['name']}' не задан")
        stand["password"] = password

    return cfg


def _default_config() -> dict:
    return {
        "stands"    : [],
        "monitoring": {"check_interval": 5, "ssh_timeout": 10},
    }


# ============================================================
# МОДЕЛЬ СТЕНДА
# ============================================================

class StandInfo:
    def __init__(self, name, ip, username="pkrv", password="",
                 stand_type="", port=22, folders=None):
        self.name       = name
        self.ip         = ip
        self.username   = username
        self.password   = password
        self.status     = "offline"
        self.connected  = False
        self.stand_type = stand_type
        self.port       = port
        self.ssh_client = None
        self.folders    = folders or {}
        self.qconn_active = False  # флаг — права qconn получены

    @property
    def needs_qconn(self) -> bool:
        return self.stand_type.strip().lower() in QCONN_TYPES

    @property
    def browse_folders(self) -> list:
        return _board_folders(self.stand_type)

    @property
    def cvs_path(self) -> str:
        return self.folders.get("cvs", self.browse_folders[0])


# ============================================================
# CONNECTOR
# ============================================================

class BenchConnector:

    def __init__(self, config: dict = None):
        self.config     = config or load_config()
        self.stands     = {}
        self.monitoring = False
        self._init_stands()

    def _init_stands(self):
        for sc in self.config.get("stands", []):
            name = sc["name"]
            self.stands[name] = StandInfo(
                name       = name,
                ip         = sc.get("ip", ""),
                username   = sc.get("username", "pkrv"),
                password   = sc.get("password", ""),
                stand_type = sc.get("board", {}).get("type", ""),
                port       = sc.get("port", 22),
                folders    = sc.get("folders", {}),
            )

    # ----------------------------------------------------------
    # Мониторинг
    # ----------------------------------------------------------

    def check_availability(self, ip, port=22) -> bool:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            if s.connect_ex((ip, port)) != 0:
                return False
            s.settimeout(2)
            try:
                banner = s.recv(64)
                return banner.startswith(b"SSH")
            except socket.timeout:
                return True
        except Exception:
            return False
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    def start_monitoring(self):
        if self.monitoring:
            return
        self.monitoring = True

        def loop():
            interval = self.config.get("monitoring", {}).get("check_interval", 5)
            while self.monitoring:
                for name, info in list(self.stands.items()):
                    if info.connected and info.ssh_client:
                        try:
                            transport = info.ssh_client.get_transport()
                            if transport and transport.is_active():
                                info.status = "online"
                                continue
                        except Exception:
                            pass
                        try:
                            info.ssh_client.close()
                        except Exception:
                            pass
                        info.ssh_client  = None
                        info.connected   = False
                        info.qconn_active = False
                        info.status      = "offline"
                        continue
                    available   = self.check_availability(info.ip, info.port)
                    info.status = "online" if available else "offline"
                time.sleep(interval)

        threading.Thread(target=loop, daemon=True).start()

    def stop_monitoring(self):
        self.monitoring = False

    # ----------------------------------------------------------
    # Подключение
    # ----------------------------------------------------------

    def connect(self, name, password=None):
        """
        Подключается по SSH.
        Для плат ГОЗ/С1М/Арктика автоматически запускает su qconn
        (ожидаем что /etc/sudoers содержит: pkrv ALL=(qconn) NOPASSWD: ALL).
        Возвращает (ok, message).
        """
        if not HAS_PARAMIKO:
            return False, "paramiko не установлен"

        if name not in self.stands:
            return False, f"Стенд '{name}' не найден"

        info = self.stands[name]
        pwd  = password or info.password

        if not pwd:
            return False, (
                f"Нет пароля для '{name}'. "
                f"Добавьте BENCH_PASSWORD_{name.upper()} в .env"
            )

        try:
            ssh = paramiko.SSHClient()
            known = os.path.expanduser("~/.ssh/known_hosts")
            if os.path.exists(known):
                try:
                    ssh.load_host_keys(known)
                except Exception:
                    pass
            ssh.set_missing_host_key_policy(paramiko.WarningPolicy())

            timeout = self.config.get("monitoring", {}).get("ssh_timeout", 10)
            ssh.connect(
                hostname      = info.ip,
                port          = info.port,
                username      = info.username,
                password      = pwd,
                timeout       = timeout,
                allow_agent   = False,
                look_for_keys = False,
            )

            _, stdout, _ = ssh.exec_command("echo OK", timeout=5)
            if stdout.read().decode().strip() != "OK":
                ssh.close()
                return False, "Сессия открылась, но echo OK не ответил"

            info.ssh_client  = ssh
            info.connected   = True
            info.status      = "online"
            info.qconn_active = False

            # Автоматически получаем права qconn для нужных плат
            if info.needs_qconn:
                ok_q, msg_q = self._acquire_qconn(info)
                if ok_q:
                    info.qconn_active = True
                    return True, f"Подключено к {name} ({info.ip}) [qconn активен]"
                else:
                    return True, (
                        f"Подключено к {name} ({info.ip}) "
                        f"[qconn НЕДОСТУПЕН: {msg_q}]"
                    )

            return True, f"Подключено к {name} ({info.ip})"

        except AuthenticationException:
            return False, "Ошибка авторизации: неверный логин или пароль"
        except SSHException as e:
            return False, f"SSH ошибка: {e}"
        except (socket.timeout, TimeoutError, OSError) as e:
            return False, f"Таймаут / сетевая ошибка: {e}"
        except Exception as e:
            return False, f"Ошибка: {e}"

    def _acquire_qconn(self, info: StandInfo):
        """
        Проверяет доступность su qconn без пароля (через sudoers NOPASSWD).
        Выполняет тестовую команду от имени qconn.
        """
        try:
            cmd = "sudo -u qconn id"
            _, stdout, stderr = info.ssh_client.exec_command(cmd, timeout=8)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()

            if "qconn" in out:
                return True, "OK"
            if "password" in err.lower() or "sudo" in err.lower():
                return False, (
                    "sudo требует пароль. "
                    "Добавьте: pkrv ALL=(qconn) NOPASSWD: ALL в /etc/sudoers"
                )
            return False, err or "неизвестная ошибка"
        except Exception as e:
            return False, str(e)

    def disconnect(self, name):
        if name in self.stands:
            info = self.stands[name]
            if info.ssh_client:
                try:
                    info.ssh_client.close()
                except Exception:
                    pass
                info.ssh_client = None
            info.connected    = False
            info.qconn_active = False

    # ----------------------------------------------------------
    # Выполнение команд
    # ----------------------------------------------------------

    def execute(self, name, command, timeout=30, as_qconn=False):
        """
        Выполнить команду.
        Если as_qconn=True и плата требует qconn — команда оборачивается
        в sudo -u qconn bash -c '...'.
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"

        info = self.stands[name]

        if as_qconn and info.needs_qconn and info.qconn_active:
            safe_cmd = command.replace("'", "'\\''")
            command  = f"sudo -u qconn bash -c '{safe_cmd}'"

        try:
            _, stdout, stderr = info.ssh_client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return True, out, err
        except Exception as e:
            info.connected  = False
            info.ssh_client = None
            return False, "", str(e)

    # ----------------------------------------------------------
    # Листинг папки
    # ----------------------------------------------------------

    def list_directory(self, name, path):
        """
        Список файлов в папке.
        Для ГОЗ/С1М/Арктика выполняется от qconn (если активен).
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info       = self.stands[name]
        as_qconn   = info.needs_qconn and info.qconn_active
        cmd        = f"ls -la --time-style=+ '{path}' 2>&1"
        ok, out, _ = self.execute(name, cmd, as_qconn=as_qconn)

        if not ok:
            return False, [], "Команда не выполнена"
        if "No such file" in out or "Permission denied" in out:
            return False, [], out.strip()

        return self._parse_ls(out, path)

    def read_file(self, name, path, max_bytes=65536):
        """Читает содержимое файла (первые max_bytes байт)."""
        if name not in self.stands or not self.stands[name].connected:
            return False, "Нет подключения"

        info     = self.stands[name]
        as_qconn = info.needs_qconn and info.qconn_active
        # head -c ограничивает размер
        cmd = f"head -c {max_bytes} '{path}' 2>&1"
        ok, out, _ = self.execute(name, cmd, timeout=15, as_qconn=as_qconn)
        if not ok:
            return False, out
        return True, out

    @staticmethod
    def _parse_ls(output: str, base_path: str):
        entries = []
        for line in output.strip().splitlines():
            if not line or line.startswith("total"):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            perms  = parts[0]
            size   = int(parts[4]) if parts[4].isdigit() else 0
            fname  = " ".join(parts[5:])
            is_dir = perms.startswith("d")
            if fname in (".", ".."):
                continue
            entries.append({
                "name"  : fname,
                "is_dir": is_dir,
                "size"  : size,
                "perms" : perms,
                "path"  : base_path.rstrip("/") + "/" + fname,
            })
        return True, entries, ""

    # ----------------------------------------------------------
    # Деплой
    # ----------------------------------------------------------

    def deploy_files(self, name, mode="copy", local_dir=None):
        if name not in self.stands:
            return False, f"Стенд {name} не найден"
        if not self.stands[name].connected:
            return False, "Нет подключения"

        info      = self.stands[name]
        local_dir = local_dir or os.getcwd()
        mpo_path  = os.path.join(local_dir, "mpo")
        results   = [f"=== Деплой на {name} ===", ""]

        if not os.path.exists(mpo_path):
            return False, "Файл mpo не найден в " + local_dir

        remote_path = info.cvs_path + "/mpo"
        try:
            sftp = info.ssh_client.open_sftp()
            sftp.put(mpo_path, remote_path)
            sftp.close()
            results.append(f" + скопирован -> {remote_path}")
        except Exception as e:
            results.append(f" ОШИБКА SFTP: {e}")
            return False, "\n".join(results)

        if mode == "move":
            try:
                os.remove(mpo_path)
                results.append(" + локальный файл удалён (mode=move)")
            except Exception as e:
                results.append(f" ! не удалось удалить: {e}")

        ok, _, _ = self.execute(name, f"chmod +x '{remote_path}' && sync")
        results.append(" + chmod OK" if ok else " ! ошибка chmod")
        results.append("=== ДЕПЛОЙ ЗАВЕРШЁН ===")
        return True, "\n".join(results)

    # ----------------------------------------------------------
    # Диагностика
    # ----------------------------------------------------------

    def diagnose_connection(self, name) -> str:
        if name not in self.stands:
            return f"Стенд {name} не найден"

        info = self.stands[name]
        lines = [
            f"=== Диагностика {name} ({info.ip}:{info.port}) ===",
            f"Время    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Paramiko : {'установлен' if HAS_PARAMIKO else 'НЕ УСТАНОВЛЕН'}",
            f"qconn    : {'нужен' if info.needs_qconn else 'не нужен'} | "
            f"{'активен' if info.qconn_active else 'не активен'}",
            "",
        ]

        lines.append("--- Сеть ---")
        try:
            flag = "-n 1 -w 2000" if sys.platform == "win32" else "-c 1 -W 2"
            r = subprocess.run(f"ping {flag} {info.ip}",
                               shell=True, capture_output=True, timeout=5)
            lines.append(f" Ping : {'OK' if r.returncode == 0 else 'FAIL'}")
        except Exception:
            lines.append(" Ping : TIMEOUT")

        try:
            s = socket.socket()
            s.settimeout(2)
            res = s.connect_ex((info.ip, info.port))
            s.close()
            lines.append(f" Port {info.port}: {'OPEN' if res == 0 else 'CLOSED'}")
        except Exception:
            lines.append(f" Port {info.port}: ERROR")

        lines.append("")
        lines.append("--- SSH ---")
        if HAS_PARAMIKO and info.connected:
            lines.append(" SSH : активно (уже подключён)")
        elif HAS_PARAMIKO:
            try:
                ssh = paramiko.SSHClient()
                known = os.path.expanduser("~/.ssh/known_hosts")
                if os.path.exists(known):
                    ssh.load_host_keys(known)
                ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
                ssh.connect(hostname=info.ip, port=info.port,
                            username=info.username, password=info.password,
                            timeout=5, allow_agent=False, look_for_keys=False)
                ssh.close()
                lines.append(" SSH : OK")
            except AuthenticationException:
                lines.append(" SSH : ОШИБКА АВТОРИЗАЦИИ")
            except Exception as e:
                lines.append(f" SSH : ОШИБКА — {str(e)[:120]}")
        else:
            lines.append(" paramiko не установлен — тест пропущен")

        lines += ["", "=== КОНЕЦ ДИАГНОСТИКИ ==="]
        return "\n".join(lines)

    def get_all_info(self) -> dict:
        return {
            name: {
                "name"        : s.name,
                "ip"          : s.ip,
                "username"    : s.username,
                "status"      : s.status,
                "connected"   : s.connected,
                "type"        : s.stand_type,
                "port"        : s.port,
                "qconn_active": s.qconn_active,
            }
            for name, s in self.stands.items()
        }


# ============================================================
# GUI
# ============================================================

# --- Тёмная industrial-тема (QSS) ---
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #12151a;
    color: #c8d0dc;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 13px;
}

/* Боковая панель */
#sidebar {
    background-color: #0d1117;
    border-right: 1px solid #1e2530;
}

/* Заголовки секций */
#section_label {
    color: #4a90c4;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 4px 0px 2px 0px;
}

/* ComboBox */
QComboBox {
    background-color: #1a1f2a;
    border: 1px solid #2a3344;
    border-radius: 5px;
    padding: 6px 10px;
    color: #c8d0dc;
    min-height: 28px;
}
QComboBox:hover {
    border-color: #4a90c4;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #1a1f2a;
    border: 1px solid #2a3344;
    selection-background-color: #243248;
    color: #c8d0dc;
}

/* Кнопки */
QPushButton {
    background-color: #1e2738;
    border: 1px solid #2a3a54;
    border-radius: 5px;
    color: #a8b8cc;
    padding: 7px 12px;
    min-height: 28px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #243248;
    border-color: #4a90c4;
    color: #e0eaf8;
}
QPushButton:pressed {
    background-color: #1a2840;
}
QPushButton:disabled {
    background-color: #151a22;
    color: #3a4455;
    border-color: #1e2530;
}

/* Кнопка «Подключиться» — акцент */
#btn_connect {
    background-color: #1a3a5c;
    border-color: #2a6090;
    color: #70b8f0;
}
#btn_connect:hover {
    background-color: #1e4a72;
    border-color: #4a90c4;
    color: #a0d0ff;
}
#btn_connect:disabled {
    background-color: #0e2030;
    color: #1a4060;
    border-color: #102030;
}

/* Кнопка «Отключиться» */
#btn_disconnect {
    background-color: #3a1a1a;
    border-color: #602020;
    color: #c06060;
}
#btn_disconnect:hover {
    background-color: #4a2020;
    border-color: #904040;
    color: #ff8080;
}

/* TreeWidget */
QTreeWidget {
    background-color: #0f1319;
    border: 1px solid #1e2530;
    alternate-background-color: #121620;
    color: #b8c4d4;
    border-radius: 4px;
}
QTreeWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #181e28;
}
QTreeWidget::item:hover {
    background-color: #1a2234;
}
QTreeWidget::item:selected {
    background-color: #1e3050;
    color: #d0e8ff;
}
QHeaderView::section {
    background-color: #141820;
    color: #5a7a9a;
    border: none;
    border-bottom: 1px solid #1e2530;
    padding: 5px 8px;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    text-transform: uppercase;
}

/* Лог */
QTextEdit {
    background-color: #0a0d12;
    border: 1px solid #1e2530;
    border-radius: 4px;
    color: #6a9060;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

/* Разделитель */
QSplitter::handle {
    background-color: #1e2530;
    width: 2px;
    height: 2px;
}

/* Статус-бар */
QStatusBar {
    background-color: #0a0d12;
    color: #3a5070;
    border-top: 1px solid #1e2530;
    font-size: 11px;
}

/* ScrollBar */
QScrollBar:vertical {
    background-color: #0d1117;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: #2a3a54;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #3a5070;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QScrollBar:horizontal {
    background-color: #0d1117;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background-color: #2a3a54;
    border-radius: 4px;
    min-width: 30px;
}

/* Панель пути */
#path_bar {
    background-color: #0d1117;
    border: 1px solid #1e2530;
    border-radius: 4px;
    color: #4a90c4;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px 8px;
}

/* Просмотр файла */
#file_viewer {
    background-color: #070a0f;
    border: 1px solid #1e2530;
    border-radius: 4px;
    color: #80b060;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    padding: 6px;
}

/* Разделительная линия */
#hline {
    background-color: #1e2530;
    max-height: 1px;
    min-height: 1px;
    border: none;
}

/* Индикатор статуса */
#status_dot {
    font-size: 12px;
    font-weight: bold;
    padding: 4px 0px;
}

/* Тип платы */
#board_type_label {
    color: #3a5a7a;
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 2px 0px;
}
"""


def _build_gui(bc: BenchConnector):

    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QTextEdit, QTreeWidget, QTreeWidgetItem,
        QSplitter, QComboBox, QStatusBar, QMessageBox, QFrame, QListWidget,
        QListWidgetItem, QTabWidget, QAbstractItemView,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor

    def load_icon(path: str) -> QIcon:
        if path and os.path.exists(path):
            return QIcon(path)
        return QIcon()

    # ----------------------------------------------------------
    # Workers
    # ----------------------------------------------------------

    class ConnectWorker(QThread):
        finished = pyqtSignal(bool, str, str)
        log      = pyqtSignal(str)

        def __init__(self, connector, stand_name):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name

        def run(self):
            self.log.emit(f"Подключаемся к {self.stand_name}...")
            ok, msg = self.connector.connect(self.stand_name)
            self.finished.emit(ok, msg, self.stand_name)

    class ListDirWorker(QThread):
        finished = pyqtSignal(bool, list, str, str)  # ok, entries, err, path
        log      = pyqtSignal(str)

        def __init__(self, connector, stand_name, path):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name
            self.path       = path

        def run(self):
            ok, entries, err = self.connector.list_directory(
                self.stand_name, self.path)
            self.finished.emit(ok, entries, err, self.path)

    class ReadFileWorker(QThread):
        finished = pyqtSignal(bool, str, str)  # ok, content, path

        def __init__(self, connector, stand_name, path):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name
            self.path       = path

        def run(self):
            ok, content = self.connector.read_file(self.stand_name, self.path)
            self.finished.emit(ok, content, self.path)

    # ----------------------------------------------------------
    # Главное окно
    # ----------------------------------------------------------

    class MainWindow(QMainWindow):

        def __init__(self, connector):
            super().__init__()
            self.bc            = connector
            self.current_stand = None
            self.current_path  = None
            self._workers      = []

            self.setWindowTitle("BENCH MANAGER  v4.0")
            self.setMinimumSize(1100, 680)
            self.resize(1280, 760)

            app_icon = _icon_path(DEFAULT_ICON)
            if app_icon:
                self.setWindowIcon(QIcon(app_icon))

            self._build_ui()
            self._start_status_timer()

        # ---- UI ----

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QHBoxLayout(central)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            # ===================== SIDEBAR =====================
            sidebar = QWidget()
            sidebar.setObjectName("sidebar")
            sidebar.setFixedWidth(220)
            sv = QVBoxLayout(sidebar)
            sv.setContentsMargins(12, 14, 12, 10)
            sv.setSpacing(8)

            # Лого
            logo_path = _icon_path(DEFAULT_ICON)
            if logo_path:
                logo_lbl = QLabel()
                logo_lbl.setPixmap(
                    QPixmap(logo_path).scaled(
                        160, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                logo_lbl.setAlignment(Qt.AlignCenter)
                sv.addWidget(logo_lbl)

            # Иконка текущей платы
            self.board_icon_lbl = QLabel()
            self.board_icon_lbl.setAlignment(Qt.AlignCenter)
            self.board_icon_lbl.setFixedHeight(80)
            sv.addWidget(self.board_icon_lbl)

            self.board_type_lbl = QLabel()
            self.board_type_lbl.setObjectName("board_type_label")
            self.board_type_lbl.setAlignment(Qt.AlignCenter)
            sv.addWidget(self.board_type_lbl)

            self._sep(sv)

            lbl_stands = QLabel("СТЕНД")
            lbl_stands.setObjectName("section_label")
            sv.addWidget(lbl_stands)

            self.stand_combo = QComboBox()
            self.stand_combo.setIconSize(QSize(20, 20))
            for name, info in self.bc.stands.items():
                icon = load_icon(_board_icon_path(info.stand_type))
                self.stand_combo.addItem(icon, name)
            self.stand_combo.currentIndexChanged.connect(self._on_stand_changed)
            sv.addWidget(self.stand_combo)
            self._update_board_icon()

            self._sep(sv)

            lbl_conn = QLabel("ПОДКЛЮЧЕНИЕ")
            lbl_conn.setObjectName("section_label")
            sv.addWidget(lbl_conn)

            self.btn_connect = QPushButton("⏎  Подключиться")
            self.btn_connect.setObjectName("btn_connect")
            self.btn_connect.clicked.connect(self._on_connect)
            sv.addWidget(self.btn_connect)

            self.btn_disconnect = QPushButton("✕  Отключиться")
            self.btn_disconnect.setObjectName("btn_disconnect")
            self.btn_disconnect.setEnabled(False)
            self.btn_disconnect.clicked.connect(self._on_disconnect)
            sv.addWidget(self.btn_disconnect)

            self._sep(sv)

            lbl_tools = QLabel("ИНСТРУМЕНТЫ")
            lbl_tools.setObjectName("section_label")
            sv.addWidget(lbl_tools)

            self.btn_diagnose = QPushButton("⚙  Диагностика")
            self.btn_diagnose.clicked.connect(self._on_diagnose)
            sv.addWidget(self.btn_diagnose)

            sv.addStretch()
            self._sep(sv)

            # Статус
            self.status_dot = QLabel("●  offline")
            self.status_dot.setObjectName("status_dot")
            self.status_dot.setStyleSheet("color: #334455;")
            self.status_dot.setAlignment(Qt.AlignCenter)
            sv.addWidget(self.status_dot)

            self.qconn_lbl = QLabel("")
            self.qconn_lbl.setAlignment(Qt.AlignCenter)
            self.qconn_lbl.setStyleSheet("color: #3a5a3a; font-size: 10px;")
            sv.addWidget(self.qconn_lbl)

            root.addWidget(sidebar)

            # ===================== RIGHT PANEL =====================
            right_widget = QWidget()
            rv = QVBoxLayout(right_widget)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(0)

            # Верхняя панель — путь + быстрые папки
            top_bar = QWidget()
            top_bar.setStyleSheet("background-color: #0d1117; border-bottom: 1px solid #1e2530;")
            top_bar.setFixedHeight(46)
            tbh = QHBoxLayout(top_bar)
            tbh.setContentsMargins(10, 6, 10, 6)
            tbh.setSpacing(8)

            tbh.addWidget(QLabel("📁"))
            self.path_label = QLabel("/")
            self.path_label.setObjectName("path_bar")
            self.path_label.setMinimumWidth(200)
            tbh.addWidget(self.path_label, 1)

            self.btn_up = QPushButton("↑  Вверх")
            self.btn_up.setFixedWidth(90)
            self.btn_up.setEnabled(False)
            self.btn_up.clicked.connect(self._on_go_up)
            tbh.addWidget(self.btn_up)

            tbh.addWidget(QLabel("Перейти:"))
            self.folder_combo = QComboBox()
            self.folder_combo.setFixedWidth(200)
            self.folder_combo.activated.connect(self._on_quick_folder)
            tbh.addWidget(self.folder_combo)

            rv.addWidget(top_bar)

            # Основной сплиттер — дерево файлов | просмотр файла
            main_splitter = QSplitter(Qt.Horizontal)

            # Дерево файлов
            self.file_tree = QTreeWidget()
            self.file_tree.setHeaderLabels(["Имя", "Тип", "Размер", "Права"])
            self.file_tree.setColumnWidth(0, 320)
            self.file_tree.setColumnWidth(1,  60)
            self.file_tree.setColumnWidth(2,  90)
            self.file_tree.setColumnWidth(3, 110)
            self.file_tree.setAlternatingRowColors(True)
            self.file_tree.setSortingEnabled(True)
            self.file_tree.itemDoubleClicked.connect(self._on_tree_double_click)
            self.file_tree.itemClicked.connect(self._on_tree_click)
            main_splitter.addWidget(self.file_tree)

            # Правая часть — вкладки: просмотр файла / лог
            right_tabs = QTabWidget()
            right_tabs.setStyleSheet("""
                QTabWidget::pane { border: none; background: #0a0d12; }
                QTabBar::tab { background: #0d1117; color: #3a5070; padding: 6px 16px;
                               border: 1px solid #1e2530; border-bottom: none;
                               font-size: 11px; letter-spacing: 1px; }
                QTabBar::tab:selected { background: #0a0d12; color: #4a90c4;
                                        border-bottom: 1px solid #0a0d12; }
                QTabBar::tab:hover { color: #7ab0e0; }
            """)

            self.file_viewer = QTextEdit()
            self.file_viewer.setObjectName("file_viewer")
            self.file_viewer.setReadOnly(True)
            self.file_viewer.setPlaceholderText(
                "Кликните по файлу для просмотра содержимого...")
            right_tabs.addTab(self.file_viewer, "ФАЙЛ")

            self.log_box = QTextEdit()
            self.log_box.setReadOnly(True)
            self.log_box.setFont(QFont("Consolas", 10))
            self.log_box.setStyleSheet(
                "background-color: #070a0f; color: #6a9060; "
                "border: none; padding: 6px;")
            right_tabs.addTab(self.log_box, "ЛОГ")

            self.right_tabs = right_tabs
            main_splitter.addWidget(right_tabs)
            main_splitter.setSizes([560, 420])

            # Нижний сплиттер — файловое дерево + файловый просмотр | лог
            content_splitter = QSplitter(Qt.Vertical)
            content_splitter.addWidget(main_splitter)
            content_splitter.setSizes([600])

            rv.addWidget(content_splitter, 1)

            root.addWidget(right_widget, 1)

            self.setStatusBar(QStatusBar())
            self.setStyleSheet(DARK_STYLE)

        # ---- Вспомогательные ----

        def _sep(self, layout):
            line = QFrame()
            line.setObjectName("hline")
            line.setFrameShape(QFrame.HLine)
            layout.addWidget(line)

        def _update_board_icon(self):
            name = self.stand_combo.currentText()
            if not name or name not in self.bc.stands:
                self.board_icon_lbl.clear()
                self.board_type_lbl.clear()
                return
            info      = self.bc.stands[name]
            icon_path = _board_icon_path(info.stand_type)
            if icon_path:
                self.board_icon_lbl.setPixmap(
                    QPixmap(icon_path).scaled(
                        180, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.board_icon_lbl.clear()
            self.board_type_lbl.setText(info.stand_type.upper() or "UNKNOWN")

        def _update_folder_combo(self):
            name = self.stand_combo.currentText()
            self.folder_combo.clear()
            if not name or name not in self.bc.stands:
                return
            for folder in self.bc.stands[name].browse_folders:
                self.folder_combo.addItem(folder)

        def _on_stand_changed(self, _):
            self._update_board_icon()
            self._update_folder_combo()

        # ---- Таймер статуса ----

        def _start_status_timer(self):
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh_status)
            self._timer.start(3000)

        def _refresh_status(self):
            name = self.stand_combo.currentText()
            if not name or name not in self.bc.stands:
                return
            info = self.bc.stands[name]
            if info.connected:
                self.status_dot.setText("●  connected")
                self.status_dot.setStyleSheet("color: #40c060; font-size: 12px; font-weight: bold;")
                qconn_txt = "[qconn]" if info.qconn_active else ""
                self.qconn_lbl.setText(qconn_txt)
                self.qconn_lbl.setStyleSheet(
                    "color: #409040; font-size: 10px;" if info.qconn_active
                    else "color: #3a5a3a; font-size: 10px;")
            elif info.status == "online":
                self.status_dot.setText("●  online")
                self.status_dot.setStyleSheet("color: #3090a0; font-size: 12px; font-weight: bold;")
                self.qconn_lbl.setText("")
            else:
                self.status_dot.setText("●  offline")
                self.status_dot.setStyleSheet("color: #334455; font-size: 12px; font-weight: bold;")
                self.qconn_lbl.setText("")

        # ---- Подключение ----

        def _on_connect(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("⏳  Подключение...")
            self._log(f"▶ Подключаемся к {name}...")

            worker = ConnectWorker(self.bc, name)
            worker.log.connect(self._log)
            worker.finished.connect(self._on_connect_done)
            self._workers.append(worker)
            worker.start()

        def _on_connect_done(self, ok, msg, stand_name):
            self.btn_connect.setText("⏎  Подключиться")
            if ok:
                self.btn_connect.setEnabled(False)
                self.btn_disconnect.setEnabled(True)
                self.btn_up.setEnabled(True)
                self._log(f"✓ {msg}")
                self.statusBar().showMessage(msg)
                self.current_stand = stand_name
                info = self.bc.stands[stand_name]
                self.current_path  = info.browse_folders[0]
                self._update_folder_combo()
                self._load_directory(stand_name, self.current_path)
            else:
                self.btn_connect.setEnabled(True)
                self._log(f"✗ {msg}")
                QMessageBox.warning(self, "Ошибка подключения", msg)

        def _on_disconnect(self):
            name = self.stand_combo.currentText()
            self.bc.disconnect(name)
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self.btn_up.setEnabled(False)
            self.file_tree.clear()
            self.file_viewer.clear()
            self.path_label.setText("/")
            self.current_path = None
            self._log(f"✕ Отключено от {name}")

        # ---- Навигация по папкам ----

        def _on_quick_folder(self, index):
            path = self.folder_combo.itemText(index)
            if path and self.current_stand:
                self.current_path = path
                self._load_directory(self.current_stand, path)

        def _on_go_up(self):
            if not self.current_path or not self.current_stand:
                return
            parent = os.path.dirname(self.current_path.rstrip("/")) or "/"
            self.current_path = parent
            self._load_directory(self.current_stand, parent)

        def _load_directory(self, stand_name, path):
            self.file_tree.clear()
            self.file_viewer.clear()
            self.path_label.setText(path)
            self._log(f"  cd {path}")
            self.statusBar().showMessage(f"Загрузка {path}...")

            worker = ListDirWorker(self.bc, stand_name, path)
            worker.finished.connect(self._on_dir_loaded)
            self._workers.append(worker)
            worker.start()

        def _on_dir_loaded(self, ok, entries, err, path):
            self.file_tree.clear()
            if not ok:
                self._log(f"  ✗ {err}")
                self.statusBar().showMessage(f"Ошибка: {err}")
                return
            if not entries:
                self._log("  (пусто или нет прав)")
                self.statusBar().showMessage(f"{path} — пусто")
                return

            dirs  = sorted([e for e in entries if     e["is_dir"]], key=lambda x: x["name"].lower())
            files = sorted([e for e in entries if not e["is_dir"]], key=lambda x: x["name"].lower())

            for e in dirs + files:
                is_dir = e["is_dir"]
                icon   = "📁" if is_dir else "📄"
                size   = self._fmt_size(e["size"]) if not is_dir else ""
                item   = QTreeWidgetItem([
                    f"{icon}  {e['name']}",
                    "папка" if is_dir else "файл",
                    size,
                    e["perms"],
                ])
                item.setData(0, Qt.UserRole, e)
                if is_dir:
                    item.setForeground(0, QColor("#4a90c4"))
                self.file_tree.addTopLevelItem(item)

            self._log(f"  {len(dirs)} папок, {len(files)} файлов")
            self.statusBar().showMessage(
                f"{path}  •  {len(dirs)} папок, {len(files)} файлов")

        def _on_tree_double_click(self, item, _):
            entry = item.data(0, Qt.UserRole)
            if entry and entry["is_dir"] and self.current_stand:
                self.current_path = entry["path"]
                self._load_directory(self.current_stand, entry["path"])

        def _on_tree_click(self, item, _):
            """Одиночный клик по файлу — читаем содержимое."""
            entry = item.data(0, Qt.UserRole)
            if entry and not entry["is_dir"] and self.current_stand:
                self._read_file(self.current_stand, entry["path"])

        def _read_file(self, stand_name, path):
            self.file_viewer.setPlaceholderText("")
            self.file_viewer.setText(f"⏳ Загрузка {path}...")
            self.right_tabs.setCurrentIndex(0)

            worker = ReadFileWorker(self.bc, stand_name, path)
            worker.finished.connect(self._on_file_read)
            self._workers.append(worker)
            worker.start()

        def _on_file_read(self, ok, content, path):
            if ok:
                header = f"══ {path} ══\n\n"
                self.file_viewer.setText(header + content)
                self._log(f"  ✓ файл прочитан: {path}")
            else:
                self.file_viewer.setText(f"✗ Ошибка чтения:\n{content}")
                self._log(f"  ✗ ошибка чтения {path}")

        # ---- Диагностика ----

        def _on_diagnose(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self._log(f"--- Диагностика {name} ---")
            result = self.bc.diagnose_connection(name)
            self._log(result)
            self.right_tabs.setCurrentIndex(1)

        # ---- Утилиты ----

        @staticmethod
        def _fmt_size(n: int) -> str:
            if n < 1024:
                return f"{n} B"
            elif n < 1024 * 1024:
                return f"{n/1024:.1f} KB"
            elif n < 1024 ** 3:
                return f"{n/1024/1024:.1f} MB"
            return f"{n/1024/1024/1024:.2f} GB"

        def _log(self, text: str):
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.append(f'<span style="color:#2a4a3a">[{ts}]</span> {text}')

        def closeEvent(self, event):
            self.bc.stop_monitoring()
            event.accept()

    # ----------------------------------------------------------
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    app_icon = _icon_path(DEFAULT_ICON)
    if app_icon:
        app.setWindowIcon(QIcon(app_icon))

    window = MainWindow(bc)
    window.show()
    sys.exit(app.exec_())


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Bench Manager")
    parser.add_argument("--console",  "-c", action="store_true")
    parser.add_argument("--check",          action="store_true")
    parser.add_argument("--version",  "-v", action="store_true")
    parser.add_argument("--info",           action="store_true")
    parser.add_argument("--stand",    "-s", type=str)
    parser.add_argument("--diagnose",       type=str)
    args = parser.parse_args()

    if args.version:
        print("Bench Manager v4.0")
        return

    if args.info:
        print(f"paramiko : {'установлен' if HAS_PARAMIKO else 'НЕ УСТАНОВЛЕН'}")
        print(f"pyyaml   : {'установлен' if HAS_YAML    else 'НЕ УСТАНОВЛЕН'}")
        return

    config = load_config()
    bc     = BenchConnector(config)
    bc.start_monitoring()

    if args.diagnose:
        time.sleep(1)
        print(bc.diagnose_connection(args.diagnose))
        bc.stop_monitoring()
        return

    if args.stand:
        time.sleep(1)
        ok, msg = bc.connect(args.stand)
        print(f"{'УСПЕШНО' if ok else 'ОШИБКА'}: {msg}")
        bc.stop_monitoring()
        return

    if args.check:
        time.sleep(2)
        print(f"\n{'Стенд':<14} {'IP':>18}  {'Статус':<8}  qconn")
        print("-" * 52)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info["status"] == "online" else "offline"
            q = "active" if info.get("qconn_active") else "-"
            print(f" {name:<13} {info['ip']:>16}:{info['port']:<5}  {s:<8}  {q}")
        bc.stop_monitoring()
        return

    if args.console:
        time.sleep(1)
        for name in bc.stands:
            ok, msg = bc.connect(name)
            print(f"{'OK' if ok else 'ERR'} {name}: {msg}")
        bc.stop_monitoring()
        return

    try:
        _build_gui(bc)
    except ImportError as e:
        print(f"PyQt5 не найден: {e}")
        print("Установите: pip install PyQt5")
        sys.exit(1)


if __name__ == "__main__":
    main()
