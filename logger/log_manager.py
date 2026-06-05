"""
Модуль логирования приложения.
Поддерживает:
- Запись в файл с ротацией
- Вывод в консоль
- Разные уровни (DEBUG, INFO, WARNING, ERROR)
- Цветной вывод в консоль
- Синглтон (единый экземпляр на всё приложение)
"""

import os
import sys
import logging
import logging.handlers
from datetime import datetime
from typing import Optional


# ============================================================
# ЦВЕТА ДЛЯ КОНСОЛИ
# ============================================================

class LogColors:
    """ANSI-цвета для консольного вывода"""
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    
    # Цвета по уровням
    LEVEL_COLORS = {
        'DEBUG': GRAY,
        'INFO': GREEN,
        'WARNING': YELLOW,
        'ERROR': RED,
        'CRITICAL': MAGENTA + BOLD
    }
    
    @classmethod
    def colorize(cls, text: str, level: str) -> str:
        """Окрашивает текст в зависимости от уровня"""
        color = cls.LEVEL_COLORS.get(level, cls.RESET)
        return f"{color}{text}{cls.RESET}"


# ============================================================
# ФОРМАТТЕРЫ
# ============================================================

class ColoredFormatter(logging.Formatter):
    """Форматтер с цветным выводом для консоли"""
    
    def format(self, record):
        # Добавляем цвет к уровню
        levelname = record.levelname
        record.levelname = LogColors.colorize(f"{levelname:8}", levelname)
        
        # Добавляем цвет к имени модуля
        if hasattr(record, 'stand_name'):
            record.name = LogColors.colorize(record.name, 'CYAN')
        
        return super().format(record)


class FileFormatter(logging.Formatter):
    """Форматтер для записи в файл (без цветов)"""
    pass


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================

