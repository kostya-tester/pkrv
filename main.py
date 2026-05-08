"""
Bench Manager - точка входа в приложение.
Запуск GUI или консольного режима.
"""

import sys
import os
import argparse

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

from core.bench_connector import BenchConnector
from core.file_transfer import FileTransfer
from core.file_manager import FileManager
from core.process_manager import ProcessManager
from core.board_interface import BoardInterface
from logger.log_manager import LogManager
from gui.main_window import MainWindow

# Путь к картинкам
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "images")


def setup_logging():
    """Настраивает логирование"""
    logger = LogManager()
    logger.setup(
        level="INFO",
        log_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "bench_manager.log")
    )
    return logger


def init_core_modules():
    """Инициализирует модули ядра"""
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("Bench Manager запускается...")
    logger.info("=" * 50)
    
    # Коннектор стендов
    bc = BenchConnector()
    bc.start_monitoring()
    logger.info("Мониторинг стендов запущен")
    
    # Файловый трансфер
    ft = FileTransfer(bc)
    
    # Файловый менеджер
    fm = FileManager(bc)
    
    # Менеджер процессов
    pm = ProcessManager(bc)
    
    # Интерфейс плат
    bi = BoardInterface(bc)
    
    logger.info("Все модули ядра инициализированы")
    
    return bc, ft, fm, pm, bi, logger


def run_gui():
    """Запускает графический интерфейс"""
    app = QApplication(sys.argv)
    app.setApplicationName("Bench Manager")
    
    # Иконка
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
        }
    """)
    
    # Создаем главное окно
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


def run_console():
    """Запускает консольный режим"""
    logger = setup_logging()
    
    print("=" * 60)
    print("BENCH MANAGER - КОНСОЛЬНЫЙ РЕЖИМ")
    print("=" * 60)
    
    bc = BenchConnector()
    bc.start_monitoring()
    
    print("\nДоступные стенды:")
    time.sleep(2)
    
    for name, info in bc.get_all_stands_info().items():
        status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name:12} | {info['ip']:16} | {status}")
    
    print("\nДля подключения используйте:")
    print("  bc.connect_to_stand('ГОЗ')  # запросит пароль")
    print("\nДоступные команды:")
    print("  bc.execute_command('ГОЗ', 'ls -la /home/pkrv/CVS')")
    print("  bc.get_cvs_checksums('ГОЗ')")
    print("  bc.check_config_file('ГОЗ')")
    print("  bc.archive_and_download_tmp('ГОЗ')")
    print("\nИнтерактивная консоль. Введите 'exit' для выхода.")
    
    # Интерактивный режим
    import code
    code.interact(
        local=locals(),
        banner="\nДоступные объекты: bc, logger"
    )
    
    bc.stop_monitoring()
    bc.disconnect_all()


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
        print("Стенды: ГОЗ, Арктика, C1M, OrangePi")
        return
    
    # Проверка стендов
    if args.check:
        print("Проверка доступности стендов...")
        
        bc = BenchConnector()
        bc.start_monitoring()
        time.sleep(3)
        
        print("\nРезультаты:")
        for name, info in bc.get_all_stands_info().items():
            status = "ДОСТУПЕН" if info['status'] == 'online' else "НЕДОСТУПЕН"
            print(f"  {name} ({info['ip']}): {status}")
        
        bc.stop_monitoring()
        return
    
    # Консольный режим
    if args.console:
        run_console()
        return
    
    # GUI режим (по умолчанию)
    run_gui()


if __name__ == "__main__":
    # Импорт time для задержки в проверке
    import time
    main()
