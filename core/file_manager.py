"""
Модуль работы с файловой системой.
Локальные и удаленные (через BenchConnector) операции с файлами.
Просмотр, навигация, копирование, перемещение, удаление, фильтрация.
"""

import sys
import os
import time
import shutil
import fnmatch
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.bench_connector import BenchConnector, LogManager, OS_TYPE
except ImportError:
    from bench_connector import BenchConnector, LogManager, OS_TYPE


class FileInfo:
    """Информация о файле или папке"""
    
    def __init__(self, name: str, path: str, is_dir: bool = False,
                 size: int = 0, modified: str = "", permissions: str = "",
                 owner: str = "", group: str = ""):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.size_str = self._format_size(size)
        self.modified = modified
        self.permissions = permissions
        self.owner = owner
        self.group = group
        self.extension = os.path.splitext(name)[1].lower() if not is_dir else ""
        self.type = self._detect_type()
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    
    def _detect_type(self) -> str:
        if self.is_dir:
            return "folder"
        
        ext_map = {
            '.py': 'python', '.js': 'javascript', '.html': 'html',
            '.css': 'css', '.json': 'json', '.xml': 'xml',
            '.txt': 'text', '.log': 'log', '.cfg': 'config',
            '.conf': 'config', '.ini': 'config', '.yaml': 'yaml',
            '.yml': 'yaml', '.md': 'markdown', '.sh': 'shell',
            '.bash': 'shell', '.bat': 'batch', '.exe': 'executable',
            '.dll': 'library', '.so': 'library', '.a': 'library',
            '.tar': 'archive', '.gz': 'archive', '.zip': 'archive',
            '.7z': 'archive', '.rar': 'archive', '.bz2': 'archive',
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image',
            '.gif': 'image', '.bmp': 'image', '.svg': 'image',
            '.mp4': 'video', '.avi': 'video', '.mkv': 'video',
            '.mp3': 'audio', '.wav': 'audio', '.ogg': 'audio',
            '.pdf': 'document', '.doc': 'document', '.docx': 'document',
            '.xls': 'spreadsheet', '.xlsx': 'spreadsheet',
            '.c': 'source', '.cpp': 'source', '.h': 'source',
            '.java': 'source', '.go': 'source', '.rs': 'source',
        }
        return ext_map.get(self.extension, "file")
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'path': self.path,
            'is_dir': self.is_dir,
            'size': self.size,
            'size_str': self.size_str,
            'modified': self.modified,
            'permissions': self.permissions,
            'owner': self.owner,
            'group': self.group,
            'extension': self.extension,
            'type': self.type
        }
    
    def __repr__(self):
        type_icon = "[DIR]" if self.is_dir else "[FILE]"
        return f"{type_icon} {self.name} ({self.size_str})"