class LogManager:
    """
    Менеджер логирования (синглтон).
    
    Использование:
        logger = LogManager()
        logger.setup(level="DEBUG", log_file="logs/app.log")
        logger.info("Сообщение")
        logger.error("Ошибка")
        logger.warning("Предупреждение")
        logger.debug("Отладка")
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.logger = logging.getLogger('BenchManager')
        self.logger.setLevel(logging.DEBUG)
        
        self.log_file = None
        self.log_level = "INFO"
        self.console_handler = None
        self.file_handler = None
        self._handlers_configured = False
        
        self._initialized = True
    
    # ============================================================
    # НАСТРОЙКА
    # ============================================================
    
    def setup(self, level: str = "INFO", log_file: str = None,
              console: bool = True, max_size: int = 10 * 1024 * 1024,
              backup_count: int = 5, use_colors: bool = True):
        """
        Настраивает логирование.
        
        Args:
            level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
            log_file: Путь к файлу лога (если None - только консоль)
            console: Выводить в консоль
            max_size: Максимальный размер файла (байт)
            backup_count: Количество файлов ротации
            use_colors: Использовать цвета в консоли
        """
        self.log_level = level.upper()
        self.log_file = log_file
        
        # Устанавливаем уровень
        self.logger.setLevel(getattr(logging, self.log_level, logging.INFO))
        
        # Удаляем старые обработчики
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Консольный обработчик
        if console:
            self.console_handler = logging.StreamHandler(sys.stdout)
            self.console_handler.setLevel(getattr(logging, self.log_level))
            
            if use_colors:
                console_format = '%(asctime)s %(levelname)s %(message)s'
                self.console_handler.setFormatter(
                    ColoredFormatter(console_format, datefmt='%H:%M:%S')
                )
            else:
                console_format = '%(asctime)s [%(levelname)-8s] %(message)s'
                self.console_handler.setFormatter(
                    logging.Formatter(console_format, datefmt='%H:%M:%S')
                )
            
            self.logger.addHandler(self.console_handler)
        
        # Файловый обработчик
        if log_file:
            self._setup_file_handler(log_file, max_size, backup_count)
        
        self._handlers_configured = True
        
        self.info("=" * 50)
        self.info("Система логирования запущена")
        self.info(f"Уровень: {self.log_level}")
        if log_file:
            self.info(f"Файл: {os.path.abspath(log_file)}")
        self.info("=" * 50)
    
    def _setup_file_handler(self, log_file: str, max_size: int, backup_count: int):
        """Настраивает запись в файл с ротацией"""
        try:
            # Создаем папку для логов
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            
            # Ротируемый файловый обработчик
            self.file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_size,
                backupCount=backup_count,
                encoding='utf-8'
            )
            self.file_handler.setLevel(logging.DEBUG)
            
            file_format = '%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s'
            self.file_handler.setFormatter(
                FileFormatter(file_format, datefmt='%Y-%m-%d %H:%M:%S')
            )
            
            self.logger.addHandler(self.file_handler)
            
        except Exception as e:
            print(f"[LOG ERROR] Не удалось настроить файловый лог: {e}")
    
    # ============================================================
    # МЕТОДЫ ЛОГИРОВАНИЯ
    # ============================================================
    
    def info(self, message: str, stand: str = None):
        """Информационное сообщение"""
        extra = {'stand_name': stand} if stand else {}
        self.logger.info(message, extra=extra)
    
    def error(self, message: str, stand: str = None):
        """Сообщение об ошибке"""
        extra = {'stand_name': stand} if stand else {}
        self.logger.error(message, extra=extra)
    
    def warning(self, message: str, stand: str = None):
        """Предупреждение"""
        extra = {'stand_name': stand} if stand else {}
        self.logger.warning(message, extra=extra)
    
    def debug(self, message: str, stand: str = None):
        """Отладочное сообщение (только при DEBUG)"""
        extra = {'stand_name': stand} if stand else {}
        self.logger.debug(message, extra=extra)
    
    def critical(self, message: str, stand: str = None):
        """Критическая ошибка"""
        extra = {'stand_name': stand} if stand else {}
        self.logger.critical(message, extra=extra)
    
    # ============================================================
    # СПЕЦИАЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def section(self, title: str):
        """Выводит заголовок секции"""
        self.info("")
        self.info("=" * 60)
        self.info(f"  {title}")
        self.info("=" * 60)
    
    def result(self, success: bool, message: str):
        """Выводит результат операции"""
        if success:
            self.info(f"[OK] {message}")
        else:
            self.error(f"[FAIL] {message}")
    
    def table(self, headers: list, rows: list):
        """Выводит таблицу в лог"""
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))
        
        # Заголовок
        header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        self.info(header_line)
        self.info("-" * len(header_line))
        
        # Данные
        for row in rows:
            line = " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
            self.info(line)
    
    # ============================================================
    # УПРАВЛЕНИЕ
    # ============================================================
    
    def set_level(self, level: str):
        """Изменяет уровень логирования на лету"""
        self.log_level = level.upper()
        self.logger.setLevel(getattr(logging, self.log_level))
        
        if self.console_handler:
            self.console_handler.setLevel(getattr(logging, self.log_level))
        
        self.info(f"Уровень логирования изменен на: {self.log_level}")
    
    def get_log_file(self) -> Optional[str]:
        """Возвращает путь к файлу лога"""
        return self.log_file
    
    def get_log_size(self) -> int:
        """Возвращает размер файла лога в байтах"""
        if self.log_file and os.path.exists(self.log_file):
            return os.path.getsize(self.log_file)
        return 0
    
    def clear_log(self):
        """Очищает файл лога"""
        if self.log_file and os.path.exists(self.log_file):
            open(self.log_file, 'w').close()
            self.info("Файл лога очищен")
    
    def get_recent_logs(self, lines: int = 50) -> list:
        """Возвращает последние строки лога"""
        if not self.log_file or not os.path.exists(self.log_file):
            return []
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        
        return all_lines[-lines:]


# ============================================================
# БЫСТРЫЙ ДОСТУП (для совместимости)
# ============================================================

# Создаем глобальный экземпляр
_default_logger = LogManager()

def setup(level="INFO", log_file=None):
    _default_logger.setup(level, log_file)

def info(msg, stand=None):
    _default_logger.info(msg, stand)

def error(msg, stand=None):
    _default_logger.error(msg, stand)

def warning(msg, stand=None):
    _default_logger.warning(msg, stand)

def debug(msg, stand=None):
    _default_logger.debug(msg, stand)

def get_logger() -> LogManager:
    return _default_logger


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ LOG MANAGER")
    print("=" * 60)
    
    # Тест 1: Только консоль
    print("\n1. Только консоль:")
    logger = LogManager()
    logger.setup(level="DEBUG")
    logger.debug("Отладочное сообщение")
    logger.info("Информационное сообщение")
    logger.warning("Предупреждение")
    logger.error("Сообщение об ошибке")
    
    # Тест 2: С файлом
    print("\n2. С записью в файл:")
    logger.setup(level="DEBUG", log_file="logs/test.log")
    logger.section("Тестовая секция")
    logger.info("Сообщение 1")
    logger.info("Сообщение 2")
    logger.result(True, "Операция успешна")
    logger.result(False, "Операция провалена")
    
    # Тест 3: Таблица
    print("\n3. Таблица:")
    logger.table(
        ["Стенд", "IP", "Статус"],
        [
            ["ГОЗ", "192.168.243.248", "ONLINE"],
            ["Арктика", "192.168.243.249", "OFFLINE"],
            ["C1M", "192.168.243.254", "ONLINE"],
            ["OrangePi", "192.168.243.46", "ONLINE"],
        ]
    )
    
    # Тест 4: Быстрый доступ
    print("\n4. Быстрый доступ:")
    setup(level="INFO", log_file="logs/quick.log")
    info("Быстрое сообщение")
    warning("Быстрое предупреждение", stand="ГОЗ")
    error("Быстрая ошибка")
    
    print("\nТест завершен!")
