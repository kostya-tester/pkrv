"""
Сборка Bench Manager в EXE файл для Windows.
Запуск: python build_exe.py
"""

import os
import sys
import shutil
import subprocess

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
            try:
                shutil.rmtree(path)
                print(f"[OK] Очищено: {folder}")
            except Exception as e:
                print(f"[WARN] Не удалось очистить {folder}: {e}")

    # Проверяем наличие файлов
    required_files = ["main.py", "config.yaml"]
    for file in required_files:
        if not os.path.exists(os.path.join(BASE_DIR, file)):
            print(f"[ERROR] Файл не найден: {file}")
            return

    # Проверяем наличие папки с иконками
    images_dir = os.path.join(BASE_DIR, "gui", "images")
    has_images = os.path.exists(images_dir)

    # Формируем команду для PyInstaller
    cmd_parts = [
        "pyinstaller",
        "--onefile",           # Один EXE файл
        "--windowed",          # Без консольного окна
        "--name", "BenchManager",
        "--clean",             # Очистить кеш
        "--noconfirm",         # Не спрашивать подтверждение
    ]

    # Добавляем иконку если есть
    icon_path = os.path.join(BASE_DIR, "gui", "images", "logo.png")
    if os.path.exists(icon_path):
        # Конвертируем PNG в ICO если нужно
        ico_path = os.path.join(BASE_DIR, "gui", "images", "logo.ico")
        if not os.path.exists(ico_path):
            print("[INFO] ICO иконка не найдена, будет использована стандартная")
        else:
            cmd_parts.extend(["--icon", ico_path])

    # Добавляем данные
    if has_images:
        cmd_parts.extend([
            "--add-data", f"gui{os.sep}images{os.pathsep}gui{os.sep}images"
        ])

    # Добавляем config.yaml
    cmd_parts.extend([
        "--add-data", f"config.yaml{os.pathsep}."
    ])

    # Скрытые импорты
    cmd_parts.extend([
        "--hidden-import", "paramiko",
        "--hidden-import", "paramiko.ssh_exception",
        "--hidden-import", "yaml",
        "--hidden-import", "PyQt5",
        "--hidden-import", "PyQt5.QtCore",
        "--hidden-import", "PyQt5.QtGui",
        "--hidden-import", "PyQt5.QtWidgets",
        "--hidden-import", "socket",
        "--hidden-import", "threading",
    ])

    # Исключаем ненужные модули для уменьшения размера
    cmd_parts.extend([
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "PIL",
        "--exclude-module", "tkinter",
    ])

    # Добавляем главный файл
    cmd_parts.append("main.py")

    # Запускаем сборку
    print("\n[INFO] Запуск PyInstaller...")
    print(f"[CMD] {' '.join(cmd_parts)}\n")

    try:
        result = subprocess.run(cmd_parts, cwd=BASE_DIR, capture_output=True, text=True)
        print(result.stdout)

        if result.returncode != 0:
            print("[ERROR] Ошибка при сборке:")
            print(result.stderr)
            return

        # Проверяем результат
        exe_path = os.path.join(DIST_DIR, "BenchManager.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n{'=' * 60}")
            print(f"[УСПЕХ] EXE создан!")
            print(f"[ПУТЬ] {exe_path}")
            print(f"[РАЗМЕР] {size_mb:.1f} MB")
            print(f"{'=' * 60}")

            # Копируем config.yaml рядом с EXE для удобства
            config_src = os.path.join(BASE_DIR, "config.yaml")
            config_dst = os.path.join(DIST_DIR, "config.yaml")
            if os.path.exists(config_src):
                shutil.copy2(config_src, config_dst)
                print(f"[INFO] config.yaml скопирован в {DIST_DIR}")
        else:
            print("\n[ERROR] EXE не был создан!")

    except Exception as e:
        print(f"[ERROR] Исключение при сборке: {e}")


if __name__ == "__main__":
    build()