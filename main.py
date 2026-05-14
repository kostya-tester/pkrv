#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bench Manager v3.0
- Подключение через Paramiko в отдельном QThread (GUI не зависает)
- Браузер папок на стенде через SSH (ls), не через SFTP
- Правильные пути для PyInstaller (sys._MEIPASS)
- Пароли из .env / config.yaml (не хардкод)
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

IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")   # внутри _MEIPASS при сборке
ENV_PATH    = os.path.join(APP_DIR, ".env")            # рядом с .exe — не упаковывается

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
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            if s.connect_ex((ip, port)) != 0:
                s.close()
                return False
            s.settimeout(2)
            try:
                banner = s.recv(64)
                ok = banner.startswith(b"SSH")
            except socket.timeout:
                ok = True   # порт открыт, баннер не успел — не блокируем
            s.close()
            return ok
        except Exception:
            return False

    def start_monitoring(self):
        if self.monitoring:
            return
        self.monitoring = True

        def loop():
            interval = self.config.get("monitoring", {}).get("check_interval", 5)
            while self.monitoring:
                for name, info in list(self.stands.items()):
                    available = self.check_availability(info.ip, info.port)
                    if available:
                        info.status = "online"
                    else:
                        info.status = "offline"
                        if info.connected and info.ssh_client:
                            try:
                                info.ssh_client.close()
                            except Exception:
                                pass
                            info.ssh_client = None
                        info.connected = False
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
            # WarningPolicy: предупреждает о неизвестном ключе, но не блокирует.
            # Это нужно для старых стендов где known_hosts не ведётся.
            # Для production-среды замените на RejectPolicy + ssh-keyscan.
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

            # Быстрая проверка что сессия живая
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
        except socket.timeout:
            return False, f"Таймаут подключения к {info.ip}:{info.port}"
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
        """
        Возвращает список файлов/папок в path на стенде.
        Использует SSH-команду ls, а не SFTP — это работает даже когда
        SFTP-подсистема ограничена или путь виден только в shell-окружении.

        Возвращает (ok, [{"name", "is_dir", "size", "perms", "path"}], error_msg)
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info   = self.stands[name]
        target = path or info.cvs_path

        # --time-style=+ убирает дату из вывода, делает парсинг стабильным
        cmd = f"ls -la --time-style=+ '{target}' 2>&1"
        ok, out, _ = self.execute(name, cmd)
        if not ok:
            return False, [], "Команда не выполнена"

        # Если путь не существует или нет прав — ls вернёт ошибку в stdout (из-за 2>&1)
        if "No such file" in out or "Permission denied" in out:
            return False, [], out.strip()

        return self._parse_ls(out, target)

    def list_directory_as_qconn(self, name, path=None):
        """
        Листинг от имени пользователя qconn через su.
        Используется когда папки видны только qconn, а SSH-сессия открыта от pkrv.

        Требует что pkrv может делать su qconn без пароля.
        Настройка на стенде: добавить в /etc/sudoers строку
            pkrv ALL=(qconn) NOPASSWD: ALL
        """
        if name not in self.stands or not self.stands[name].connected:
            return False, [], "Нет подключения"

        info   = self.stands[name]
        target = path or info.cvs_path

        # su -c запускает команду от qconn в неинтерактивном режиме
        cmd = f'su qconn -c \'ls -la --time-style=+ "{target}"\' 2>&1'
        ok, out, _ = self.execute(name, cmd)
        if not ok:
            return False, [], "Команда su qconn не выполнена"

        lines = out.strip().splitlines()
        # Если su попросил пароль — первая строка будет "Password:"
        if lines and lines[0].lower().startswith("password"):
            return False, [], (
                "su qconn требует пароль. "
                "Настройте /etc/sudoers: pkrv ALL=(qconn) NOPASSWD: ALL"
            )

        return self._parse_ls(out, target)

    @staticmethod
    def _parse_ls(output: str, base_path: str):
        """Парсит вывод ls -la в список словарей."""
        entries = []
        for line in output.strip().splitlines():
            if not line or line.startswith("total"):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            perms  = parts[0]
            size   = int(parts[4]) if parts[4].isdigit() else 0
            fname  = parts[-1]
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
        """
        Деплой mpo на стенд через SFTP.
        mode="copy" — оригинал остаётся локально.
        mode="move" — локальный файл удаляется после копирования.
        """
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

        # Ping
        lines.append("--- Сеть ---")
        try:
            flag = "-n 1 -w 2000" if sys.platform == "win32" else "-c 1 -W 2"
            r = subprocess.run(f"ping {flag} {info.ip}",
                               shell=True, capture_output=True, timeout=5)
            lines.append(f" Ping : {'OK' if r.returncode == 0 else 'FAIL'}")
        except Exception:
            lines.append(" Ping : TIMEOUT")

        # TCP-порт
        try:
            s = socket.socket()
            s.settimeout(2)
            res = s.connect_ex((info.ip, info.port))
            s.close()
            lines.append(f" Port {info.port}: {'OPEN' if res == 0 else 'CLOSED'}")
        except Exception:
            lines.append(f" Port {info.port}: ERROR")

        # Попытка SSH
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
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
    from PyQt5.QtGui import QFont

    # ----------------------------------------------------------
    # Worker — подключение в фоновом потоке
    # Именно это устраняет "connecting и слетает":
    # ssh.connect() может занять 5-10 сек, и если он вызывается
    # в главном потоке — Qt считает что приложение зависло и убивает его.
    # ----------------------------------------------------------
    class ConnectWorker(QThread):
        finished = pyqtSignal(bool, str)   # ok, message
        log      = pyqtSignal(str)

        def __init__(self, connector, stand_name):
            super().__init__()
            self.connector  = connector
            self.stand_name = stand_name

        def run(self):
            self.log.emit(f"Подключаемся к {self.stand_name}...")
            ok, msg = self.connector.connect(self.stand_name)
            self.finished.emit(ok, msg)

    # ----------------------------------------------------------
    # Worker — листинг папки в фоновом потоке
    # Тоже в отдельном потоке — ls по SSH может занять секунду.
    # ----------------------------------------------------------
    class ListDirWorker(QThread):
        finished = pyqtSignal(bool, list, str)   # ok, entries, error
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
            self._workers      = []   # держим ссылки, чтобы QThread не собрался GC

            self.setWindowTitle("Bench Manager v3.0")
            self.setMinimumSize(900, 600)
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
            left.setFixedWidth(220)
            lv = QVBoxLayout(left)
            lv.setContentsMargins(0, 0, 0, 0)

            lv.addWidget(QLabel("Стенды:"))
            self.stand_combo = QComboBox()
            for name in self.bc.stands:
                self.stand_combo.addItem(name)
            lv.addWidget(self.stand_combo)

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

            # Дерево файлов — показывает папки стенда
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
            splitter.setSizes([220, 680])

            self.setStatusBar(QStatusBar())

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

        def _on_connect_done(self, ok, msg):
            self.btn_connect.setText("Подключиться")
            if ok:
                self.btn_connect.setEnabled(False)
                self.btn_disconnect.setEnabled(True)
                self.btn_browse.setEnabled(True)
                self.btn_browse_qconn.setEnabled(True)
                self._log(f"✓ {msg}")
                self.statusBar().showMessage(msg)
                # Автоматически открываем CVS-папку после подключения
                name = self.stand_combo.currentText()
                self.current_stand = name
                self.current_path  = self.bc.stands[name].cvs_path
                self._load_directory(name, self.current_path)
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
