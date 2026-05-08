"""
Bench Manager - точка входа в приложение.
"""

import sys
import os
import time
import argparse

# ============================================================
# ОПРЕДЕЛЕНИЕ ПУТЕЙ
# ============================================================

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Добавляем все возможные пути
for folder in ['', 'core', 'logger', 'gui', 'scripts']:
    path = os.path.join(BASE_DIR, folder)
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

# ============================================================
# ИМПОРТЫ (прямые)
# ============================================================

# Импортируем модули напрямую
import bench_connector
import file_transfer
import file_manager
import process_manager
import board_interface
import log_manager
import main_window

BenchConnector = bench_connector.BenchConnector
FileTransfer = file_transfer.FileTransfer
FileManager = file_manager.FileManager
ProcessManager = process_manager.ProcessManager
BoardInterface = board_interface.BoardInterface
LogManager = log_manager.LogManager
MainWindow = main_window.MainWindow

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

# ============================================================
# ПУТИ
# ============================================================

if getattr(sys, 'frozen', False):
    IMAGES_DIR = os.path.join(sys._MEIPASS, "gui", "images")
else:
    IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
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
    
    logo_path = os.path.join(IMAGES_DIR, "logo.png")
    if os.path.exists(logo_path):
        app.setWindowIcon(QIcon(logo_path))
    
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', 'Arial', sans-serif;
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
    print("BENCH MANAGER - КОНСОЛЬНЫЙ РЕЖИМ")
    print("=" * 60)
    
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(3)
    
    print("\nДоступные стенды:")
    for name, info in bc.get_all_stands_info().items():
        status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name:12} | {info['ip']:16} | {status}")
    
    ft = FileTransfer(bc)
    fm = FileManager(bc)
    pm = ProcessManager(bc)
    bi = BoardInterface(bc)
    
    print("\nДоступные объекты: bc, ft, fm, pm, bi, logger")
    print("Введите exit для выхода")
    
    import code
    code.interact(local={'bc': bc, 'ft': ft, 'fm': fm, 'pm': pm, 'bi': bi, 'logger': logger})
    
    bc.stop_monitoring()
    bc.disconnect_all()


# ============================================================
# MAIN
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
    
    if args.check:
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(3)
        for name, info in bc.get_all_stands_info().items():
            status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
            print(f"  {name} ({info['ip']}): {status}")
        bc.stop_monitoring()
        return
    
    if args.console:
        run_console()
        return
    
    run_gui()


if __name__ == "__main__":
    main()
