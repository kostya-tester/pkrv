"""
Core модули Bench Manager.
Ядро системы для работы со стендами, файлами, процессами и платами.
"""

from core.bench_connector import BenchConnector, StandInfo
from core.file_transfer import FileTransfer
from core.file_manager import FileManager, FileInfo
from core.process_manager import ProcessManager, ProcessInfo
from core.board_interface import BoardInterface, BoardInfo

__all__ = [
    'BenchConnector',
    'StandInfo',
    'FileTransfer',
    'FileManager',
    'FileInfo',
    'ProcessManager',
    'ProcessInfo',
    'BoardInterface',
    'BoardInfo',
]

__version__ = '1.0.0'
