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

# Добавляем корень проекта в путь
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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

from core.bench_connector import BenchConnector
from core.file_transfer import FileTransfer
from core.file_manager import FileManager
from core.process_manager import ProcessManager
from core.board_interface import BoardInterface
from logger.log_manager import LogManager
from gui.main_window import MainWindow


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
    print("\nДоступные объекты:")
    print("  bc    - BenchConnector (подключение к стендам)")
    print("  ft    - FileTransfer (загрузка/скачивание файлов)")
    print("  fm    - FileManager (работа с папками)")
    print("  pm    - ProcessManager (управление процессами)")
    print("  bi    - BoardInterface (работа с платами)")
    print("  logger - LogManager (логирование)")
    print("\nПримеры команд:")
    print("  bc.connect_to_stand('ГОЗ')")
    print("  bc.get_cvs_checksums('ГОЗ')")
    print("  bc.check_config_file('ГОЗ')")
    print("  pm.get_process_list('ГОЗ')")
    print("  bi.flash_firmware('ГОЗ', 'mpo')")
    print("\nДля выхода введите: exit")
    
    # Инициализируем остальные модули
    ft = FileTransfer(bc)
    fm = FileManager(bc)
    pm = ProcessManager(bc)
    bi = BoardInterface(bc)
    
    # Интерактивная сессия
    import code
    code.interact(
        local={
            'bc': bc,
            'ft': ft,
            'fm': fm,
            'pm': pm,
            'bi': bi,
            'logger': logger
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
        description="Bench Manager - управление стендами и платами",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py              # Запуск GUI
  python main.py --console    # Консольный режим
  python main.py --check      # Проверить доступность стендов
        """
    )
    
    parser.add_argument(
        '--console', '-c',
        action='store_true',
        help='Запуск в консольном режиме без GUI'
    )
    
    parser.add_argument(
        '--check',
        action='store_true',
        help='Проверить доступность всех стендов и выйти'
    )
    
    parser.add_argument(
        '--version', '-v',
        action='store_true',
        help='Показать версию'
    )
    
    args = parser.parse_args()
    
    # Версия
    if args.version:
        print("Bench Manager v1.0.0")
        print("Стенды: ГОЗ (192.168.243.248)")
        print("        Арктика (192.168.243.249)")
        print("        C1M (192.168.243.254)")
        print("        OrangePi (192.168.243.46)")
        return
    
    # Проверка стендов
    if args.check:
        print("=" * 60)
        print("ПРОВЕРКА ДОСТУПНОСТИ СТЕНДОВ")
        print("=" * 60)
        
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(3)
        
        for name, info in bc.get_all_stands_info().items():
            status = "ДОСТУПЕН" if info['status'] == 'online' else "НЕДОСТУПЕН"
            print(f"  {name:12} ({info['ip']:16}) : {status}")
        
        bc.stop_monitoring()
        return
    
    # Консольный режим
    if args.console:
        run_console()
        return
    
    # GUI режим (по умолчанию)
    try:
        run_gui()
    except Exception as e:
        print(f"Ошибка запуска GUI: {e}")
        print("Попробуйте консольный режим: python main.py --console")
        sys.exit(1)


if __name__ == "__main__":
    main()