class FileManager:
    """
    Менеджер файловой системы.
    Работает локально и удаленно через BenchConnector.
    
    Возможности:
    - Просмотр содержимого папок
    - Навигация по файловой системе
    - Информация о файлах (размер, дата, права)
    - Копирование, перемещение, удаление
    - Фильтрация по расширению и маске
    - Поиск файлов
    - Сравнение директорий
    """
    
    def __init__(self, bench_connector: BenchConnector = None):
        """
        Args:
            bench_connector: Экземпляр BenchConnector (опционально, для удаленных операций)
        """
        self.bc = bench_connector
        self.logger = LogManager()
        self.logger.setup(level="INFO")
        
        # Текущая рабочая директория (локальная)
        self.local_cwd = os.getcwd()
        
        # Текущая директория на каждом стенде
        self.remote_cwd: Dict[str, str] = {}
        
        # История навигации
        self.local_history: List[str] = [self.local_cwd]
        self.remote_history: Dict[str, List[str]] = {}
        
        # Избранные папки
        self.favorites: List[str] = []
    
    # ============================================================
    # ЛОКАЛЬНЫЕ ОПЕРАЦИИ
    # ============================================================
    
    def list_local(self, path: str = None, pattern: str = "*",
                   show_hidden: bool = False, sort_by: str = "name",
                   reverse: bool = False) -> List[FileInfo]:
        """
        Список файлов в локальной папке.
        
        Args:
            path: Путь к папке (если None - текущая)
            pattern: Фильтр по маске (*.py, *.txt, data*)
            show_hidden: Показывать скрытые файлы
            sort_by: Сортировка (name, size, date, type)
            reverse: Обратный порядок
            
        Returns:
            Список FileInfo
        """
        if path is None:
            path = self.local_cwd
        
        if not os.path.exists(path):
            self.logger.error(f"Путь не существует: {path}")
            return []
        
        if not os.path.isdir(path):
            self.logger.error(f"Это не директория: {path}")
            return []
        
        items = []
        
        try:
            for entry in os.scandir(path):
                # Скрытые файлы
                if not show_hidden and entry.name.startswith('.'):
                    continue
                
                # Фильтр по маске
                if pattern != "*" and not fnmatch.fnmatch(entry.name, pattern):
                    continue
                
                stat = entry.stat()
                
                file_info = FileInfo(
                    name=entry.name,
                    path=entry.path,
                    is_dir=entry.is_dir(),
                    size=stat.st_size if not entry.is_dir() else 0,
                    modified=datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    permissions=self._format_permissions(stat.st_mode)
                )
                items.append(file_info)
        except PermissionError:
            self.logger.error(f"Нет доступа к папке: {path}")
        except Exception as e:
            self.logger.error(f"Ошибка чтения папки: {e}")
        
        # Сортировка
        if sort_by == "name":
            items.sort(key=lambda x: x.name.lower(), reverse=reverse)
        elif sort_by == "size":
            items.sort(key=lambda x: x.size, reverse=not reverse)
        elif sort_by == "date":
            items.sort(key=lambda x: x.modified, reverse=not reverse)
        elif sort_by == "type":
            items.sort(key=lambda x: (x.is_dir, x.extension), reverse=reverse)
        
        # Папки первыми
        dirs = [i for i in items if i.is_dir]
        files = [i for i in items if not i.is_dir]
        
        return dirs + files
    
    def list_remote(self, stand_name: str, path: str = None,
                    pattern: str = "*", show_hidden: bool = False) -> List[FileInfo]:
        """
        Список файлов на удаленном стенде.
        
        Args:
            stand_name: Имя стенда
            path: Путь на стенде
            pattern: Фильтр по маске
            show_hidden: Показывать скрытые файлы
            
        Returns:
            Список FileInfo
        """
        if not self.bc:
            self.logger.error("BenchConnector не настроен")
            return []
        
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к {stand_name}")
            return []
        
        if path is None:
            if stand_name not in self.remote_cwd:
                self.remote_cwd[stand_name] = "/home/pkrv"
            path = self.remote_cwd[stand_name]
        
        command = f"ls -la --time-style=long-iso {path} 2>/dev/null"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if not success:
            self.logger.error(f"Ошибка чтения папки: {stderr}")
            return []
        
        items = []
        
        for line in stdout.strip().split('\n'):
            if not line.startswith('total') and line.strip():
                parts = line.split()
                if len(parts) >= 8:
                    name = ' '.join(parts[7:])
                    
                    # Пропускаем . и ..
                    if name in ['.', '..']:
                        continue
                    
                    # Скрытые файлы
                    if not show_hidden and name.startswith('.'):
                        continue
                    
                    # Фильтр по маске
                    if pattern != "*" and not fnmatch.fnmatch(name, pattern):
                        continue
                    
                    is_dir = line.startswith('d')
                    
                    file_info = FileInfo(
                        name=name,
                        path=f"{path.rstrip('/')}/{name}",
                        is_dir=is_dir,
                        size=int(parts[4]) if parts[4].isdigit() and not is_dir else 0,
                        modified=f"{parts[5]} {parts[6]}" if len(parts) > 6 else "",
                        permissions=parts[0] if parts else "",
                        owner=parts[2] if len(parts) > 2 else "",
                        group=parts[3] if len(parts) > 3 else ""
                    )
                    items.append(file_info)
        
        # Сортировка: папки первыми, потом по имени
        items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
        
        return items
    
    # ============================================================
    # НАВИГАЦИЯ
    # ============================================================
    
    def cd_local(self, path: str) -> bool:
        """Сменить локальную директорию"""
        if path == "..":
            new_path = os.path.dirname(self.local_cwd)
        elif path == "~":
            new_path = os.path.expanduser("~")
        elif os.path.isabs(path):
            new_path = path
        else:
            new_path = os.path.join(self.local_cwd, path)
        
        new_path = os.path.normpath(new_path)
        
        if os.path.isdir(new_path):
            self.local_history.append(self.local_cwd)
            self.local_cwd = new_path
            self.logger.info(f"Локальная директория: {new_path}")
            return True
        
        self.logger.error(f"Директория не найдена: {new_path}")
        return False
    
    def cd_remote(self, stand_name: str, path: str) -> bool:
        """Сменить директорию на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        current = self.remote_cwd.get(stand_name, "/")
        
        if path == "..":
            new_path = os.path.dirname(current) if current != "/" else "/"
        elif path == "~":
            stand_config = self.bc.get_stand_config(stand_name)
            new_path = f"/home/{stand_config.get('username', 'pkrv')}"
        elif path.startswith('/'):
            new_path = path
        else:
            new_path = f"{current.rstrip('/')}/{path}"
        
        # Проверяем существование
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"test -d {new_path} && echo 'OK'"
        )
        
        if success and 'OK' in stdout:
            if stand_name not in self.remote_history:
                self.remote_history[stand_name] = []
            self.remote_history[stand_name].append(current)
            self.remote_cwd[stand_name] = new_path
            self.logger.info(f"Удаленная директория [{stand_name}]: {new_path}")
            return True
        
        return False
    
    def get_local_cwd(self) -> str:
        """Возвращает текущую локальную директорию"""
        return self.local_cwd
    
    def get_remote_cwd(self, stand_name: str) -> str:
        """Возвращает текущую директорию на стенде"""
        return self.remote_cwd.get(stand_name, "/")
    
    def go_back_local(self) -> bool:
        """Вернуться в предыдущую локальную директорию"""
        if len(self.local_history) > 1:
            self.local_cwd = self.local_history.pop()
            return True
        return False
    
    def go_back_remote(self, stand_name: str) -> bool:
        """Вернуться в предыдущую директорию на стенде"""
        if stand_name in self.remote_history and self.remote_history[stand_name]:
            self.remote_cwd[stand_name] = self.remote_history[stand_name].pop()
            return True
        return False
    
    # ============================================================
    # ИНФОРМАЦИЯ О ФАЙЛЕ
    # ============================================================
    
    def get_file_info_local(self, path: str) -> Optional[FileInfo]:
        """Получает информацию о локальном файле"""
        if not os.path.exists(path):
            return None
        
        stat = os.stat(path)
        is_dir = os.path.isdir(path)
        
        return FileInfo(
            name=os.path.basename(path),
            path=os.path.abspath(path),
            is_dir=is_dir,
            size=stat.st_size if not is_dir else 0,
            modified=datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            permissions=self._format_permissions(stat.st_mode)
        )
    
    def get_file_info_remote(self, stand_name: str, path: str) -> Optional[FileInfo]:
        """Получает информацию о файле на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return None
        
        command = f"ls -lad --time-style=long-iso {path} 2>/dev/null"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if not success or not stdout.strip():
            return None
        
        parts = stdout.strip().split()
        if len(parts) < 8:
            return None
        
        is_dir = stdout.startswith('d')
        name = os.path.basename(path)
        
        return FileInfo(
            name=name,
            path=path,
            is_dir=is_dir,
            size=int(parts[4]) if parts[4].isdigit() and not is_dir else 0,
            modified=f"{parts[5]} {parts[6]}",
            permissions=parts[0],
            owner=parts[2],
            group=parts[3]
        )
    
    # ============================================================
    # ОПЕРАЦИИ С ФАЙЛАМИ (ЛОКАЛЬНЫЕ)
    # ============================================================
    
    def copy_local(self, source: str, destination: str) -> bool:
        """Копирует файл или папку локально"""
        try:
            if os.path.isdir(source):
                shutil.copytree(source, destination)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)
            self.logger.info(f"Скопировано: {source} -> {destination}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка копирования: {e}")
            return False
    
    def move_local(self, source: str, destination: str) -> bool:
        """Перемещает файл или папку локально"""
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.move(source, destination)
            self.logger.info(f"Перемещено: {source} -> {destination}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка перемещения: {e}")
            return False
    
    def delete_local(self, path: str) -> bool:
        """Удаляет файл или папку локально"""
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.logger.info(f"Удалено: {path}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка удаления: {e}")
            return False
    
    def create_folder_local(self, path: str) -> bool:
        """Создает папку локально"""
        try:
            os.makedirs(path, exist_ok=True)
            self.logger.info(f"Создана папка: {path}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка создания папки: {e}")
            return False
    
    # ============================================================
    # ОПЕРАЦИИ С ФАЙЛАМИ (УДАЛЕННЫЕ)
    # ============================================================
    
    def copy_remote(self, stand_name: str, source: str, destination: str) -> bool:
        """Копирует файл/папку на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        command = f"cp -r {source} {destination} 2>&1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success:
            self.logger.info(f"[{stand_name}] Скопировано: {source} -> {destination}")
        else:
            self.logger.error(f"[{stand_name}] Ошибка копирования: {stderr}")
        
        return success
    
    def move_remote(self, stand_name: str, source: str, destination: str) -> bool:
        """Перемещает файл/папку на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        command = f"mv {source} {destination} 2>&1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success:
            self.logger.info(f"[{stand_name}] Перемещено: {source} -> {destination}")
        
        return success
    
    def delete_remote(self, stand_name: str, path: str) -> bool:
        """Удаляет файл/папку на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        command = f"rm -rf {path} 2>&1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success:
            self.logger.info(f"[{stand_name}] Удалено: {path}")
        
        return success
    
    def create_folder_remote(self, stand_name: str, path: str) -> bool:
        """Создает папку на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        command = f"mkdir -p {path} 2>&1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success:
            self.logger.info(f"[{stand_name}] Создана папка: {path}")
        
        return success
    
    # ============================================================
    # ПОИСК ФАЙЛОВ
    # ============================================================
    
    def search_local(self, start_path: str, pattern: str = "*",
                     max_depth: int = None, min_size: int = None,
                     max_size: int = None, modified_after: str = None) -> List[FileInfo]:
        """
        Поиск файлов локально.
        
        Args:
            start_path: Начальная папка
            pattern: Маска файла
            max_depth: Максимальная глубина поиска
            min_size: Минимальный размер (байт)
            max_size: Максимальный размер (байт)
            modified_after: Дата изменения (YYYY-MM-DD)
            
        Returns:
            Список найденных файлов
        """
        results = []
        
        for root, dirs, files in os.walk(start_path):
            # Глубина
            if max_depth is not None:
                depth = root[len(start_path):].count(os.sep)
                if depth > max_depth:
                    dirs.clear()
                    continue
            
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    full_path = os.path.join(root, filename)
                    stat = os.stat(full_path)
                    
                    # Фильтр по размеру
                    if min_size and stat.st_size < min_size:
                        continue
                    if max_size and stat.st_size > max_size:
                        continue
                    
                    # Фильтр по дате
                    if modified_after:
                        file_date = datetime.fromtimestamp(stat.st_mtime)
                        filter_date = datetime.strptime(modified_after, '%Y-%m-%d')
                        if file_date < filter_date:
                            continue
                    
                    file_info = FileInfo(
                        name=filename,
                        path=full_path,
                        is_dir=False,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    )
                    results.append(file_info)
        
        return results
    
    def search_remote(self, stand_name: str, start_path: str,
                      pattern: str = "*", max_depth: int = 3) -> List[FileInfo]:
        """Поиск файлов на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return []
        
        command = f"find {start_path} -maxdepth {max_depth} -name '{pattern}' -type f -ls 2>/dev/null"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if not success:
            return []
        
        results = []
        for line in stdout.strip().split('\n'):
            if line.strip():
                parts = line.split()
                if len(parts) >= 11:
                    name = ' '.join(parts[10:])
                    results.append(FileInfo(
                        name=os.path.basename(name),
                        path=name,
                        is_dir=False,
                        size=int(parts[6]) if parts[6].isdigit() else 0,
                        modified=f"{parts[7]} {parts[8]} {parts[9]}",
                        permissions=parts[2]
                    ))
        
        return results
    
    # ============================================================
    # ФИЛЬТРАЦИЯ ПО РАСШИРЕНИЮ
    # ============================================================
    
    def filter_by_extension(self, files: List[FileInfo], 
                            extensions: List[str]) -> List[FileInfo]:
        """Фильтрует файлы по расширениям"""
        exts = [e.lower() if e.startswith('.') else f'.{e.lower()}' for e in extensions]
        return [f for f in files if f.extension in exts]
    
    def filter_by_type(self, files: List[FileInfo], file_type: str) -> List[FileInfo]:
        """Фильтрует файлы по типу (python, image, archive, config...)"""
        return [f for f in files if f.type == file_type]
    
    def group_by_extension(self, files: List[FileInfo]) -> Dict[str, List[FileInfo]]:
        """Группирует файлы по расширениям"""
        groups = {}
        for f in files:
            ext = f.extension or "(no extension)"
            if ext not in groups:
                groups[ext] = []
            groups[ext].append(f)
        return groups
    
    # ============================================================
    # СРАВНЕНИЕ ДИРЕКТОРИЙ
    # ============================================================
    
    def compare_directories(self, path1: str, path2: str) -> Dict:
        """
        Сравнивает две локальные директории.
        
        Returns:
            Словарь с тремя списками: only_in_1, only_in_2, different
        """
        if not os.path.isdir(path1) or not os.path.isdir(path2):
            return {}
        
        files1 = {f.name: f for f in self.list_local(path1)}
        files2 = {f.name: f for f in self.list_local(path2)}
        
        names1 = set(files1.keys())
        names2 = set(files2.keys())
        
        only_in_1 = [files1[n] for n in (names1 - names2)]
        only_in_2 = [files2[n] for n in (names2 - names1)]
        
        # Проверяем различия в одинаковых файлах
        different = []
        for name in names1 & names2:
            f1 = files1[name]
            f2 = files2[name]
            if f1.size != f2.size or f1.modified != f2.modified:
                different.append({'name': name, 'file1': f1, 'file2': f2})
        
        return {
            'only_in_1': only_in_1,
            'only_in_2': only_in_2,
            'different': different,
            'identical': len(names1 & names2) - len(different)
        }
    
    # ============================================================
    # РАЗМЕР ДИРЕКТОРИИ
    # ============================================================
    
    def get_dir_size_local(self, path: str) -> int:
        """Вычисляет размер локальной директории"""
        total = 0
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
        except:
            pass
        return total
    
    def get_dir_size_remote(self, stand_name: str, path: str) -> int:
        """Вычисляет размер директории на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return 0
        
        command = f"du -sb {path} 2>/dev/null | cut -f1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success and stdout.strip().isdigit():
            return int(stdout.strip())
        return 0
    
    # ============================================================
    # КОНТРОЛЬНЫЕ СУММЫ
    # ============================================================
    
    def calculate_md5_local(self, file_path: str) -> Optional[str]:
        """Вычисляет MD5 локального файла"""
        if not os.path.isfile(file_path):
            return None
        
        try:
            md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            return md5.hexdigest()
        except:
            return None
    
    def calculate_md5_remote(self, stand_name: str, file_path: str) -> Optional[str]:
        """Вычисляет MD5 файла на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return None
        
        command = f"md5sum {file_path} 2>/dev/null | cut -d' ' -f1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if success and stdout.strip():
            return stdout.strip()
        return None
    
    # ============================================================
    # ИЗБРАННОЕ
    # ============================================================
    
    def add_favorite(self, path: str):
        """Добавляет путь в избранное"""
        if path not in self.favorites:
            self.favorites.append(path)
            self.logger.info(f"Добавлено в избранное: {path}")
    
    def remove_favorite(self, path: str):
        """Удаляет путь из избранного"""
        if path in self.favorites:
            self.favorites.remove(path)
            self.logger.info(f"Удалено из избранного: {path}")
    
    def get_favorites(self) -> List[str]:
        """Возвращает список избранных путей"""
        return self.favorites.copy()
    
    # ============================================================
    # ДЕРЕВО ДИРЕКТОРИЙ
    # ============================================================
    
    def tree_local(self, path: str = None, max_depth: int = 3,
                   show_files: bool = True, indent: str = "") -> str:
        """
        Возвращает текстовое дерево директорий.
        
        Args:
            path: Начальный путь
            max_depth: Глубина
            show_files: Показывать файлы
            indent: Отступ для рекурсии
            
        Returns:
            Строка с деревом
        """
        if path is None:
            path = self.local_cwd
        
        if max_depth <= 0:
            return ""
        
        result = ""
        items = sorted(os.listdir(path))
        
        for i, item in enumerate(items):
            full_path = os.path.join(path, item)
            is_last = (i == len(items) - 1)
            prefix = "└── " if is_last else "├── "
            
            if os.path.isdir(full_path):
                result += f"{indent}{prefix}{item}/\n"
                new_indent = indent + ("    " if is_last else "│   ")
                result += self.tree_local(full_path, max_depth - 1, show_files, new_indent)
            elif show_files:
                result += f"{indent}{prefix}{item}\n"
        
        return result
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def _format_permissions(self, mode: int) -> str:
        """Форматирует права доступа в строку rwx"""
        perms = ""
        for who in "USR", "GRP", "OTH":
            for what in "R", "W", "X":
                if mode & getattr(os, f"S_I{what}{who}"):
                    perms += what.lower()
                else:
                    perms += "-"
        return perms
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def exists_local(self, path: str) -> bool:
        """Проверяет существование локального пути"""
        return os.path.exists(path)
    
    def exists_remote(self, stand_name: str, path: str) -> bool:
        """Проверяет существование пути на стенде"""
        if not self.bc or not self.bc.is_connected(stand_name):
            return False
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"test -e {path} && echo 'YES' || echo 'NO'"
        )
        return success and 'YES' in stdout


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ FILE MANAGER")
    print("=" * 60)
    
    fm = FileManager()
    
    # Локальные операции
    print(f"\nТекущая директория: {fm.get_local_cwd()}")
    
    print("\nСодержимое текущей папки:")
    for item in fm.list_local(sort_by="name")[:20]:
        print(f"  {item}")
    
    print("\nТолько Python-файлы:")
    py_files = fm.filter_by_extension(fm.list_local(), ['.py'])
    for item in py_files[:10]:
        print(f"  {item}")
    
    print("\nГруппировка по расширениям:")
    groups = fm.group_by_extension(fm.list_local())
    for ext, files in groups.items():
        print(f"  {ext}: {len(files)} файлов")
    
    print("\nДерево (глубина 2):")
    print(fm.tree_local(max_depth=2, show_files=False))
    
    print("\n" + "=" * 60)
    print("Примеры использования с удаленными стендами:")
    print("=" * 60)
    print("""
    from core.bench_connector import BenchConnector
    bc = BenchConnector()
    bc.start_monitoring()
    bc.connect_to_stand('ГОЗ')  # запросит пароль
    
    fm = FileManager(bc)
    
    # Список файлов на стенде
    files = fm.list_remote('ГОЗ', '/home/pkrv/CVS')
    for f in files:
        print(f)
    
    # Сменить директорию
    fm.cd_remote('ГОЗ', '/tmp')
    print(fm.get_remote_cwd('ГОЗ'))
    
    # Размер папки
    size = fm.get_dir_size_remote('ГОЗ', '/home/pkrv/CVS')
    print(f"Размер CVS: {fm._format_size(size)}")
    
    # Поиск на стенде
    results = fm.search_remote('ГОЗ', '/home/pkrv', pattern='*.cfg')
    for f in results:
        print(f.path)
    """)
