#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bench Manager v4.0 - Simple Fixed Version
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
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
ENV_PATH = os.path.join(APP_DIR, ".env")

# ============================================================
# ИКОНКИ
# ============================================================
BOARD_ICON_MAP = {
    "arktika": "arktika.png",
    "c1m": "c1m.png",
    "goz": "goz.png",
    "orangepi": "orangepi.png",
}
DEFAULT_ICON = "logo.png"

BOARD_FOLDERS = {
    "goz": ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "c1m": ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "arktika": ["/home/pkrv/CVS", "/tmp", "/fead_hd", "/fs/"],
    "orangepi": ["/"],
}

QCONN_TYPES = {"goz", "c1m", "arktika"}


def _icon_path(filename: str) -> str:
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.exists(path) else ""


def _board_icon_path(board_type: str) -> str:
    key = (board_type or "").strip().lower()
    filename = BOARD_ICON_MAP.get(key, DEFAULT_ICON)
    return _icon_path(filename) or _icon_path(DEFAULT_ICON)


def _board_folders(board_type: str) -> list:
    key = (board_type or "").strip().lower()
    return BOARD_FOLDERS.get(key, ["/home/pkrv/CVS", "/tmp"])


# ============================================================
# БИБЛИОТЕКИ
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
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


def load_config() -> dict:
    _load_env_file()
    if not HAS_YAML or not os.path.exists(CONFIG_PATH):
        return {"stands": [], "monitoring": {"check_interval": 5, "ssh_timeout": 10}}

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    for stand in cfg.get("stands", []):
        name_key = stand.get("name", "").upper().replace(" ", "_")
        env_key = f"BENCH_PASSWORD_{name_key}"
        password = os.environ.get(env_key, "") or stand.get("password", "")
        stand["password"] = password

    return cfg


# ============================================================
# МОДЕЛЬ СТЕНДА
# ============================================================
class StandInfo:
    def __init__(self, name, ip, username="pkrv", password="", stand_type="", port=22, folders=None):
        self.name = name
        self.ip = ip
        self.username = username
        self.password = password
        self.status = "offline"
        self.connected = False
        self.stand_type = stand_type
        self.port = port
        self.ssh_client = None
        self.folders = folders or {}
        self.qconn_active = False

    @property
    def needs_qconn(self):
        return self.stand_type.strip().lower() in QCONN_TYPES

    @property
    def browse_folders(self):
        return _board_folders(self.stand_type)

    @property
    def cvs_path(self):
        return self.folders.get("cvs", self.browse_folders[0])


