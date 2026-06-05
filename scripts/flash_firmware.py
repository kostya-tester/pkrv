"""
Скрипт прошивки платы на стенде.
Создает симлинк на указанную прошивку: ln -sf <firmware> 1po2_1n
"""

import sys
import os
import time
import shutil
from datetime import datetime


# Пути по умолчанию
FIRMWARE_DIR = "/home/pkrv/fpo_cfg"
EXECUTABLE = "1po2_1n"
CONFIG_FILE = "1po2_1n.cfg"


def check_firmware(firmware_name: str) -> bool:
    """Проверяет наличие файла прошивки"""
    firmware_path = os.path.join(FIRMWARE_DIR, firmware_name)
    if os.path.exists(firmware_path):
        print(f"[OK] Прошивка найдена: {firmware_path}")
        return True
    else:
        print(f"[FAIL] Прошивка не найдена: {firmware_path}")
        return False


def backup_current() -> str:
    """Создает бэкап текущей прошивки"""
    executable_path = os.path.join(FIRMWARE_DIR, EXECUTABLE)
    
    if not os.path.exists(executable_path):
        print("[WARN] Нет текущей прошивки для бэкапа")
        return ""
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Если симлинк - читаем цель
    if os.path.islink(executable_path):
        current = os.readlink(executable_path)
        backup_name = f"{current}.backup_{timestamp}"
        
        if os.path.exists(os.path.join(FIRMWARE_DIR, current)):
            shutil.copy2(
                os.path.join(FIRMWARE_DIR, current),
                os.path.join(FIRMWARE_DIR, backup_name)
            )
            print(f"[OK] Бэкап создан: {backup_name}")
            return backup_name
    
    return ""


def stop_process():
    """Останавливает запущенный процесс"""
    print(f"Остановка {EXECUTABLE}...")
    os.system(f"pkill -f {EXECUTABLE} 2>/dev/null")
    os.system(f"slay {EXECUTABLE} 2>/dev/null")
    time.sleep(1)
    print("[OK] Процесс остановлен")


def flash_firmware(firmware_name: str) -> bool:
    """Прошивает плату указанной прошивкой"""
    firmware_path = os.path.join(FIRMWARE_DIR, firmware_name)
    executable_path = os.path.join(FIRMWARE_DIR, EXECUTABLE)
    
    # Удаляем старый файл/симлинк
    if os.path.exists(executable_path):
        os.remove(executable_path)
        print(f"[OK] Удален старый: {executable_path}")
    
    # Создаем симлинк
    os.symlink(firmware_path, executable_path)
    print(f"[OK] Создан симлинк: {EXECUTABLE} -> {firmware_name}")
    
    # Проверяем
    if os.path.exists(executable_path) and os.path.islink(executable_path):
        target = os.readlink(executable_path)
        print(f"[OK] Проверка: {EXECUTABLE} -> {target}")
        return True
    
    return False


def start_process():
    """Запускает прошитый процесс"""
    executable_path = os.path.join(FIRMWARE_DIR, EXECUTABLE)
    
    if not os.path.exists(executable_path):
        print(f"[FAIL] Исполняемый файл не найден: {executable_path}")
        return
    
    print(f"Запуск {EXECUTABLE}...")
    os.system(f"cd {FIRMWARE_DIR} && nohup ./{EXECUTABLE} > /dev/null 2>&1 &")
    time.sleep(1)
    
    # Проверяем запуск
    result = os.popen(f"pgrep -f {EXECUTABLE}").read().strip()
    if result:
        print(f"[OK] Процесс запущен, PID: {result}")
    else:
        print("[WARN] Процесс не запустился или сразу завершился")


def main():
    print("=" * 60)
    print("ПРОШИВКА ПЛАТЫ")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Аргументы
    if len(sys.argv) < 2:
        print("Использование: python flash_firmware.py <прошивка>")
        print(f"Пример: python flash_firmware.py mpo")
        print(f"\nПапка прошивок: {FIRMWARE_DIR}")
        
        # Список доступных прошивок
        if os.path.isdir(FIRMWARE_DIR):
            files = os.listdir(FIRMWARE_DIR)
            firmwares = [f for f in files 
                        if not f.endswith('.cfg') 
                        and '.backup' not in f 
                        and f != EXECUTABLE]
            
            if firmwares:
                print(f"\nДоступные прошивки:")
                for fw in firmwares:
                    size = os.path.getsize(os.path.join(FIRMWARE_DIR, fw))
                    print(f"  - {fw} ({size} байт)")
        
        return 1
    
    firmware_name = sys.argv[1]
    
    print(f"\nПрошивка: {firmware_name}")
    print(f"Папка: {FIRMWARE_DIR}")
    
    # 1. Проверяем прошивку
    if not check_firmware(firmware_name):
        return 1
    
    # 2. Бэкап
    backup_current()
    
    # 3. Останавливаем процесс
    stop_process()
    
    # 4. Прошиваем
    if not flash_firmware(firmware_name):
        print("[FAIL] Ошибка прошивки!")
        return 1
    
    # 5. Запускаем
    start_process()
    
    print("\n" + "=" * 60)
    print("[ГОТОВО] Плата прошита успешно!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
