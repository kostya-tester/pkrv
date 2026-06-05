"""
Модуль логирования Bench Manager.
Поддерживает запись в файл, консоль с цветами, ротацию логов.
"""

from logger.log_manager import LogManager, setup, info, error, warning, debug, get_logger

__all__ = [
    'LogManager',
    'setup',
    'info',
    'error',
    'warning',
    'debug',
    'get_logger',
]