# ============================================================
# КОННЕКТОР
# ============================================================
class BenchConnector:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.stands = {}
        self.monitoring = False
        self._init_stands()

    def _init_stands(self):
        for sc in self.config.get("stands", []):
            name = sc["name"]
            self.stands[name] = StandInfo(
                name=name,
                ip=sc.get("ip", ""),
                username=sc.get("username", "pkrv"),
                password=sc.get("password", ""),
                stand_type=sc.get("board", {}).get("type", ""),
                port=sc.get("port", 22),
                folders=sc.get("folders", {}),
            )

    def check_availability(self, ip, port=22):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex((ip, port)) == 0
            s.close()
            return result
        except:
            return False

    def start_monitoring(self):
        if self.monitoring:
            return
        self.monitoring = True

        def loop():
            interval = self.config.get("monitoring", {}).get("check_interval", 5)
            while self.monitoring:
                for name, info in self.stands.items():
                    if info.connected and info.ssh_client:
                        try:
                            transport = info.ssh_client.get_transport()
                            if transport and transport.is_active():
                                info.status = "online"
                                continue
                        except:
                            pass
                        info.ssh_client = None
                        info.connected = False
                        info.qconn_active = False
                        info.status = "offline"
                        continue
                    info.status = "online" if self.check_availability(info.ip, info.port) else "offline"
                time.sleep(interval)

        threading.Thread(target=loop, daemon=True).start()

    def stop_monitoring(self):
        self.monitoring = False

    def connect(self, name, password=None):
        """Простое подключение с поддержкой старых SSH серверов"""
        if not HAS_PARAMIKO:
            return False, "paramiko не установлен"

        if name not in self.stands:
            return False, f"Стенд '{name}' не найден"

        info = self.stands[name]
        pwd = password or info.password

        if not pwd:
            return False, f"Нет пароля для '{name}'"

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            timeout = self.config.get("monitoring", {}).get("ssh_timeout", 10)

            # Пробуем стандартное подключение
            try:
                ssh.connect(
                    hostname=info.ip,
                    port=info.port,
                    username=info.username,
                    password=pwd,
                    timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                    compress=True,
                )
            except SSHException as e:
                if "no acceptable host key" in str(e).lower():
                    # Пробуем с отключенными алгоритмами
                    ssh.connect(
                        hostname=info.ip,
                        port=info.port,
                        username=info.username,
                        password=pwd,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False,
                        compress=True,
                        disabled_algorithms={'pubkeys': []},
                    )
                else:
                    raise e

            # Проверка соединения
            _, stdout, _ = ssh.exec_command("echo OK", timeout=5)
            if stdout.read().decode().strip() != "OK":
                ssh.close()
                return False, "Не удалось выполнить тестовую команду"

            info.ssh_client = ssh
            info.connected = True
            info.status = "online"
            info.qconn_active = False

            # Проверяем qconn
            if info.needs_qconn:
                ok_q, msg_q = self._acquire_qconn(info)
                if ok_q:
                    info.qconn_active = True
                    return True, f"Подключено к {name} ({info.ip}) [qconn]"
                return True, f"Подключено к {name} ({info.ip}) [qconn: {msg_q}]"

            return True, f"Подключено к {name} ({info.ip})"

        except AuthenticationException:
            return False, f"Ошибка авторизации для {info.username}"
        except Exception as e:
            return False, f"Ошибка подключения: {e}"

    def _acquire_qconn(self, info):
        try:
            _, stdout, stderr = info.ssh_client.exec_command("sudo -n -u qconn whoami 2>&1", timeout=8)
            out = stdout.read().decode("utf-8", errors="replace").strip()

            if "qconn" in out:
                return True, "OK"

            err = stderr.read().decode("utf-8", errors="replace").strip()
            if "password" in err.lower():
                return False, "sudo требует пароль (добавьте NOPASSWD в /etc/sudoers)"
            return False, err or "неизвестная ошибка"
        except Exception as e:
            return False, str(e)

    def disconnect(self, name):
        if name in self.stands:
            info = self.stands[name]
            if info.ssh_client:
                try:
                    info.ssh_client.close()
                except:
                    pass
                info.ssh_client = None
            info.connected = False
            info.qconn_active = False

    def execute(self, name, command, timeout=30, as_qconn=False):
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"

        info = self.stands[name]

        if as_qconn and info.needs_qconn and info.qconn_active:
            command = f"sudo -u qconn bash -c '{command}'"

        try:
            _, stdout, stderr = info.ssh_client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return True, out, err
        except Exception as e:
            return False, "", str(e)

    def list_directory(self, name, path):
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info = self.stands[name]
        as_qconn = info.needs_qconn and info.qconn_active
        cmd = f"ls -la '{path}' 2>&1"
        ok, out, _ = self.execute(name, cmd, as_qconn=as_qconn)

        if not ok:
            return False, [], "Команда не выполнена"
        if "No such file" in out or "Permission denied" in out or "cannot access" in out:
            return False, [], out.strip()

        return self._parse_ls(out, path)

    def read_file(self, name, path, max_bytes=65536):
        if name not in self.stands or not self.stands[name].connected:
            return False, "Нет подключения"

        info = self.stands[name]
        as_qconn = info.needs_qconn and info.qconn_active
        cmd = f"head -c {max_bytes} '{path}' 2>&1"
        ok, out, _ = self.execute(name, cmd, timeout=15, as_qconn=as_qconn)
        return (True, out) if ok else (False, out)

    @staticmethod
    def _parse_ls(output, base_path):
        entries = []
        for line in output.strip().splitlines():
            if not line or line.startswith("total") or "cannot access" in line.lower():
                continue
            parts = line.split()
            if len(parts) < 6:
                continue

            perms = parts[0]
            try:
                size = int(parts[4]) if parts[4].isdigit() else 0
            except:
                size = 0

            fname = " ".join(parts[5:])
            if " -> " in fname:
                fname = fname.split(" -> ")[0].strip()

            is_dir = perms.startswith("d")
            if fname in (".", ".."):
                continue

            entries.append({
                "name": fname,
                "is_dir": is_dir,
                "size": size,
                "perms": perms,
                "path": base_path.rstrip("/") + "/" + fname,
            })
        return True, entries, ""

    def deploy_files(self, name, mode="copy", local_dir=None):
        if name not in self.stands or not self.stands[name].connected:
            return False, "Нет подключения"

        info = self.stands[name]
        local_dir = local_dir or os.getcwd()
        mpo_path = os.path.join(local_dir, "mpo")
        results = [f"=== Деплой на {name} ===", ""]

        if not os.path.exists(mpo_path):
            return False, "Файл mpo не найден"

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
                results.append(" + локальный файл удалён")
            except Exception as e:
                results.append(f" ! не удалось удалить: {e}")

        ok, _, _ = self.execute(name, f"chmod +x '{remote_path}' && sync")
        results.append(" + chmod OK" if ok else " ! ошибка chmod")
        results.append("=== ДЕПЛОЙ ЗАВЕРШЁН ===")
        return True, "\n".join(results)

    def diagnose_connection(self, name):
        if name not in self.stands:
            return f"Стенд {name} не найден"

        info = self.stands[name]
        lines = [
            f"=== Диагностика {name} ({info.ip}:{info.port}) ===",
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Paramiko: {'установлен' if HAS_PARAMIKO else 'НЕ УСТАНОВЛЕН'}",
            "",
        ]

        # Проверка сети
        lines.append("--- Сеть ---")
        try:
            param = "-n 1 -w 2000" if sys.platform == "win32" else "-c 1 -W 2"
            r = subprocess.run(f"ping {param} {info.ip}", shell=True, capture_output=True, timeout=5)
            lines.append(f"Ping: {'OK' if r.returncode == 0 else 'FAIL'}")
        except:
            lines.append("Ping: TIMEOUT")

        try:
            s = socket.socket()
            s.settimeout(2)
            res = s.connect_ex((info.ip, info.port))
            s.close()
            lines.append(f"Port {info.port}: {'OPEN' if res == 0 else 'CLOSED'}")
        except:
            lines.append(f"Port {info.port}: ERROR")

        # Проверка SSH
        lines.append("\n--- SSH ---")
        if HAS_PARAMIKO and info.connected:
            lines.append("SSH: подключено")
        elif HAS_PARAMIKO:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Пробуем стандартное подключение
                try:
                    ssh.connect(hostname=info.ip, port=info.port,
                                username=info.username, password=info.password,
                                timeout=5, allow_agent=False, look_for_keys=False)
                    lines.append("SSH (стандартный): OK")
                except:
                    # Пробуем с отключенными алгоритмами
                    try:
                        ssh.connect(hostname=info.ip, port=info.port,
                                    username=info.username, password=info.password,
                                    timeout=5, allow_agent=False, look_for_keys=False,
                                    disabled_algorithms={'pubkeys': []})
                        lines.append("SSH (legacy): OK")
                    except AuthenticationException:
                        lines.append("SSH: ОШИБКА АВТОРИЗАЦИИ")
                    except Exception as e:
                        lines.append(f"SSH: ОШИБКА - {str(e)[:100]}")

                ssh.close()
            except Exception as e:
                lines.append(f"SSH: ОШИБКА - {str(e)[:100]}")
        else:
            lines.append("paramiko не установлен")

        lines += ["", "=== КОНЕЦ ДИАГНОСТИКИ ==="]
        return "\n".join(lines)

    def get_all_info(self):
        return {
            name: {
                "name": s.name,
                "ip": s.ip,
                "username": s.username,
                "status": s.status,
                "connected": s.connected,
                "type": s.stand_type,
                "port": s.port,
                "qconn_active": s.qconn_active,
            }
            for name, s in self.stands.items()
        }


