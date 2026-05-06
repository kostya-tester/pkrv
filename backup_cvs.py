"""
Скрипт бэкапа папки /home/pkrv/CVS со стендов.
Запуск: python backup_cvs.py
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.bench_connector import BenchConnector
from core.file_transfer import FileTransfer


def backup_cvs(stand_name: str, backup_dir: str = "backups"):
    """
    Создает бэкап папки /home/pkrv/CVS со стенда.
    
    Args:
        stand_name: Имя стенда (ГОЗ, Арктика, C1M)
        backup_dir: Папка для бэкапов
    """
    # Создаем коннектор и файловый менеджер
    bc = BenchConnector()
    ft = FileTransfer(bc)
    
    # Запускаем мониторинг
    bc.start_monitoring()
    time.sleep(2)
    
    # Проверяем доступность стенда
    info = bc.get_stand_info(stand_name)
    if info['status'] != 'online':
        print(f"Стенд {stand_name} недоступен!")
        bc.stop_monitoring()
        return None
    
    print(f"Подключение к {stand_name}...")
    
    # Подключаемся (запросит пароль)
    if not bc.connect_to_stand(stand_name):
        print("Ошибка подключения!")
        bc.stop_monitoring()
        return None
    
    # Имя архива с датой
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_name = f"CVS_backup_{stand_name}_{timestamp}.tar.gz"
    remote_archive = f"/tmp/{archive_name}"
    
    cvs_path = "/home/pkrv/CVS"
    
    # Получаем список файлов
    print(f"\nФайлы в {cvs_path}:")
    success, stdout, stderr = bc.execute_command(stand_name, f"ls -la {cvs_path}")
    if success:
        print(stdout)
    
    # Создаем архив на стенде
    print(f"Создание архива {archive_name}...")
    success, stdout, stderr = bc.execute_command(
        stand_name,
        f"cd {cvs_path} && tar -czf {remote_archive} ."
    )
    
    if not success:
        print(f"Ошибка создания архива: {stderr}")
        bc.disconnect_from_stand(stand_name)
        bc.stop_monitoring()
        return None
    
    # Получаем размер архива
    success, stdout, stderr = bc.execute_command(stand_name, f"ls -lh {remote_archive} | awk '{{print $5}}'")
    archive_size = stdout.strip() if success else "неизвестно"
    
    # Скачиваем архив
    os.makedirs(backup_dir, exist_ok=True)
    local_path = os.path.join(backup_dir, archive_name)
    
    print(f"Скачивание архива ({archive_size})...")
    result = ft.download_file(stand_name, remote_archive, local_path)
    
    # Удаляем архив на стенде
    bc.execute_command(stand_name, f"rm -f {remote_archive}")
    
    # Отключаемся
    bc.disconnect_from_stand(stand_name)
    bc.stop_monitoring()
    
    if result:
        # Считаем MD5
        import hashlib
        md5 = hashlib.md5()
        with open(local_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        
        print(f"\nБэкап создан успешно!")
        print(f"  Файл: {local_path}")
        print(f"  Размер: {os.path.getsize(local_path):,} байт")
        print(f"  MD5: {md5.hexdigest()}")
        return local_path
    else:
        print("Ошибка скачивания!")
        return None


def backup_all_stands():
    """Создает бэкап со всех доступных стендов"""
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(3)
    
    print("=" * 60)
    print("БЭКАП CVS СО ВСЕХ СТЕНДОВ")
    print("=" * 60)
    
    for stand_name in ["ГОЗ", "Арктика", "C1M"]:
        print(f"\n{'=' * 60}")
        print(f"Стенд: {stand_name}")
        print(f"{'=' * 60}")
        
        info = bc.get_stand_info(stand_name)
        if info['status'] == 'online':
            backup_cvs(stand_name)
        else:
            print(f"Стенд {stand_name} OFFLINE - пропускаем")
    
    bc.stop_monitoring()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Бэкап папки CVS со стендов")
    parser.add_argument("stand", nargs="?", default=None, 
                       help="Имя стенда (ГОЗ, Арктика, C1M). Если не указано - все стенды")
    parser.add_argument("-o", "--output", default="backups",
                       help="Папка для сохранения бэкапов (по умолчанию: backups)")
    
    args = parser.parse_args()
    
    if args.stand:
        backup_cvs(args.stand, args.output)
    else:
        backup_all_stands()
