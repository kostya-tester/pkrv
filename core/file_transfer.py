"""
Модуль передачи файлов на стенды и обратно.
Использует системные scp/pscp или paramiko если доступен.
Работает на Windows и Linux.
"""

import os
import sys
import time
import hashlib
import tempfile
import zipfile
import tarfile
import threading
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime
from pathlib import Path

# Импортируем коннектор
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.bench_connector import BenchConnector, LogManager, OS_TYPE, SSHConnection
except ImportError:
    # Упрощенный импорт для тестирования
    from bench_connector import BenchConnector, LogManager, OS_TYPE, SSHConnection


class FileTransfer:
    """
    Модуль передачи файлов между локальной машиной и стендами.
    
    Возможности:
    - Загрузка файлов на стенд
    - Скачивание файлов со стенда
    - Прогресс передачи
    - Проверка контрольных сумм (MD5)
    - Сжатие перед отправкой
    - Пакетная передача
    - Повтор при обрыве
    - Работа с директориями
    """
    
    def __init__(self, bench_connector: BenchConnector):
        """
        Args:
            bench_connector: Экземпляр BenchConnector для SSH-соединений
        """
        self.bc = bench_connector
        self.logger = LogManager()
        self.logger.setup(level="INFO")
        
        # Папка для временных файлов
        self.temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Папка для скачанных файлов
        self.downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "downloads")
        os.makedirs(self.downloads_dir, exist_ok=True)
    
    # ============================================================
    # ЗАГРУЗКА ФАЙЛА НА СТЕНД
    # ============================================================
    
    def upload_file(self, stand_name: str, local_path: str, remote_folder: str,
                    remote_filename: str = None, show_progress: bool = True,
                    verify: bool = True, retries: int = 2) -> bool:
        """
        Загружает один файл на стенд.
        
        Args:
            stand_name: Имя стенда (ГОЗ, Арктика, C1M, OrangePi)
            local_path: Путь к локальному файлу
            remote_folder: Папка назначения на стенде
            remote_filename: Имя файла на стенде (если None - оригинальное)
            show_progress: Показывать прогресс загрузки
            verify: Проверять контрольную сумму после загрузки
            retries: Количество повторных попыток при ошибке
            
        Returns:
            True если загрузка успешна
        """
        # Проверяем локальный файл
        if not os.path.exists(local_path):
            self.logger.error(f"Файл не найден: {local_path}")
            return False
        
        if not os.path.isfile(local_path):
            self.logger.error(f"Это не файл: {local_path}")
            return False
        
        # Проверяем подключение
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к стенду {stand_name}")
            return False
        
        # Определяем имя файла
        if remote_filename is None:
            remote_filename = os.path.basename(local_path)
        
        remote_path = f"{remote_folder.rstrip('/')}/{remote_filename}"
        
        # Вычисляем MD5 локального файла
        local_md5 = None
        if verify:
            self.logger.info(f"Вычисление контрольной суммы {local_path}...")
            local_md5 = self._calculate_md5(local_path)
            self.logger.info(f"MD5: {local_md5}")
        
        # Получаем размер файла
        file_size = os.path.getsize(local_path)
        file_size_str = self._format_size(file_size)
        
        self.logger.info(f"Загрузка файла на {stand_name}:")
        self.logger.info(f"  Источник: {local_path}")
        self.logger.info(f"  Назначение: {remote_path}")
        self.logger.info(f"  Размер: {file_size_str}")
        
        # Попытки загрузки
        for attempt in range(1, retries + 2):
            if attempt > 1:
                self.logger.info(f"Повторная попытка {attempt}/{retries + 1}...")
                time.sleep(2)
            
            # Показываем прогресс (если файл большой)
            if show_progress and file_size > 1024 * 1024:  # > 1MB
                self._show_upload_progress(stand_name, local_path, remote_path, file_size)
            
            # Выполняем загрузку
            conn = self.bc.connections.get(stand_name)
            if not conn:
                self.logger.error(f"Соединение с {stand_name} потеряно")
                continue
            
            if conn.upload_file(local_path, remote_path):
                # Проверяем загрузку
                if verify and local_md5:
                    self.logger.info("Проверка загруженного файла...")
                    if self._verify_remote_file(stand_name, remote_path, local_md5):
                        self.logger.info(f"Файл успешно загружен и проверен: {remote_filename}")
                        return True
                    else:
                        self.logger.error("Контрольная сумма не совпадает!")
                        # Удаляем битый файл
                        self.bc.execute_command(stand_name, f"rm -f {remote_path}")
                        continue
                else:
                    self.logger.info(f"Файл загружен: {remote_filename}")
                    return True
            else:
                self.logger.error(f"Ошибка загрузки (попытка {attempt})")
        
        self.logger.error(f"Не удалось загрузить файл после {retries + 1} попыток")
        return False
    
    # ============================================================
    # СКАЧИВАНИЕ ФАЙЛА СО СТЕНДА
    # ============================================================
    
    def download_file(self, stand_name: str, remote_path: str, 
                      local_path: str = None, show_progress: bool = True,
                      verify: bool = True, retries: int = 2) -> Optional[str]:
        """
        Скачивает файл со стенда.
        
        Args:
            stand_name: Имя стенда
            remote_path: Путь к файлу на стенде
            local_path: Куда сохранить (если None - в папку downloads)
            show_progress: Показывать прогресс
            verify: Проверять контрольную сумму
            retries: Количество попыток
            
        Returns:
            Путь к скачанному файлу или None
        """
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к стенду {stand_name}")
            return None
        
        # Определяем локальный путь
        if local_path is None:
            filename = os.path.basename(remote_path)
            local_path = os.path.join(self.downloads_dir, f"{stand_name}_{filename}")
        
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Проверяем существование файла на стенде
        success, stdout, stderr = self.bc.execute_command(
            stand_name, 
            f"test -f {remote_path} && echo 'EXISTS' || echo 'NOT_FOUND'"
        )
        
        if not success or 'NOT_FOUND' in stdout:
            self.logger.error(f"Файл не найден на стенде: {remote_path}")
            return None
        
        # Получаем размер файла
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"stat -c%s {remote_path} 2>/dev/null || wc -c < {remote_path}"
        )
        
        remote_size = int(stdout.strip()) if success and stdout.strip().isdigit() else 0
        size_str = self._format_size(remote_size)
        
        self.logger.info(f"Скачивание файла с {stand_name}:")
        self.logger.info(f"  Источник: {remote_path}")
        self.logger.info(f"  Назначение: {local_path}")
        self.logger.info(f"  Размер: {size_str}")
        
        # Попытки скачивания
        for attempt in range(1, retries + 2):
            if attempt > 1:
                self.logger.info(f"Повторная попытка {attempt}/{retries + 1}...")
                time.sleep(2)
            
            if show_progress and remote_size > 1024 * 1024:
                self._show_download_progress(stand_name, remote_path, local_path, remote_size)
            
            conn = self.bc.connections.get(stand_name)
            if not conn:
                continue
            
            if conn.download_file(remote_path, local_path):
                if verify:
                    self.logger.info("Проверка скачанного файла...")
                    if self._verify_local_file(local_path, stand_name, remote_path):
                        self.logger.info(f"Файл скачан и проверен: {os.path.basename(local_path)}")
                        return local_path
                else:
                    self.logger.info(f"Файл скачан: {os.path.basename(local_path)}")
                    return local_path
        
        return None
    
    # ============================================================
    # ЗАГРУЗКА ДИРЕКТОРИИ
    # ============================================================
    
    def upload_directory(self, stand_name: str, local_dir: str, remote_folder: str,
                         compress: bool = True, show_progress: bool = True) -> bool:
        """
        Загружает директорию на стенд.
        
        Args:
            stand_name: Имя стенда
            local_dir: Локальная папка
            remote_folder: Папка назначения на стенде
            compress: Сжать перед отправкой (быстрее)
            show_progress: Показывать прогресс
            
        Returns:
            True если успешно
        """
        if not os.path.isdir(local_dir):
            self.logger.error(f"Директория не найдена: {local_dir}")
            return False
        
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к стенду {stand_name}")
            return False
        
        dir_name = os.path.basename(local_dir.rstrip('/\\'))
        
        self.logger.info(f"Загрузка директории на {stand_name}: {dir_name}")
        
        if compress:
            # Сжимаем и отправляем
            archive_name = f"{dir_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
            archive_local = os.path.join(self.temp_dir, archive_name)
            
            self.logger.info("Сжатие директории...")
            if self._create_tar_gz(local_dir, archive_local):
                self.logger.info(f"Архив создан: {archive_name}")
                
                # Загружаем архив
                if self.upload_file(stand_name, archive_local, remote_folder, archive_name, show_progress):
                    # Распаковываем на стенде
                    self.logger.info("Распаковка на стенде...")
                    success, stdout, stderr = self.bc.execute_command(
                        stand_name,
                        f"cd {remote_folder} && tar -xzf {archive_name} && rm -f {archive_name}"
                    )
                    
                    # Удаляем локальный архив
                    os.remove(archive_local)
                    
                    if success:
                        self.logger.info(f"Директория загружена: {dir_name}")
                        return True
                    else:
                        self.logger.error(f"Ошибка распаковки: {stderr}")
                
                # Удаляем локальный архив
                if os.path.exists(archive_local):
                    os.remove(archive_local)
            else:
                self.logger.error("Ошибка создания архива")
        else:
            # Пофайловая загрузка
            self.logger.info("Пофайловая загрузка...")
            
            files_uploaded = 0
            files_failed = 0
            
            for root, dirs, files in os.walk(local_dir):
                for filename in files:
                    local_file = os.path.join(root, filename)
                    relative_path = os.path.relpath(local_file, local_dir)
                    remote_file_path = f"{remote_folder.rstrip('/')}/{relative_path}"
                    remote_file_dir = os.path.dirname(remote_file_path)
                    
                    # Создаем поддиректории на стенде
                    self.bc.execute_command(stand_name, f"mkdir -p {remote_file_dir}")
                    
                    if self.upload_file(stand_name, local_file, remote_file_dir, filename, 
                                       show_progress=False, verify=False):
                        files_uploaded += 1
                    else:
                        files_failed += 1
            
            self.logger.info(f"Загружено: {files_uploaded}, ошибок: {files_failed}")
            return files_failed == 0
        
        return False
    
    # ============================================================
    # СКАЧИВАНИЕ ДИРЕКТОРИИ
    # ============================================================
    
    def download_directory(self, stand_name: str, remote_dir: str,
                           local_path: str = None) -> Optional[str]:
        """
        Скачивает директорию со стенда (архивом).
        
        Args:
            stand_name: Имя стенда
            remote_dir: Путь к папке на стенде
            local_path: Куда сохранить
            
        Returns:
            Путь к скачанной папке или None
        """
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к стенду {stand_name}")
            return None
        
        if local_path is None:
            dir_name = os.path.basename(remote_dir.rstrip('/'))
            local_path = os.path.join(self.downloads_dir, f"{stand_name}_{dir_name}")
        
        archive_name = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        remote_archive = f"/tmp/{archive_name}"
        
        self.logger.info(f"Архивация директории на стенде: {remote_dir}")
        
        # Создаем архив на стенде
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"tar -czf {remote_archive} -C {os.path.dirname(remote_dir)} {os.path.basename(remote_dir)} 2>/dev/null"
        )
        
        if not success:
            self.logger.error(f"Ошибка архивации: {stderr}")
            return None
        
        # Скачиваем
        archive_local = os.path.join(self.temp_dir, archive_name)
        result = self.download_file(stand_name, remote_archive, archive_local, show_progress=True)
        
        # Удаляем архив на стенде
        self.bc.execute_command(stand_name, f"rm -f {remote_archive}")
        
        if result:
            # Распаковываем
            self.logger.info(f"Распаковка в {local_path}...")
            os.makedirs(local_path, exist_ok=True)
            
            if self._extract_tar_gz(archive_local, local_path):
                os.remove(archive_local)
                self.logger.info(f"Директория скачана: {local_path}")
                return local_path
        
        if os.path.exists(archive_local):
            os.remove(archive_local)
        
        return None
    
    # ============================================================
    # ПРОВЕРКА ЦЕЛОСТНОСТИ
    # ============================================================
    
    def _calculate_md5(self, file_path: str) -> str:
        """Вычисляет MD5 хеш файла"""
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    
    def _verify_remote_file(self, stand_name: str, remote_path: str, expected_md5: str) -> bool:
        """Проверяет MD5 файла на стенде"""
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"md5sum {remote_path} 2>/dev/null | cut -d' ' -f1"
        )
        if success and stdout.strip():
            remote_md5 = stdout.strip()
            return remote_md5.lower() == expected_md5.lower()
        return False
    
    def _verify_local_file(self, local_path: str, stand_name: str, remote_path: str) -> bool:
        """Проверяет MD5 локального и удаленного файла"""
        local_md5 = self._calculate_md5(local_path)
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"md5sum {remote_path} 2>/dev/null | cut -d' ' -f1"
        )
        if success and stdout.strip():
            remote_md5 = stdout.strip()
            match = local_md5.lower() == remote_md5.lower()
            self.logger.info(f"  Локальный MD5:  {local_md5}")
            self.logger.info(f"  Удаленный MD5:  {remote_md5}")
            self.logger.info(f"  Совпадение:     {'ДА' if match else 'НЕТ'}")
            return match
        return False
    
    # ============================================================
    # АРХИВАЦИЯ
    # ============================================================
    
    def _create_tar_gz(self, source_dir: str, output_path: str) -> bool:
        """Создает tar.gz архив директории"""
        try:
            import tarfile
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(source_dir, arcname=os.path.basename(source_dir))
            return True
        except Exception as e:
            self.logger.error(f"Ошибка создания архива: {e}")
            return False
    
    def _extract_tar_gz(self, archive_path: str, output_dir: str) -> bool:
        """Распаковывает tar.gz архив"""
        try:
            import tarfile
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=output_dir)
            return True
        except Exception as e:
            self.logger.error(f"Ошибка распаковки: {e}")
            return False
    
    # ============================================================
    # ПРОГРЕСС ПЕРЕДАЧИ
    # ============================================================
    
    def _show_upload_progress(self, stand_name: str, local_path: str, 
                               remote_path: str, file_size: int):
        """Показывает прогресс загрузки (упрощенно)"""
        self.logger.info(f"Загрузка... ({self._format_size(file_size)})")
        # Более сложный прогресс-бар можно добавить через tqdm или свой
    
    def _show_download_progress(self, stand_name: str, remote_path: str,
                                  local_path: str, file_size: int):
        """Показывает прогресс скачивания (упрощенно)"""
        self.logger.info(f"Скачивание... ({self._format_size(file_size)})")
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def _format_size(self, size: int) -> str:
        """Форматирует размер файла"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    def get_downloads_dir(self) -> str:
        """Возвращает путь к папке downloads"""
        return self.downloads_dir
    
    def list_downloads(self) -> List[str]:
        """Список скачанных файлов"""
        files = []
        for f in os.listdir(self.downloads_dir):
            path = os.path.join(self.downloads_dir, f)
            if os.path.isfile(path):
                files.append({
                    'name': f,
                    'size': self._format_size(os.path.getsize(path)),
                    'date': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
                })
        return sorted(files, key=lambda x: x['date'], reverse=True)
    
    def clean_temp(self):
        """Очищает временные файлы"""
        for f in os.listdir(self.temp_dir):
            try:
                path = os.path.join(self.temp_dir, f)
                if os.path.isfile(path):
                    os.remove(path)
            except:
                pass
        self.logger.info("Временные файлы очищены")


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК (ТОЛЬКО ДЛЯ ПРОВЕРКИ)
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ FILE TRANSFER")
    print("=" * 60)
    
    # Создаем коннектор
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(2)
    
    # Создаем file_transfer
    ft = FileTransfer(bc)
    
    print("\nДоступные стенды:")
    for name, info in bc.get_all_stands_info().items():
        status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name}: {status}")
    
    print("\nДля тестирования выберите стенд и подключитесь.")
    print("Пример использования:")
    print("  bc.connect_to_stand('ГОЗ')")
    print("  ft.upload_file('ГОЗ', 'test.txt', '/tmp')")
    print("  ft.download_file('ГОЗ', '/tmp/test.txt')")
    print("  ft.upload_directory('ГОЗ', './my_folder', '/tmp')")
    print("  ft.download_directory('ГОЗ', '/tmp/my_folder')")
