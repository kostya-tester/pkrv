"""
Пример скрипта для запуска на стендах.
Демонстрирует структуру скрипта: аргументы, вывод, логгирование.
"""

import sys
import os
import time
from datetime import datetime


def main():
    """Основная функция скрипта"""
    
    print("=" * 50)
    print(f"ЗАПУСК СКРИПТА: {os.path.basename(__file__)}")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Хост: {os.uname().nodename if hasattr(os, 'uname') else 'unknown'}")
    print("=" * 50)
    
    # Аргументы командной строки
    args = sys.argv[1:]
    print(f"\nАргументы: {args if args else 'нет'}")
    
    # Имитация работы
    print("\nВыполнение задачи...")
    for i in range(5):
        print(f"  Шаг {i+1}/5...")
        time.sleep(0.5)
    
    # Проверка окружения
    print("\nПроверка окружения:")
    print(f"  Текущая папка: {os.getcwd()}")
    print(f"  Пользователь: {os.environ.get('USER', 'unknown')}")
    print(f"  HOME: {os.environ.get('HOME', 'unknown')}")
    
    print("\n[ЗАВЕРШЕНО] Скрипт выполнен успешно!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
