"""
Скрипт запуска тестового сценария на плате.
Проверяет работоспособность системы: файлы, процессы, сеть, прошивку.
"""

import sys
import os
import time
from datetime import datetime


# Конфигурация проверок
CHECKS = {
    'files': {
        'config': {
            'path': '/home/pkrv/fpo_cfg/1po2_1n.cfg',
            'description': 'Файл конфигурации'
        },
        'executable': {
            'path': '/home/pkrv/fpo_cfg/1po2_1n',
            'description': 'Исполняемый файл'
        },
        'cvs_folder': {
            'path': '/home/pkrv/CVS',
            'description': 'Папка CVS',
            'is_dir': True
        }
    },
    'processes': {
        'sshd': {
            'name': 'sshd',
            'description': 'SSH сервер'
        }
    },
    'network': {
        'localhost': {
            'host': '127.0.0.1',
            'port': 22,
            'description': 'SSH порт'
        }
    }
}

# Результаты тестов
passed = 0
failed = 0
warnings = 0


def test_header(title: str):
    """Выводит заголовок теста"""
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def test_result(name: str, success: bool, message: str = "", warning: bool = False):
    """Выводит результат теста"""
    global passed, failed, warnings
    
    if success:
        passed += 1
        status = "[OK]"
    elif warning:
        warnings += 1
        status = "[WARN]"
    else:
        failed += 1
        status = "[FAIL]"
    
    print(f"  {status} {name}: {message}")


def check_file(path: str, is_dir: bool = False) -> tuple:
    """Проверяет существование файла/папки"""
    exists = os.path.isdir(path) if is_dir else os.path.isfile(path)
    
    if exists:
        if is_dir:
            count = len(os.listdir(path))
            return True, f"найдено ({count} файлов)"
        else:
            size = os.path.getsize(path)
            return True, f"найден ({size} байт)"
    else:
        return False, "не найден"


def check_process(process_name: str) -> tuple:
    """Проверяет, запущен ли процесс"""
    result = os.popen(f"pgrep -f {process_name} 2>/dev/null").read().strip()
    
    if result:
        pids = result.split('\n')
        return True, f"запущен (PID: {', '.join(pids)})"
    else:
        # Проверяем через ps
        result = os.popen(f"ps aux | grep -v grep | grep {process_name}").read().strip()
        if result:
            return True, "запущен"
        return False, "не запущен"


def check_port(host: str, port: int, timeout: int = 2) -> tuple:
    """Проверяет доступность порта"""
    import socket
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            return True, f"порт {port} открыт"
        else:
            return False, f"порт {port} закрыт"
    except Exception as e:
        return False, str(e)


def check_active_firmware() -> tuple:
    """Проверяет активную прошивку"""
    executable = '/home/pkrv/fpo_cfg/1po2_1n'
    
    if not os.path.exists(executable):
        return False, "исполняемый файл не найден"
    
    if os.path.islink(executable):
        target = os.readlink(executable)
        return True, f"симлинк -> {os.path.basename(target)}"
    else:
        return True, "обычный файл (не симлинк)", True


def check_disk_space(path: str = "/") -> tuple:
    """Проверяет свободное место на диске"""
    try:
        stat = os.statvfs(path)
        free_gb = (stat.f_frsize * stat.f_bavail) / (1024**3)
        
        if free_gb > 1:
            return True, f"свободно {free_gb:.1f} GB"
        else:
            return False, f"мало места: {free_gb:.1f} GB", True
    except:
        return False, "не удалось проверить"


def check_memory() -> tuple:
    """Проверяет доступную память"""
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if 'MemAvailable' in line:
                    avail_kb = int(line.split()[1])
                    avail_mb = avail_kb // 1024
                    
                    if avail_mb > 100:
                        return True, f"доступно {avail_mb} MB"
                    else:
                        return False, f"мало памяти: {avail_mb} MB", True
        return False, "не удалось определить"
    except:
        return False, "ошибка чтения /proc/meminfo"


def run_custom_command(command: str) -> tuple:
    """Выполняет произвольную команду"""
    result = os.popen(f"{command} 2>&1").read().strip()
    exit_code = os.popen(f"{command} > /dev/null 2>&1; echo $?").read().strip()
    
    if exit_code == '0':
        return True, result[:80]
    else:
        return False, result[:80] if result else "ошибка выполнения"


def main():
    print("=" * 60)
    print("ЗАПУСК ТЕСТОВОГО СЦЕНАРИЯ")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Хост: {os.uname().nodename if hasattr(os, 'uname') else 'unknown'}")
    print("=" * 60)
    
    # --== ПРОВЕРКА ФАЙЛОВ ==--
    test_header("ПРОВЕРКА ФАЙЛОВ")
    
    for key, check in CHECKS['files'].items():
        success, message = check_file(
            check['path'],
            check.get('is_dir', False)
        )
        test_result(check['description'], success, message)
    
    # --== ПРОВЕРКА ПРОЦЕССОВ ==--
    test_header("ПРОВЕРКА ПРОЦЕССОВ")
    
    for key, check in CHECKS['processes'].items():
        success, message = check_process(check['name'])
        test_result(check['description'], success, message)
    
    # Проверка 1po2_1n отдельно
    success, message = check_process('1po2_1n')
    test_result("Процесс 1po2_1n", success, message)
    
    # --== ПРОВЕРКА СЕТИ ==--
    test_header("ПРОВЕРКА СЕТИ")
    
    for key, check in CHECKS['network'].items():
        success, message = check_port(check['host'], check['port'])
        test_result(check['description'], success, message)
    
    # --== ПРОВЕРКА ПРОШИВКИ ==--
    test_header("ПРОВЕРКА ПРОШИВКИ")
    
    success, message, *rest = check_active_firmware()
    warning = rest[0] if rest else False
    test_result("Активная прошивка", success, message, warning)
    
    # --== СИСТЕМНЫЕ РЕСУРСЫ ==--
    test_header("СИСТЕМНЫЕ РЕСУРСЫ")
    
    success, message, *rest = check_disk_space()
    warning = rest[0] if rest else False
    test_result("Дисковое пространство", success, message, warning)
    
    success, message, *rest = check_memory()
    warning = rest[0] if rest else False
    test_result("Оперативная память", success, message, warning)
    
    # --== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ==--
    if '--full' in sys.argv:
        test_header("ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ")
        
        # Проверка uptime
        uptime = os.popen("uptime -p 2>/dev/null || uptime").read().strip()
        test_result("Uptime", True, uptime)
        
        # Проверка логов
        log_exists = os.path.exists("/var/log/1po2_1n.log")
        if log_exists:
            log_size = os.path.getsize("/var/log/1po2_1n.log")
            test_result("Лог 1po2_1n.log", True, f"найден ({log_size} байт)")
        else:
            test_result("Лог 1po2_1n.log", False, "не найден", True)
    
    # --== ИТОГИ ==--
    test_header("ИТОГИ ТЕСТИРОВАНИЯ")
    
    total = passed + failed + warnings
    
    print(f"  Всего проверок: {total}")
    print(f"  Пройдено:       {passed}")
    print(f"  Предупреждений: {warnings}")
    print(f"  Ошибок:         {failed}")
    
    if failed == 0 and warnings == 0:
        print(f"\n  [OK] ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
    elif failed == 0:
        print(f"\n  [OK] ПРОВЕРКИ ПРОЙДЕНЫ (есть предупреждения)")
    else:
        print(f"\n  [FAIL] ОБНАРУЖЕНЫ ПРОБЛЕМЫ!")
    
    print("=" * 60)
    
    # Возвращаем код ошибки если были провалы
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
