"""
Скрипт чтения данных с датчиков платы.
Собирает системную информацию: температура, память, загрузка CPU, сеть.
"""

import sys
import os
import time
import json
from datetime import datetime


def read_cpu_temp() -> str:
    """Читает температуру CPU"""
    paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
    ]
    
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    temp = int(f.read().strip()) / 1000
                    return f"{temp:.1f}°C"
            except:
                pass
    
    # Пробуем через команду
    result = os.popen("vcgencmd measure_temp 2>/dev/null").read().strip()
    if result:
        return result.replace("temp=", "")
    
    return "N/A"


def read_cpu_usage() -> str:
    """Читает загрузку CPU"""
    try:
        # /proc/stat
        with open('/proc/stat', 'r') as f:
            line = f.readline()
            parts = line.split()
            
            if len(parts) >= 5:
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                
                total = user + nice + system + idle
                usage = 100 * (user + nice + system) / total
                
                return f"{usage:.1f}%"
    except:
        pass
    
    # Запасной вариант
    result = os.popen("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'").read().strip()
    if result:
        return f"{result}%"
    
    return "N/A"


def read_memory() -> dict:
    """Читает использование памяти"""
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        
        mem_info = {}
        for line in lines:
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip().split()[0]
                
                if key in ['MemTotal', 'MemFree', 'MemAvailable']:
                    mem_info[key] = int(value) // 1024  # в МБ
        
        total = mem_info.get('MemTotal', 0)
        free = mem_info.get('MemAvailable', mem_info.get('MemFree', 0))
        used = total - free if total > 0 else 0
        percent = (used / total * 100) if total > 0 else 0
        
        return {
            'total_mb': total,
            'used_mb': used,
            'free_mb': free,
            'percent': f"{percent:.1f}%"
        }
    except:
        pass
    
    # Запасной вариант
    result = os.popen("free -m | grep Mem | awk '{print $2,$3,$4}'").read().strip()
    if result:
        parts = result.split()
        if len(parts) >= 3:
            return {
                'total_mb': int(parts[0]),
                'used_mb': int(parts[1]),
                'free_mb': int(parts[2]),
                'percent': f"{int(parts[1])/int(parts[0])*100:.1f}%"
            }
    
    return {'total_mb': 0, 'used_mb': 0, 'free_mb': 0, 'percent': 'N/A'}


def read_disk_usage() -> dict:
    """Читает использование диска"""
    try:
        stat = os.statvfs('/')
        total = stat.f_frsize * stat.f_blocks
        free = stat.f_frsize * stat.f_bfree
        used = total - free
        percent = (used / total * 100) if total > 0 else 0
        
        return {
            'total_gb': round(total / (1024**3), 1),
            'used_gb': round(used / (1024**3), 1),
            'free_gb': round(free / (1024**3), 1),
            'percent': f"{percent:.1f}%"
        }
    except:
        pass
    
    # Запасной вариант
    result = os.popen("df -h / | tail -1 | awk '{print $2,$3,$4,$5}'").read().strip()
    if result:
        parts = result.split()
        if len(parts) >= 4:
            return {
                'total_gb': parts[0],
                'used_gb': parts[1],
                'free_gb': parts[2],
                'percent': parts[3]
            }
    
    return {'total_gb': 'N/A', 'used_gb': 'N/A', 'free_gb': 'N/A', 'percent': 'N/A'}


def read_network() -> dict:
    """Читает сетевую информацию"""
    result = {}
    
    # IP адрес
    ip = os.popen("hostname -I 2>/dev/null | awk '{print $1}'").read().strip()
    result['ip'] = ip if ip else "N/A"
    
    # Хостнейм
    hostname = os.popen("hostname").read().strip()
    result['hostname'] = hostname if hostname else "N/A"
    
    # Проверка соединения
    ping = os.popen("ping -c 1 8.8.8.8 2>/dev/null | grep 'time=' | awk -F'time=' '{print $2}' | awk '{print $1}'").read().strip()
    result['ping_google'] = f"{ping} ms" if ping else "N/A"
    
    return result


def read_uptime() -> str:
    """Читает время работы"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_sec = float(f.readline().split()[0])
        
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        
        if days > 0:
            return f"{days}д {hours}ч {minutes}м"
        elif hours > 0:
            return f"{hours}ч {minutes}м"
        else:
            return f"{minutes}м"
    except:
        pass
    
    result = os.popen("uptime | awk -F'up' '{print $2}' | awk -F',' '{print $1}'").read().strip()
    return result if result else "N/A"


def main():
    """Основная функция"""
    print("=" * 60)
    print("ЧТЕНИЕ ДАТЧИКОВ ПЛАТЫ")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Сбор данных
    data = {
        'timestamp': datetime.now().isoformat(),
        'hostname': os.uname().nodename if hasattr(os, 'uname') else read_network()['hostname'],
        'cpu_temp': read_cpu_temp(),
        'cpu_usage': read_cpu_usage(),
        'memory': read_memory(),
        'disk': read_disk_usage(),
        'network': read_network(),
        'uptime': read_uptime(),
        'processes': len(os.popen("ps aux | grep -v grep | grep 1po2_1n").read().strip().split('\n'))
    }
    
    # Вывод в читаемом виде
    print(f"\n{'─' * 40}")
    print("СИСТЕМНАЯ ИНФОРМАЦИЯ")
    print(f"{'─' * 40}")
    print(f"  Хост:          {data['hostname']}")
    print(f"  Uptime:        {data['uptime']}")
    print(f"  IP:            {data['network']['ip']}")
    
    print(f"\n{'─' * 40}")
    print("РЕСУРСЫ")
    print(f"{'─' * 40}")
    print(f"  CPU темп.:     {data['cpu_temp']}")
    print(f"  CPU загрузка:  {data['cpu_usage']}")
    print(f"  Память:        {data['memory']['percent']} "
          f"({data['memory']['used_mb']}/{data['memory']['total_mb']} MB)")
    print(f"  Диск:          {data['disk']['percent']} "
          f"({data['disk']['used_gb']}/{data['disk']['total_gb']} GB)")
    
    print(f"\n{'─' * 40}")
    print("ПРОЦЕСС")
    print(f"{'─' * 40}")
    if data['processes'] > 0:
        print(f"  1po2_1n:       ЗАПУЩЕН ({data['processes']} экз.)")
    else:
        print(f"  1po2_1n:       ОСТАНОВЛЕН")
    
    print(f"\n{'─' * 40}")
    print("СЕТЬ")
    print(f"{'─' * 40}")
    print(f"  Ping 8.8.8.8:  {data['network']['ping_google']}")
    
    # Если аргумент --json - выводим JSON
    if '--json' in sys.argv:
        print(f"\n{json.dumps(data, indent=2, ensure_ascii=False)}")
    
    print("\n[OK] Чтение датчиков завершено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