# ============================================================
# GUI
# ============================================================
def _build_gui(bc: BenchConnector):
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QTextEdit, QTreeWidget, QTreeWidgetItem,
        QSplitter, QComboBox, QStatusBar, QMessageBox, QFrame,
        QTabWidget, QSizePolicy, QGraphicsDropShadowEffect,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor, QPalette

    def load_icon(path):
        return QIcon(path) if path and os.path.exists(path) else QIcon()

    # Workers
    class ConnectWorker(QThread):
        finished = pyqtSignal(bool, str, str)
        log = pyqtSignal(str)

        def __init__(self, connector, stand_name):
            super().__init__()
            self.connector = connector
            self.stand_name = stand_name

        def run(self):
            self.log.emit(f"Подключаемся к {self.stand_name}...")
            ok, msg = self.connector.connect(self.stand_name)
            self.finished.emit(ok, msg, self.stand_name)

    class ListDirWorker(QThread):
        finished = pyqtSignal(bool, list, str, str)

        def __init__(self, connector, stand_name, path):
            super().__init__()
            self.connector = connector
            self.stand_name = stand_name
            self.path = path

        def run(self):
            ok, entries, err = self.connector.list_directory(self.stand_name, self.path)
            self.finished.emit(ok, entries, err, self.path)

    class ReadFileWorker(QThread):
        finished = pyqtSignal(bool, str, str)

        def __init__(self, connector, stand_name, path):
            super().__init__()
            self.connector = connector
            self.stand_name = stand_name
            self.path = path

        def run(self):
            ok, content = self.connector.read_file(self.stand_name, self.path)
            self.finished.emit(ok, content, self.path)

    class MainWindow(QMainWindow):
        def __init__(self, connector):
            super().__init__()
            self.bc = connector
            self.current_stand = None
            self.current_path = None
            self._workers = []

            self.setWindowTitle("BENCH MANAGER v4.0")
            self.setMinimumSize(1120, 700)
            self.resize(1340, 800)

            app_icon = _icon_path(DEFAULT_ICON)
            if app_icon:
                self.setWindowIcon(QIcon(app_icon))

            self._build_ui()
            self._start_status_timer()

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QHBoxLayout(central)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            # Sidebar
            sidebar = QWidget()
            sidebar.setObjectName("sidebar")
            sidebar.setFixedWidth(230)
            sv = QVBoxLayout(sidebar)
            sv.setContentsMargins(14, 16, 14, 14)
            sv.setSpacing(6)

            # Logo
            logo_path = _icon_path(DEFAULT_ICON)
            if logo_path:
                logo_lbl = QLabel()
                pm = QPixmap(logo_path).scaled(140, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_lbl.setPixmap(pm)
                logo_lbl.setAlignment(Qt.AlignCenter)
                sv.addWidget(logo_lbl)

            title_lbl = QLabel("BENCH MANAGER")
            title_lbl.setObjectName("app_title")
            title_lbl.setAlignment(Qt.AlignCenter)
            sv.addWidget(title_lbl)

            ver_lbl = QLabel("v4.0  //  SSH CONSOLE")
            ver_lbl.setObjectName("app_version")
            ver_lbl.setAlignment(Qt.AlignCenter)
            sv.addWidget(ver_lbl)

            self._sep(sv)

            # Board icon
            self.board_icon_lbl = QLabel()
            self.board_icon_lbl.setAlignment(Qt.AlignCenter)
            self.board_icon_lbl.setFixedHeight(90)
            sv.addWidget(self.board_icon_lbl)

            self.board_type_lbl = QLabel()
            self.board_type_lbl.setObjectName("board_type_label")
            self.board_type_lbl.setAlignment(Qt.AlignCenter)
            sv.addWidget(self.board_type_lbl)

            self.ip_label = QLabel()
            self.ip_label.setObjectName("ip_label")
            self.ip_label.setAlignment(Qt.AlignCenter)
            sv.addWidget(self.ip_label)

            self._sep(sv)

            # Stand selector
            sv.addWidget(QLabel("СТЕНД", objectName="section_label"))

            self.stand_combo = QComboBox()
            self.stand_combo.setIconSize(QSize(20, 20))
            for name, info in self.bc.stands.items():
                icon = load_icon(_board_icon_path(info.stand_type))
                self.stand_combo.addItem(icon, name)
            self.stand_combo.currentIndexChanged.connect(self._on_stand_changed)
            sv.addWidget(self.stand_combo)
            self._update_board_icon()

            self._sep(sv)

            # Connection buttons
            sv.addWidget(QLabel("ПОДКЛЮЧЕНИЕ", objectName="section_label"))

            self.btn_connect = QPushButton("⏎   Подключиться")
            self.btn_connect.setObjectName("btn_connect")
            self.btn_connect.clicked.connect(self._on_connect)
            sv.addWidget(self.btn_connect)

            self.btn_disconnect = QPushButton("✕   Отключиться")
            self.btn_disconnect.setObjectName("btn_disconnect")
            self.btn_disconnect.setEnabled(False)
            self.btn_disconnect.clicked.connect(self._on_disconnect)
            sv.addWidget(self.btn_disconnect)

            self._sep(sv)

            # Tools
            sv.addWidget(QLabel("ИНСТРУМЕНТЫ", objectName="section_label"))

            self.btn_diagnose = QPushButton("⚙   Диагностика")
            self.btn_diagnose.clicked.connect(self._on_diagnose)
            sv.addWidget(self.btn_diagnose)

            self.btn_refresh = QPushButton("↺   Обновить папку")
            self.btn_refresh.clicked.connect(self._on_refresh)
            sv.addWidget(self.btn_refresh)

            sv.addStretch()

            self._sep(sv)

            # Status
            self.status_dot = QLabel("●   OFFLINE")
            self.status_dot.setObjectName("status_dot")
            self.status_dot.setStyleSheet("color: #253545;")
            self.status_dot.setAlignment(Qt.AlignCenter)
            sv.addWidget(self.status_dot)

            self.qconn_lbl = QLabel("")
            self.qconn_lbl.setAlignment(Qt.AlignCenter)
            self.qconn_lbl.setStyleSheet("color: #2a4a2a; font-size: 10px;")
            sv.addWidget(self.qconn_lbl)

            root.addWidget(sidebar)

            # Right panel
            right_widget = QWidget()
            rv = QVBoxLayout(right_widget)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(0)

            # Top bar
            top_bar = QWidget()
            top_bar.setFixedHeight(50)
            top_bar.setStyleSheet("background-color: #0a0e18; border-bottom: 1px solid #1a2434;")
            tbh = QHBoxLayout(top_bar)
            tbh.setContentsMargins(12, 8, 12, 8)
            tbh.setSpacing(10)

            path_icon = QLabel("📁")
            path_icon.setStyleSheet("font-size: 14px;")
            tbh.addWidget(path_icon)

            self.path_label = QLabel("/")
            self.path_label.setObjectName("path_bar")
            self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            tbh.addWidget(self.path_label, 1)

            self.btn_up = QPushButton("↑  Вверх")
            self.btn_up.setFixedWidth(95)
            self.btn_up.setEnabled(False)
            self.btn_up.clicked.connect(self._on_go_up)
            tbh.addWidget(self.btn_up)

            nav_lbl = QLabel("Быстрый переход:")
            nav_lbl.setStyleSheet("color: #2a4a6a; font-size: 11px;")
            tbh.addWidget(nav_lbl)

            self.folder_combo = QComboBox()
            self.folder_combo.setFixedWidth(210)
            self.folder_combo.activated.connect(self._on_quick_folder)
            tbh.addWidget(self.folder_combo)

            rv.addWidget(top_bar)

            # Main splitter
            main_splitter = QSplitter(Qt.Horizontal)
            main_splitter.setHandleWidth(3)

            # File tree
            tree_container = QWidget()
            tc_layout = QVBoxLayout(tree_container)
            tc_layout.setContentsMargins(8, 8, 4, 8)
            tc_layout.setSpacing(0)

            tree_header = QLabel("ФАЙЛОВАЯ СИСТЕМА")
            tree_header.setStyleSheet(
                "color: #1e4060; font-size: 9px; font-weight: bold; letter-spacing: 3px; padding: 0px 4px 6px 2px;")
            tc_layout.addWidget(tree_header)

            self.file_tree = QTreeWidget()
            self.file_tree.setHeaderLabels(["Имя", "Тип", "Размер", "Права"])
            self.file_tree.setColumnWidth(0, 300)
            self.file_tree.setColumnWidth(1, 62)
            self.file_tree.setColumnWidth(2, 88)
            self.file_tree.setColumnWidth(3, 108)
            self.file_tree.setAlternatingRowColors(True)
            self.file_tree.setSortingEnabled(True)
            self.file_tree.setRootIsDecorated(False)
            self.file_tree.setUniformRowHeights(True)
            self.file_tree.itemDoubleClicked.connect(self._on_tree_double_click)
            self.file_tree.itemClicked.connect(self._on_tree_click)
            tc_layout.addWidget(self.file_tree)

            main_splitter.addWidget(tree_container)

            # Right tabs
            right_tabs = QTabWidget()

            self.file_viewer = QTextEdit()
            self.file_viewer.setObjectName("file_viewer")
            self.file_viewer.setReadOnly(True)
            self.file_viewer.setPlaceholderText("Кликните по файлу для просмотра...")
            right_tabs.addTab(self.file_viewer, "  ФАЙЛ  ")

            self.log_box = QTextEdit()
            self.log_box.setReadOnly(True)
            self.log_box.setFont(QFont("Consolas", 10))
            self.log_box.setStyleSheet("background-color: #060810; color: #5a9060; border: none; padding: 8px;")
            right_tabs.addTab(self.log_box, "  ЛОГ  ")

            self.right_tabs = right_tabs
            main_splitter.addWidget(right_tabs)
            main_splitter.setSizes([580, 440])

            rv.addWidget(main_splitter, 1)
            root.addWidget(right_widget, 1)

            # Status bar
            sb = QStatusBar()
            self.setStatusBar(sb)
            self._status_perm = QLabel("Готов")
            self._status_perm.setStyleSheet("color: #2a4a6a; padding-right:8px;")
            sb.addPermanentWidget(self._status_perm)

            # Apply dark style
            self.setStyleSheet(self._dark_style())

        def _dark_style(self):
            return """
            QMainWindow, QWidget { background-color: #0e1118; color: #b8c8dc; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            #sidebar { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #090c12, stop:1 #0e1118); border-right: 1px solid #1c2535; }
            #section_label { color: #2e6fa3; font-size: 9px; font-weight: bold; letter-spacing: 3px; padding: 6px 0px 3px 2px; }
            QComboBox { background-color: #131926; border: 1px solid #1e2d42; border-radius: 6px; padding: 7px 12px; color: #c0d0e0; min-height: 30px; }
            QComboBox:hover { border-color: #3a7abf; }
            QComboBox QAbstractItemView { background-color: #131926; border: 1px solid #1e2d42; color: #c0d0e0; selection-background-color: #1e3a5c; }
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1c2840, stop:1 #141e30); border: 1px solid #253450; border-radius: 6px; color: #90aac8; padding: 8px 14px; min-height: 30px; }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #243258, stop:1 #1a2848); border-color: #3a7abf; color: #d0e4f8; }
            QPushButton:disabled { background-color: #0e121c; color: #2a3548; border-color: #141c28; }
            #btn_connect { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1a4a7a, stop:1 #123258); border-color: #2a6aaa; color: #78c0f0; font-weight: 600; }
            #btn_connect:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #205a90, stop:1 #163c70); border-color: #4a9ae0; color: #a8d8ff; }
            #btn_connect:disabled { background-color: #0c1c30; color: #1a3a58; border-color: #0e1e30; }
            #btn_disconnect { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3a1a1a, stop:1 #281010); border-color: #6a2a2a; color: #c06868; font-weight: 600; }
            #btn_disconnect:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a2020, stop:1 #341414); border-color: #9a4040; color: #ff9090; }
            QTreeWidget { background-color: #0b0f18; border: 1px solid #1a2434; alternate-background-color: #0d1120; color: #a8bccc; border-radius: 6px; outline: none; }
            QTreeWidget::item { padding: 5px 10px; border-bottom: 1px solid #131924; }
            QTreeWidget::item:hover { background-color: #162030; }
            QTreeWidget::item:selected { background-color: #1a3258; color: #d0e8ff; }
            QHeaderView::section { background-color: #0d1220; color: #3a6a9a; border: none; border-bottom: 1px solid #1a2434; padding: 6px 10px; font-size: 10px; font-weight: bold; letter-spacing: 2px; }
            QTextEdit { background-color: #080b10; border: 1px solid #1a2434; border-radius: 6px; color: #5a9060; font-family: 'Consolas', monospace; font-size: 11px; padding: 6px; }
            QSplitter::handle { background-color: #1a2434; width: 2px; height: 2px; }
            QStatusBar { background-color: #080b10; color: #304a6a; border-top: 1px solid #1a2434; font-size: 11px; }
            QScrollBar:vertical { background-color: #0b0f18; width: 7px; }
            QScrollBar::handle:vertical { background-color: #243450; border-radius: 3px; min-height: 28px; }
            QScrollBar:horizontal { background-color: #0b0f18; height: 7px; }
            QScrollBar::handle:horizontal { background-color: #243450; border-radius: 3px; min-width: 28px; }
            #path_bar { background-color: #0b0f18; border: 1px solid #1a2434; border-radius: 5px; color: #3a8abf; font-family: 'Consolas', monospace; font-size: 11px; padding: 5px 10px; }
            #file_viewer { background-color: #060810; border: 1px solid #1a2434; border-radius: 6px; color: #72b060; font-family: 'Consolas', monospace; font-size: 11px; padding: 8px; }
            #hline { background-color: #1a2434; max-height: 1px; min-height: 1px; border: none; margin: 4px 0px; }
            #status_dot { font-size: 12px; font-weight: bold; padding: 4px 0px; letter-spacing: 1px; }
            #board_type_label { color: #2a4a6a; font-size: 9px; font-weight: bold; letter-spacing: 2px; padding: 1px 0px 4px 0px; }
            #ip_label { color: #2a4a6a; font-size: 10px; font-family: 'Consolas', monospace; padding: 2px 0px; }
            #app_title { color: #4a8abf; font-size: 11px; font-weight: bold; letter-spacing: 4px; padding: 2px 0px; }
            #app_version { color: #1e3a58; font-size: 9px; letter-spacing: 3px; }
            QTabWidget::pane { border: none; background: #080b10; }
            QTabBar::tab { background: #0d1220; color: #2e5070; padding: 7px 20px; border: 1px solid #1a2434; font-size: 10px; font-weight: bold; letter-spacing: 2px; margin-right: 2px; }
            QTabBar::tab:selected { background: #080b10; color: #4a90c4; }
            QTabBar::tab:hover { color: #6ab0e4; }
            QToolTip { background-color: #0d1220; color: #90b8d8; border: 1px solid #2a4a6a; border-radius: 4px; padding: 5px 8px; font-size: 11px; }
            """

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
                self.ip_label.clear()
                return
            info = self.bc.stands[name]
            icon_path = _board_icon_path(info.stand_type)
            if icon_path:
                self.board_icon_lbl.setPixmap(
                    QPixmap(icon_path).scaled(190, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.board_type_lbl.setText(f"[ {info.stand_type.upper()} ]" if info.stand_type else "[ UNKNOWN ]")
            self.ip_label.setText(f"{info.ip}:{info.port}")

        def _update_folder_combo(self):
            name = self.stand_combo.currentText()
            self.folder_combo.clear()
            if name and name in self.bc.stands:
                for folder in self.bc.stands[name].browse_folders:
                    self.folder_combo.addItem(folder)

        def _on_stand_changed(self, _):
            self._update_board_icon()
            self._update_folder_combo()

        def _start_status_timer(self):
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh_status)
            self._timer.start(2500)

        def _refresh_status(self):
            name = self.stand_combo.currentText()
            if not name or name not in self.bc.stands:
                return
            info = self.bc.stands[name]

            if info.connected:
                self.status_dot.setText("●   CONNECTED")
                self.status_dot.setStyleSheet("color: #38c060; font-size:12px; font-weight:bold;")
                self.qconn_lbl.setText("[  QCONN  ]" if info.qconn_active else "")
            elif info.status == "online":
                self.status_dot.setText("●   ONLINE")
                self.status_dot.setStyleSheet("color: #2a9aaa; font-size:12px; font-weight:bold;")
                self.qconn_lbl.setText("")
            else:
                self.status_dot.setText("●   OFFLINE")
                self.status_dot.setStyleSheet("color: #253545; font-size:12px; font-weight:bold;")
                self.qconn_lbl.setText("")

        def _on_connect(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("⏳   Соединение...")
            self._log(f"▶ Подключение → {name}")

            worker = ConnectWorker(self.bc, name)
            worker.log.connect(self._log)
            worker.finished.connect(self._on_connect_done)
            self._workers.append(worker)
            worker.start()

        def _on_connect_done(self, ok, msg, stand_name):
            self.btn_connect.setText("⏎   Подключиться")
            if ok:
                self.btn_connect.setEnabled(False)
                self.btn_disconnect.setEnabled(True)
                self.btn_up.setEnabled(True)
                self._log(f"✓ {msg}")
                self.statusBar().showMessage(msg, 5000)
                self.current_stand = stand_name
                self.current_path = self.bc.stands[stand_name].browse_folders[0]
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
            self.current_stand = None
            self._log(f"✕ Отключено от {name}")

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

        def _on_refresh(self):
            if self.current_stand and self.current_path:
                self._load_directory(self.current_stand, self.current_path)

        def _load_directory(self, stand_name, path):
            self.file_tree.clear()
            self.file_viewer.clear()
            self.path_label.setText(path)
            self._log(f"  › cd {path}")
            self.statusBar().showMessage(f"Загрузка {path}...")

            worker = ListDirWorker(self.bc, stand_name, path)
            worker.finished.connect(self._on_dir_loaded)
            self._workers.append(worker)
            worker.start()

        def _on_dir_loaded(self, ok, entries, err, path):
            self.file_tree.clear()
            if not ok:
                self._log(f"  ✗ {err}")
                self.statusBar().showMessage(f"Ошибка: {err}", 4000)
                return
            if not entries:
                self._log("  (пусто)")
                return

            dirs = sorted([e for e in entries if e["is_dir"]], key=lambda x: x["name"].lower())
            files = sorted([e for e in entries if not e["is_dir"]], key=lambda x: x["name"].lower())

            for e in dirs + files:
                is_dir = e["is_dir"]
                icon = "📁" if is_dir else "📄"
                size = self._fmt_size(e["size"]) if not is_dir else ""
                item = QTreeWidgetItem([f"{icon}  {e['name']}", "папка" if is_dir else "файл", size, e["perms"]])
                item.setData(0, Qt.UserRole, e)

                if is_dir:
                    item.setForeground(0, QColor("#3a8ac4"))
                else:
                    item.setForeground(2, QColor("#3a6a4a"))

                self.file_tree.addTopLevelItem(item)

            self._log(f"  ✓ {len(dirs)} папок, {len(files)} файлов")
            self.statusBar().showMessage(f"{path}  •  {len(dirs)} папок, {len(files)} файлов", 6000)

        def _on_tree_double_click(self, item, _):
            entry = item.data(0, Qt.UserRole)
            if entry and entry["is_dir"] and self.current_stand:
                self.current_path = entry["path"]
                self._load_directory(self.current_stand, entry["path"])

        def _on_tree_click(self, item, _):
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
                self.file_viewer.setText(f"══════  {path}  ══════\n\n{content}")
                self._log(f"  ✓ файл прочитан: {path}")
            else:
                self.file_viewer.setText(f"✗ Ошибка чтения:\n{content}")
                self._log(f"  ✗ ошибка чтения {path}")

        def _on_diagnose(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self._log(f"─── Диагностика {name} ───")
            result = self.bc.diagnose_connection(name)
            self._log(result)
            self.right_tabs.setCurrentIndex(1)

        @staticmethod
        def _fmt_size(n):
            if n < 1024:
                return f"{n} B"
            elif n < 1024 * 1024:
                return f"{n / 1024:.1f} KB"
            elif n < 1024 ** 3:
                return f"{n / 1024 / 1024:.1f} MB"
            return f"{n / 1024 / 1024 / 1024:.2f} GB"

        def _log(self, text):
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.append(f'<span style="color:#1e3c28">[{ts}]</span> <span style="color:#4a7a5a">{text}</span>')

        def closeEvent(self, event):
            self.bc.stop_monitoring()
            event.accept()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0e1118"))
    palette.setColor(QPalette.WindowText, QColor("#b8c8dc"))
    palette.setColor(QPalette.Base, QColor("#0b0f18"))
    palette.setColor(QPalette.Text, QColor("#b8c8dc"))
    palette.setColor(QPalette.Button, QColor("#1c2840"))
    palette.setColor(QPalette.ButtonText, QColor("#90aac8"))
    palette.setColor(QPalette.Highlight, QColor("#1a3258"))
    palette.setColor(QPalette.HighlightedText, QColor("#d0e8ff"))
    app.setPalette(palette)

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
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--version", "-v", action="store_true")
    parser.add_argument("--info", action="store_true")
    parser.add_argument("--stand", "-s", type=str)
    parser.add_argument("--diagnose", type=str)
    args = parser.parse_args()

    if args.version:
        print("Bench Manager v4.0")
        return

    if args.info:
        print(f"paramiko : {'установлен' if HAS_PARAMIKO else 'НЕ УСТАНОВЛЕН'}")
        print(f"pyyaml   : {'установлен' if HAS_YAML else 'НЕ УСТАНОВЛЕН'}")
        return

    config = load_config()
    bc = BenchConnector(config)
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

    try:
        _build_gui(bc)
    except ImportError as e:
        print(f"PyQt5 не найден: {e}")
        print("Установите: pip install PyQt5")
        sys.exit(1)


if __name__ == "__main__":
    main()