"""
Bench Manager - точка входа в приложение.
Запуск GUI или консольного режима.
"""

import sys
import os
import time
import argparse

# ============================================================
# ОПРЕДЕЛЕНИЕ ПУТЕЙ
# ============================================================

if getattr(sys, 'frozen', False):
    # Запуск из EXE (PyInstaller)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Запуск из Python
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Добавляем ВСЕ нужные папки в sys.path
paths_to_add = [
    BASE_DIR,
    os.path.join(BASE_DIR, 'core'),
    os.path.join(BASE_DIR, 'logger'),
    os.path.join(BASE_DIR, 'gui'),
]

for path in paths_to_add:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

# Путь к картинкам
if getattr(sys, 'frozen', False):
    IMAGES_DIR = os.path.join(sys._MEIPASS, "gui", "images")
    SCRIPTS_DIR = os.path.join(sys._MEIPASS, "scripts")
    CONFIG_FILE = os.path.join(sys._MEIPASS, "config.yaml")
else:
    IMAGES_DIR = os.path.join(BASE_DIR, "gui", "images")
    SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
    CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")


# ============================================================
# ИМПОРТЫ
# ============================================================

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

# Импортируем модули ядра через importlib для надежности
import importlib

def safe_import(module_name: str):
    """Безопасный импорт модуля с подробной ошибкой"""
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        print(f"ОШИБКА ИМПОРТА: {module_name}")
        print(f"  Путь: {sys.path}")
        print(f"  Ошибка: {e}")
        raise

bench_connector = safe_import('bench_connector')
BenchConnector = bench_connector.BenchConnector

file_transfer = safe_import('file_transfer')
FileTransfer = file_transfer.FileTransfer

file_manager = safe_import('file_manager')
FileManager = file_manager.FileManager

process_manager = safe_import('process_manager')
ProcessManager = process_manager.ProcessManager

board_interface = safe_import('board_interface')
BoardInterface = board_interface.BoardInterface

log_manager = safe_import('log_manager')
LogManager = log_manager.LogManager

gui_main = safe_import('main_window')
MainWindow = gui_main.MainWindow


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================

def setup_logging():
    """Настраивает логирование"""
    logger = LogManager()
    
    log_file = os.path.join(BASE_DIR, "logs", "bench_manager.log")
    
    logger.setup(
        level="INFO",
        log_file=log_file
    )
    return logger


# ============================================================
# ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ
# ============================================================

def init_core_modules():
    """Инициализирует модули ядра"""
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("Bench Manager запускается...")
    logger.info(f"Версия: 1.0.0")
    logger.info(f"Папка: {BASE_DIR}")
    logger.info("=" * 50)
    
    # Коннектор стендов
    bc = BenchConnector()
    bc.start_monitoring()
    logger.info("Мониторинг стендов запущен")
    
    # Файловый трансфер
    ft = FileTransfer(bc)
    logger.info("FileTransfer инициализирован")
    
    # Файловый менеджер
    fm = FileManager(bc)
    logger.info("FileManager инициализирован")
    
    # Менеджер процессов
    pm = ProcessManager(bc)
    logger.info("ProcessManager инициализирован")
    
    # Интерфейс плат
    bi = BoardInterface(bc)
    logger.info("BoardInterface инициализирован")
    
    logger.info("Все модули ядра готовы")
    
    return bc, ft, fm, pm, bi, logger


# ============================================================
# GUI РЕЖИМ
# ============================================================

def run_gui():
    """Запускает графический интерфейс"""
    app = QApplication(sys.argv)
    app.setApplicationName("Bench Manager")
    app.setApplicationVersion("1.0.0")
    
    # Иконка приложения
    logo_path = os.path.join(IMAGES_DIR, "logo.png")
    if os.path.exists(logo_path):
        app.setWindowIcon(QIcon(logo_path))
    
    # Темная тема
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', 'Arial', sans-serif;
            font-size: 12px;
        }
        QToolTip {
            background-color: #2a2a4a;
            color: #e0e0e0;
            border: 1px solid #4a4a8a;
            padding: 5px;
            border-radius: 3px;
        }
    """)
    
    # Создаем главное окно
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


# ============================================================
# КОНСОЛЬНЫЙ РЕЖИМ
# ============================================================

def run_console():
    """Запускает консольный режим"""
    logger = setup_logging()
    
    print("=" * 60)
    print("BENCH MANAGER - КОНСОЛЬНЫЙ РЕЖИМ")
    print("=" * 60)
    
    bc = BenchConnector()
    bc.start_monitoring()
    
    print("\nПоиск стендов...")
    time.sleep(3)
    
    print("\nДоступные стенды:")
    for name, info in bc.get_all_stands_info().items():
        status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name:12} | {info['ip']:16} | {status}")
    
    print("\n" + "=" * 60)
    print("Интерактивная консоль")
    print("=" * 60)
    print("\nДоступные объекты: bc, ft, fm, pm, bi, logger")
    print("Для выхода введите: exit")
    
    ft = FileTransfer(bc)
    fm = FileManager(bc)
    pm = ProcessManager(bc)
    bi = BoardInterface(bc)
    
    import code
    code.interact(
        local={
            'bc': bc, 'ft': ft, 'fm': fm,
            'pm': pm, 'bi': bi, 'logger': logger
        },
        banner=""
    )
    
    bc.stop_monitoring()
    bc.disconnect_all()
    logger.info("Приложение закрыто")


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description="Bench Manager - управление стендами и платами"
    )
    
    parser.add_argument('--console', '-c', action='store_true',
                        help='Запуск в консольном режиме')
    parser.add_argument('--check', action='store_true',
                        help='Проверить доступность стендов')
    parser.add_argument('--version', '-v', action='store_true',
                        help='Показать версию')
    
    args = parser.parse_args()
    
    if args.version:
        print("Bench Manager v1.0.0")
        print("Стенды: ГОЗ, Арктика, C1M, OrangePi")
        return
    
    if args.check:
        print("Проверка доступности стендов...")
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(3)
        
        for name, info in bc.get_all_stands_info().items():
            status = "ДОСТУПЕН" if info['status'] == 'online' else "НЕДОСТУПЕН"
            print(f"  {name:12} ({info['ip']:16}) : {status}")
        
        bc.stop_monitoring()
        return
    
    if args.console:
        run_console()
        return
    
    # GUI режим
    try:
        run_gui()
    except Exception as e:
        print(f"Ошибка запуска GUI: {e}")
        print("Попробуйте: python main.py --console")
        sys.exit(1)


if __name__ == "__main__":
    main()
