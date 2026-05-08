"""
Bench Manager - точка входа.
"""

import sys
import os
import time
import argparse
import importlib
import importlib.util

# ============================================================
# ПУТИ
# ============================================================

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# ЗАГРУЗКА МОДУЛЕЙ ВРУЧНУЮ
# ============================================================

def load_module(name: str, folder: str):
    """Загружает модуль из указанной папки"""
    path = os.path.join(BASE_DIR, folder, f"{name}.py")
    
    if not os.path.exists(path):
        # Пробуем без папки
        path = os.path.join(BASE_DIR, f"{name}.py")
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл не найден: {path}")
    
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Загружаем модули
log_manager = load_module("log_manager", "logger")
LogManager = log_manager.LogManager

bench_connector = load_module("bench_connector", "core")
BenchConnector = bench_connector.BenchConnector

file_transfer = load_module("file_transfer", "core")
FileTransfer = file_transfer.FileTransfer

file_manager = load_module("file_manager", "core")
FileManager = file_manager.FileManager

process_manager = load_module("process_manager", "core")
ProcessManager = process_manager.ProcessManager

board_interface = load_module("board_interface", "core")
BoardInterface = board_interface.BoardInterface

main_window = load_module("main_window", "gui")
MainWindow = main_window.MainWindow

# PyQt5
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

# ============================================================
# ПУТИ К КАРТИНКАМ
# ============================================================

if getattr(sys, 'frozen', False):
    IMAGES_DIR = os.path.join(sys._MEIPASS, "gui", "images")
else:
    IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")

# ============================================================
# ЛОГГЕР
# ============================================================

def setup_logging():
    logger = LogManager()
    log_file = os.path.join(BASE_DIR, "logs", "bench_manager.log")
    logger.setup(level="INFO", log_file=log_file)
    return logger

# ============================================================
# GUI
# ============================================================

def run_gui():
    app = QApplication(sys.argv)
    app.setApplicationName("Bench Manager")
    
    logo = os.path.join(IMAGES_DIR, "logo.png")
    if os.path.exists(logo):
        app.setWindowIcon(QIcon(logo))
    
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 12px;
        }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

# ============================================================
# КОНСОЛЬ
# ============================================================

def run_console():
    logger = setup_logging()
    print("=" * 60)
    print("BENCH MANAGER - КОНСОЛЬ")
    print("=" * 60)
    
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(3)
    
    for name, info in bc.get_all_stands_info().items():
        s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name:12} | {info['ip']:16} | {s}")
    
    ft = FileTransfer(bc)
    fm = FileManager(bc)
    pm = ProcessManager(bc)
    bi = BoardInterface(bc)
    
    print("\nОбъекты: bc, ft, fm, pm, bi, logger")
    
    import code
    code.interact(local={'bc': bc, 'ft': ft, 'fm': fm, 'pm': pm, 'bi': bi, 'logger': logger})
    
    bc.stop_monitoring()
    bc.disconnect_all()

# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--console', '-c', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--version', '-v', action='store_true')
    
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v1.0.0")
        return
    
    if args.check:
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(3)
        for name, info in bc.get_all_stands_info().items():
            s = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name} ({info['ip']}): {s}")
        bc.stop_monitoring()
        return
    
    if args.console:
        run_console()
        return
    
    run_gui()

if __name__ == "__main__":
    main()
