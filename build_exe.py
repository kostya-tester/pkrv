"""
Сборка Bench Manager в EXE файл для Windows.
Запуск: python build_exe.py
"""

import os
import sys
import shutil

# Папки
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")

def build():
    print("=" * 60)
    print("СБОРКА BENCH MANAGER В EXE")
    print("=" * 60)
    
    # Очищаем старые сборки
    for folder in ["build", "dist"]:
        path = os.path.join(BASE_DIR, folder)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"[OK] Очищено: {folder}")
    
    # Список файлов для включения
    datas = []
    
    # Добавляем картинки
    images_dir = os.path.join(BASE_DIR, "gui", "images")
    if os.path.exists(images_dir):
        datas.append(f"gui/images/*")
        print("[OK] Добавлены картинки")
    
    # Добавляем скрипты
    scripts_dir = os.path.join(BASE_DIR, "scripts")
    if os.path.exists(scripts_dir):
        datas.append(f"scripts/*")
        print("[OK] Добавлены скрипты")
    
    # Добавляем конфиг
    config_file = os.path.join(BASE_DIR, "config.yaml")
    if os.path.exists(config_file):
        datas.append(f"config.yaml")
        print("[OK] Добавлен config.yaml")
    
    # Команда сборки
    cmd = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--name", "BenchManager",
        "--add-data", f"gui/images/*{os.pathsep}gui/images",
        "--add-data", f"scripts/*{os.pathsep}scripts",
        "--add-data", f"config.yaml{os.pathsep}.",
        "--hidden-import", "paramiko",
        "--hidden-import", "yaml",
        "--hidden-import", "psutil",
        "--hidden-import", "PyQt5",
        "main.py"
    ]
    
    print(f"\nКоманда: {' '.join(cmd)}")
    print("\nЗапуск сборки...\n")
    
    # Запускаем
    os.system(" ".join(cmd))
    
    # Проверяем результат
    exe_path = os.path.join(DIST_DIR, "BenchManager.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n[ГОТОВО] EXE создан: {exe_path}")
        print(f"[INFO] Размер: {size_mb:.1f} MB")
    else:
        print("\n[ОШИБКА] EXE не создан!")


if __name__ == "__main__":
    build()
