#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bench Manager v3.0
- Подключение через Paramiko в отдельном QThread (GUI не зависает)
- Браузер папок на стенде через SSH (ls), не через SFTP
- Правильные пути для PyInstaller (sys._MEIPASS)
- Пароли из .env / config.yaml (не хардкод)
- Иконки стендов из gui/images (arktika, c1m, goz, orangepi, logo)
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
# ПУТИ — работают и в .py и в собранном .exe (PyInstaller)
# ============================================================
if getattr(sys, "frozen", False):
    # Запуск из .exe — все встроенные ресурсы (config, images) лежат в sys._MEIPASS
    BASE_DIR = sys._MEIPASS
    # APP_DIR — папка рядом с .exe, туда кладём .env и пишем логи
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

IMAGES_DIR  = os.path.join(BASE_DIR, "gui", "images")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")   # внутри _MEIPASS при сборке
ENV_PATH    = os.path.join(APP_DIR, ".env")            # рядом с .exe — не упаковывается

# ============================================================
# ИКОНКИ — сопоставление типа платы → имя файла в gui/images
# ============================================================

# Ключи — значения поля board.type из config.yaml (нижний регистр).
# Можно добавлять новые пары без правки логики GUI.
BOARD_ICON_MAP = {
    "arktika"  : "arktika.png",
    "c1m"      : "c1m.png",
    "goz"      : "goz.png",
    "orangepi" : "orangepi.png",
}

# Иконка по умолчанию — logo.png
DEFAULT_ICON = "logo.png"


def _icon_path(filename: str) -> str:
    """Полный путь к файлу иконки. Возвращает пустую строку если файл не найден."""
    path = os.path.join(IMAGES_DIR, filename)
    return path if os.path.exists(path) else ""


def _board_icon_path(board_type: str) -> str:
    """
    Возвращает путь к иконке по типу платы.
    Если тип не распознан или файл отсутствует — возвращает путь к logo.png.
    """
    key      = (board_type or "").strip().lower()
    filename = BOARD_ICON_MAP.get(key, DEFAULT_ICON)
    path     = _icon_path(filename)
    if not path:
        # Попробуем fallback на logo.png
        path = _icon_path(DEFAULT_ICON)
    return path


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
    """Читает .env рядом с .exe / main.py, не перетирает уже заданные переменные."""
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
    """
    Читает config.yaml.
    Пароли: env-переменная BENCH_PASSWORD_<NAME> -> поле password в yaml -> пустая строка.
    Приоритет env позволяет не хранить пароли в репозитории.
    """
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
            print(f"WARNING: пароль для '{stand['name']}' не задан "
                  f"(нет {env_key} и нет поля password в config.yaml)")
        stand["password"] = password

    return cfg


