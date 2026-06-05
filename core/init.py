"""
Core модули Bench Manager.
Ядро системы для работы со стендами, файлами, процессами, платами и Jenkins.
"""

from core.bench_connector import BenchConnector, StandInfo
from core.file_transfer import FileTransfer
from core.file_manager import FileManager, FileInfo
from core.process_manager import ProcessManager, ProcessInfo
from core.board_interface import BoardInterface, BoardInfo

# Jenkins модули
from core.jenkins_manager import JenkinsManager

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
    'JenkinsManager',
]

__version__ = '1.0.0'