def _default_config() -> dict:
    """Минимальный конфиг если config.yaml не найден."""
    return {
        "stands": [],
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
        self.status     = "offline"   # "online" | "offline"
        self.connected  = False
        self.stand_type = stand_type
        self.port       = port
        self.ssh_client = None
        # Папки из config.yaml (cvs, tmp, config)
        self.folders    = folders or {}

    @property
    def cvs_path(self) -> str:
        return self.folders.get("cvs", "/home/pkrv/CVS")


# ============================================================
# CONNECTOR
# ============================================================

class BenchConnector:

    def __init__(self, config: dict = None):
        self.config    = config or load_config()
        self.stands    = {}
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
    # Мониторинг доступности
    # ----------------------------------------------------------

    def check_availability(self, ip, port=22) -> bool:
        """
        TCP + попытка прочитать SSH-баннер.
        При timeout на recv считаем online — порт открыт, SSH просто медленный.
        Сокет всегда закрывается через finally.
        """
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
                return True   # порт открыт, баннер не успел — не блокируем
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
                    # Если уже есть активное SSH-соединение — доверяем ему,
                    # TCP-пинг не трогает живую сессию (race condition fix).
                    if info.connected and info.ssh_client:
                        try:
                            transport = info.ssh_client.get_transport()
                            if transport and transport.is_active():
                                info.status = "online"
                                continue
                        except Exception:
                            pass
                        # Транспорт умер — помечаем как offline и чистим
                        try:
                            info.ssh_client.close()
                        except Exception:
                            pass
                        info.ssh_client = None
                        info.connected  = False
                        info.status     = "offline"
                        continue

                    # Нет активного SSH — проверяем TCP-доступность
                    available = self.check_availability(info.ip, info.port)
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
        Синхронное подключение через Paramiko.
        В GUI вызывать ТОЛЬКО из QThread (см. ConnectWorker), иначе окно зависнет.
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
                f"Добавьте BENCH_PASSWORD_{name.upper()} в .env "
                f"или поле password в config.yaml"
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

            info.ssh_client = ssh
            info.connected  = True
            info.status     = "online"
            return True, f"Подключено к {name} ({info.ip})"

        except AuthenticationException:
            return False, "Ошибка авторизации: неверный логин или пароль"
        except SSHException as e:
            return False, f"SSH ошибка: {e}"
        except (socket.timeout, TimeoutError, OSError) as e:
            return False, f"Таймаут / сетевая ошибка подключения к {info.ip}:{info.port} — {e}"
        except Exception as e:
            return False, f"Ошибка: {e}"

    def disconnect(self, name):
        if name in self.stands:
            info = self.stands[name]
            if info.ssh_client:
                try:
                    info.ssh_client.close()
                except Exception:
                    pass
                info.ssh_client = None
            info.connected = False

    # ----------------------------------------------------------
    # Выполнение команд
    # ----------------------------------------------------------

    def execute(self, name, command, timeout=30):
        """Выполнить команду, вернуть (ok, stdout, stderr)."""
        if name not in self.stands or not self.stands[name].connected:
            return False, "", "Нет подключения"
        info = self.stands[name]
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
    # Браузер папок — через SSH, не через SFTP
    # ----------------------------------------------------------

    def list_directory(self, name, path=None):
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info   = self.stands[name]
        target = path or info.cvs_path

        cmd = f"ls -la --time-style=+ '{target}' 2>&1"
        ok, out, _ = self.execute(name, cmd)
        if not ok:
            return False, [], "Команда не выполнена"

        if "No such file" in out or "Permission denied" in out:
            return False, [], out.strip()

        return self._parse_ls(out, target)

    def list_directory_as_qconn(self, name, path=None):
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info   = self.stands[name]
        target = path or info.cvs_path

        cmd = f'su qconn -c \'ls -la --time-style=+ "{target}"\' 2>&1'
        ok, out, _ = self.execute(name, cmd)
        if not ok:
            return False, [], "Команда su qconn не выполнена"

        lines = out.strip().splitlines()
        if lines and lines[0].lower().startswith("password"):
            return False, [], (
                "su qconn требует пароль. "
                "Настройте /etc/sudoers: pkrv ALL=(qconn) NOPASSWD: ALL"
            )

        return self._parse_ls(out, target)

    @staticmethod
    def _parse_ls(output: str, base_path: str):
        """
        Парсит вывод ls -la --time-style=+ в список словарей.

        Формат строки с --time-style=+:
          drwxr-xr-x  2 pkrv pkrv  4096  dirname
          -rw-r--r--  1 pkrv pkrv  1234  file with spaces.txt

        --time-style=+ убирает дату полностью, поэтому после size (поле [4])
        идёт сразу имя файла, которое может содержать пробелы.
        Берём его как join от parts[8:] (нумерация: perms links user group size name).
        Но ls без даты выдаёт 6 полей до имени: perms links user group size name.
        Поэтому имя = parts[5:] соединённые пробелом.
        """
        entries = []
        for line in output.strip().splitlines():
            if not line or line.startswith("total"):
                continue
            parts = line.split()
            # Минимум 6 полей: perms links user group size name
            if len(parts) < 6:
                continue
            perms  = parts[0]
            size   = int(parts[4]) if parts[4].isdigit() else 0
            # Имя файла — всё начиная с 6-го поля (индекс 5), склеиваем пробелом
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
    # Деплой файлов
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

        results.append("[1/4] Проверка локального файла...")
        if not os.path.exists(mpo_path):
            return False, "Файл mpo не найден в " + local_dir
        results.append(f" + найден: {mpo_path}")
        results.append("")

        remote_path = info.cvs_path + "/mpo"
        results.append(f"[2/4] Копирование -> {remote_path} ...")
        try:
            sftp = info.ssh_client.open_sftp()
            sftp.put(mpo_path, remote_path)
            sftp.close()
            results.append(" + скопирован")
        except Exception as e:
            results.append(f" ОШИБКА SFTP: {e}")
            return False, "\n".join(results)
        results.append("")

        if mode == "move":
            try:
                os.remove(mpo_path)
                results.append(" + локальный файл удалён (mode=move)")
            except Exception as e:
                results.append(f" ! не удалось удалить локальный файл: {e}")
        results.append("")

        results.append("[3/4] Установка прав...")
        ok, _, _ = self.execute(name, f"chmod +x '{remote_path}' && sync")
        results.append(" + OK" if ok else " ! ошибка chmod")
        results.append("")

        results.append("[4/4] Проверка на стенде...")
        ok, out, _ = self.execute(name, f"ls -la '{remote_path}'")
        results.append(f" + {out.strip()}" if ok else " ! файл не найден")
        results.append("")
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
        if not HAS_PARAMIKO:
            lines.append(" paramiko не установлен — SSH-тест пропущен")
        else:
            try:
                ssh = paramiko.SSHClient()
                known = os.path.expanduser("~/.ssh/known_hosts")
                if os.path.exists(known):
                    try:
                        ssh.load_host_keys(known)
                    except Exception:
                        pass
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

        lines += ["", "=== КОНЕЦ ДИАГНОСТИКИ ==="]
        return "\n".join(lines)

    def get_all_info(self) -> dict:
        return {
            name: {
                "name"     : s.name,
                "ip"       : s.ip,
                "username" : s.username,
                "status"   : s.status,
                "connected": s.connected,
                "type"     : s.stand_type,
                "port"     : s.port,
            }
            for name, s in self.stands.items()
        }


# ============================================================
# GUI — QThread для подключения (не блокирует интерфейс)
# ============================================================

def _build_gui(bc: BenchConnector):
    """Строит и запускает PyQt5 GUI. Вызывается только из main()."""

    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QTextEdit, QTreeWidget, QTreeWidgetItem,
        QSplitter, QComboBox, QStatusBar, QMessageBox, QFrame,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt5.QtGui import QFont, QIcon, QPixmap

    # ----------------------------------------------------------
    # Вспомогательная функция — загрузить QIcon по пути.
    # Возвращает QIcon (пустой если файл не найден — Qt не упадёт).
    # ----------------------------------------------------------
    def load_icon(path: str) -> QIcon:
        if path and os.path.exists(path):
            return QIcon(path)
        return QIcon()

    # ----------------------------------------------------------
    # Worker — подключение в фоновом потоке
    # ----------------------------------------------------------
    class ConnectWorker(QThread):
        finished = pyqtSignal(bool, str, str)  # ok, message, stand_name
        log      = pyqtSignal(str)

        def __init__(self, connector, stand_name):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name

        def run(self):
            self.log.emit(f"Подключаемся к {self.stand_name}...")
            ok, msg = self.connector.connect(self.stand_name)
            self.finished.emit(ok, msg, self.stand_name)  # имя стенда фиксируем здесь

    # ----------------------------------------------------------
    # Worker — листинг папки в фоновом потоке
    # ----------------------------------------------------------
    class ListDirWorker(QThread):
        finished = pyqtSignal(bool, list, str)
        log      = pyqtSignal(str)

        def __init__(self, connector, stand_name, path, as_qconn=False):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name
            self.path       = path
            self.as_qconn   = as_qconn

        def run(self):
            if self.as_qconn:
                ok, entries, err = self.connector.list_directory_as_qconn(
                    self.stand_name, self.path)
            else:
                ok, entries, err = self.connector.list_directory(
                    self.stand_name, self.path)
            self.finished.emit(ok, entries, err)

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

            self.setWindowTitle("Bench Manager v3.0")
            self.setMinimumSize(900, 600)

            # Иконка приложения — logo.png
            app_icon_path = _icon_path(DEFAULT_ICON)
            if app_icon_path:
                self.setWindowIcon(QIcon(app_icon_path))

            self._build_ui()
            self._start_status_timer()

        # ---------- UI ----------

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QHBoxLayout(central)
            root.setContentsMargins(6, 6, 6, 6)

            splitter = QSplitter(Qt.Horizontal)
            root.addWidget(splitter)

            # Левая панель — список стендов
            left = QWidget()
            left.setFixedWidth(240)
            lv = QVBoxLayout(left)
            lv.setContentsMargins(4, 4, 4, 4)
            lv.setSpacing(6)

            # Логотип приложения в верхней части боковой панели
            logo_path = _icon_path(DEFAULT_ICON)
            if logo_path:
                logo_label = QLabel()
                pixmap = QPixmap(logo_path).scaled(
                    200, 60,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                logo_label.setPixmap(pixmap)
                logo_label.setAlignment(Qt.AlignCenter)
                lv.addWidget(logo_label)

                line_top = QFrame()
                line_top.setFrameShape(QFrame.HLine)
                lv.addWidget(line_top)

            lv.addWidget(QLabel("Стенды:"))

            # ComboBox стендов — с иконкой платы для каждого стенда
            self.stand_combo = QComboBox()
            self.stand_combo.setIconSize(QSize(24, 24))
            for name, info in self.bc.stands.items():
                icon = load_icon(_board_icon_path(info.stand_type))
                self.stand_combo.addItem(icon, name)
            # При смене стенда обновляем иконку стенда в заголовке
            self.stand_combo.currentIndexChanged.connect(self._on_stand_changed)
            lv.addWidget(self.stand_combo)

            # Иконка текущего стенда (крупная, под комбобоксом)
            self.stand_icon_label = QLabel()
            self.stand_icon_label.setAlignment(Qt.AlignCenter)
            lv.addWidget(self.stand_icon_label)
            self._update_stand_icon()   # показываем иконку сразу

            self.btn_connect = QPushButton("Подключиться")
            self.btn_connect.clicked.connect(self._on_connect)
            lv.addWidget(self.btn_connect)

            self.btn_disconnect = QPushButton("Отключиться")
            self.btn_disconnect.setEnabled(False)
            self.btn_disconnect.clicked.connect(self._on_disconnect)
            lv.addWidget(self.btn_disconnect)

            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            lv.addWidget(line)

            self.btn_browse = QPushButton("Открыть папки (pkrv)")
            self.btn_browse.setEnabled(False)
            self.btn_browse.clicked.connect(self._on_browse)
            lv.addWidget(self.btn_browse)

            self.btn_browse_qconn = QPushButton("Открыть папки (qconn)")
            self.btn_browse_qconn.setEnabled(False)
            self.btn_browse_qconn.clicked.connect(self._on_browse_qconn)
            lv.addWidget(self.btn_browse_qconn)

            self.btn_diagnose = QPushButton("Диагностика")
            self.btn_diagnose.clicked.connect(self._on_diagnose)
            lv.addWidget(self.btn_diagnose)

            lv.addStretch()

            # Индикатор статуса
            self.status_dot = QLabel("● offline")
            self.status_dot.setStyleSheet("color: gray;")
            lv.addWidget(self.status_dot)

            splitter.addWidget(left)

            # Правая панель
            right_splitter = QSplitter(Qt.Vertical)

            # Дерево файлов
            self.file_tree = QTreeWidget()
            self.file_tree.setHeaderLabels(["Имя", "Тип", "Размер", "Права"])
            self.file_tree.setColumnWidth(0, 280)
            self.file_tree.setColumnWidth(1, 60)
            self.file_tree.setColumnWidth(2, 80)
            self.file_tree.itemDoubleClicked.connect(self._on_tree_double_click)
            right_splitter.addWidget(self.file_tree)

            # Лог
            self.log_box = QTextEdit()
            self.log_box.setReadOnly(True)
            self.log_box.setFont(QFont("Courier New", 9))
            self.log_box.setMaximumHeight(180)
            right_splitter.addWidget(self.log_box)

            splitter.addWidget(right_splitter)
            splitter.setSizes([240, 660])

            self.setStatusBar(QStatusBar())

        # ---------- Иконки стендов ----------

        def _update_stand_icon(self):
            """Обновляет крупную иконку платы под комбобоксом."""
            name = self.stand_combo.currentText()
            if not name or name not in self.bc.stands:
                self.stand_icon_label.clear()
                return

            info      = self.bc.stands[name]
            icon_path = _board_icon_path(info.stand_type)
            if icon_path:
                pixmap = QPixmap(icon_path).scaled(
                    180, 90,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.stand_icon_label.setPixmap(pixmap)
                # Подпись с типом платы под иконкой
                board_type = info.stand_type or "unknown"
                self.stand_icon_label.setToolTip(f"Тип платы: {board_type}")
            else:
                self.stand_icon_label.clear()

        def _on_stand_changed(self, _index):
            self._update_stand_icon()

        # ---------- Таймер статуса ----------

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
                self.status_dot.setText("● connected")
                self.status_dot.setStyleSheet("color: limegreen;")
            elif info.status == "online":
                self.status_dot.setText("● online")
                self.status_dot.setStyleSheet("color: green;")
            else:
                self.status_dot.setText("● offline")
                self.status_dot.setStyleSheet("color: gray;")

        # ---------- Подключение ----------

        def _on_connect(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("Подключение...")
            self._log(f"Подключаемся к {name}...")

            worker = ConnectWorker(self.bc, name)
            worker.log.connect(self._log)
            worker.finished.connect(self._on_connect_done)
            self._workers.append(worker)
            worker.start()

        def _on_connect_done(self, ok, msg, stand_name):
            # stand_name — имя стенда из worker, не из комбобокса.
            # Это важно: пользователь мог сменить выбор пока шло подключение.
            self.btn_connect.setText("Подключиться")
            if ok:
                self.btn_connect.setEnabled(False)
                self.btn_disconnect.setEnabled(True)
                self.btn_browse.setEnabled(True)
                self.btn_browse_qconn.setEnabled(True)
                self._log(f"✓ {msg}")
                self.statusBar().showMessage(msg)
                self.current_stand = stand_name
                self.current_path  = self.bc.stands[stand_name].cvs_path
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
            self.btn_browse.setEnabled(False)
            self.btn_browse_qconn.setEnabled(False)
            self.file_tree.clear()
            self._log(f"Отключено от {name}")

        # ---------- Браузер папок ----------

        def _on_browse(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self.current_stand = name
            self.current_path  = self.bc.stands[name].cvs_path
            self._load_directory(name, self.current_path, as_qconn=False)

        def _on_browse_qconn(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self.current_stand = name
            self.current_path  = self.bc.stands[name].cvs_path
            self._load_directory(name, self.current_path, as_qconn=True)

        def _load_directory(self, stand_name, path, as_qconn=False):
            self.file_tree.clear()
            mode = "qconn" if as_qconn else "pkrv"
            self._log(f"Загрузка {path} [{mode}]...")
            self.statusBar().showMessage(f"Загрузка {path}...")

            worker = ListDirWorker(self.bc, stand_name, path, as_qconn=as_qconn)
            worker.log.connect(self._log)
            worker.finished.connect(
                lambda ok, entries, err: self._on_dir_loaded(ok, entries, err, path)
            )
            self._workers.append(worker)
            worker.start()

        def _on_dir_loaded(self, ok, entries, err, path):
            self.file_tree.clear()
            if not ok:
                self._log(f"✗ {err}")
                self.statusBar().showMessage(f"Ошибка: {err}")
                return

            if not entries:
                self._log("  (папка пуста или нет прав)")
                self.statusBar().showMessage(f"{path} — пусто")
                return

            for e in sorted(entries, key=lambda x: (not x["is_dir"], x["name"].lower())):
                icon = "[D]" if e["is_dir"] else "[F]"
                size = f"{e['size']:,}" if not e["is_dir"] else ""
                item = QTreeWidgetItem([
                    f"{icon} {e['name']}",
                    "папка" if e["is_dir"] else "файл",
                    size,
                    e["perms"],
                ])
                item.setData(0, Qt.UserRole, e)
                self.file_tree.addTopLevelItem(item)

            self._log(f"  {len(entries)} объектов в {path}")
            self.statusBar().showMessage(f"{path}  ({len(entries)} объектов)")

        def _on_tree_double_click(self, item, _col):
            """Двойной клик по папке — заходим внутрь."""
            entry = item.data(0, Qt.UserRole)
            if entry and entry["is_dir"] and self.current_stand:
                self._load_directory(self.current_stand, entry["path"])
                self.current_path = entry["path"]

        # ---------- Диагностика ----------

        def _on_diagnose(self):
            name = self.stand_combo.currentText()
            if not name:
                return
            self._log(f"--- Диагностика {name} ---")
            result = self.bc.diagnose_connection(name)
            self._log(result)

        # ---------- Утилиты ----------

        def _log(self, text):
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.append(f"[{ts}] {text}")

        def closeEvent(self, event):
            self.bc.stop_monitoring()
            event.accept()

    # ----------------------------------------------------------
    # Запуск приложения
    # ----------------------------------------------------------
    app    = QApplication(sys.argv)

    # Иконка в панели задач / Alt-Tab — тоже logo.png
    app_icon_path = _icon_path(DEFAULT_ICON)
    if app_icon_path:
        app.setWindowIcon(QIcon(app_icon_path))

    window = MainWindow(bc)
    window.show()
    sys.exit(app.exec_())


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Bench Manager")
    parser.add_argument("--console",  "-c", action="store_true", help="Подключиться ко всем стендам")
    parser.add_argument("--check",          action="store_true", help="Показать статус стендов")
    parser.add_argument("--version",  "-v", action="store_true")
    parser.add_argument("--info",           action="store_true", help="Версии библиотек")
    parser.add_argument("--stand",    "-s", type=str,            help="Подключиться к конкретному стенду")
    parser.add_argument("--diagnose",       type=str,            help="Диагностика стенда")
    args = parser.parse_args()

    if args.version:
        print("Bench Manager v3.0")
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
        print(f"\n{'Стенд':<14} {'IP':>18}  {'Статус'}")
        print("-" * 44)
        for name, info in bc.get_all_info().items():
            s = "ONLINE" if info["status"] == "online" else "offline"
            print(f" {name:<13} {info['ip']:>16}:{info['port']:<5}  {s}")
        bc.stop_monitoring()
        return

    if args.console:
        time.sleep(1)
        for name in bc.stands:
            ok, msg = bc.connect(name)
            print(f"{'OK' if ok else 'ERR'} {name}: {msg}")
        bc.stop_monitoring()
        return

    # GUI режим
    try:
        _build_gui(bc)
    except ImportError as e:
        print(f"PyQt5 не найден: {e}")
        print("Установите: pip install PyQt5")
        sys.exit(1)


if __name__ == "__main__":
    main()
