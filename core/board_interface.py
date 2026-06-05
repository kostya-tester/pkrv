"""
Модуль взаимодействия с платами на стендах.
Прошивка, запуск скриптов, диагностика.
Использует BenchConnector для SSH-соединений.

Основные операции:
- Прошивка платы (ln -sf mpo 1po2_1n)
- Запуск исполняемых файлов
- Чтение данных с платы
- Диагностика подключения
- Перезагрузка платы
"""

import sys
import os
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.bench_connector import BenchConnector, LogManager
except ImportError:
    from bench_connector import BenchConnector, LogManager


class BoardInfo:
    """Информация о плате"""
    
    def __init__(self, name: str, board_type: str, serial: str = "",
                 status: str = "unknown", firmware: str = ""):
        self.name = name
        self.board_type = board_type
        self.serial = serial
        self.status = status
        self.firmware = firmware
        self.last_check = None
        self.connected = False
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'type': self.board_type,
            'serial': self.serial,
            'status': self.status,
            'firmware': self.firmware,
            'connected': self.connected,
            'last_check': self.last_check.strftime('%H:%M:%S') if self.last_check else 'Никогда'
        }


class BoardInterface:
    """
    Интерфейс для работы с платами на стендах.
    
    Для ГОЗ/Арктика/C1M:
    - Прошивка платы (симлинк на прошивку)
    - Запуск/остановка процессов
    - Чтение логов
    - Диагностика
    - Перезагрузка
    
    Для OrangePi:
    - Подключение и просмотр файлов
    - Базовая диагностика
    """
    
    KNOWN_BOARDS = {
        "ГОЗ": {
            "type": "основная",
            "paths": {
                "firmware_dir": "/home/pkrv/fpo_cfg",
                "executable": "1po2_1n",
                "config": "1po2_1n.cfg",
                "logs": "/var/log/1po2_1n.log",
                "scripts": "/home/pkrv/scripts"
            },
            "can_flash": True,
            "can_run_process": True
        },
        "Арктика": {
            "type": "основная",
            "paths": {
                "firmware_dir": "/home/pkrv/fpo_cfg",
                "executable": "1po2_1n",
                "config": "1po2_1n.cfg",
                "logs": "/var/log/1po2_1n.log",
                "scripts": "/home/pkrv/scripts"
            },
            "can_flash": True,
            "can_run_process": True
        },
        "C1M": {
            "type": "основная",
            "paths": {
                "firmware_dir": "/home/pkrv/fpo_cfg",
                "executable": "1po2_1n",
                "config": "1po2_1n.cfg",
                "logs": "/var/log/1po2_1n.log",
                "scripts": "/home/pkrv/scripts"
            },
            "can_flash": True,
            "can_run_process": True
        },
        "OrangePi": {
            "type": "orange_pi",
            "paths": {
                "home": "/home/orangepi",
                "root": "/"
            },
            "can_flash": False,
            "can_run_process": False,
            "view_only": True
        }
    }
    
    def __init__(self, bench_connector: BenchConnector):
        self.bc = bench_connector
        self.logger = LogManager()
        self.logger.setup(level="INFO")
        
        self.boards: Dict[str, BoardInfo] = {}
        self._init_boards()
        
        self.flash_history: List[Dict] = []
        self.script_history: List[Dict] = []
    
    def _init_boards(self):
        """Инициализация информации о платах"""
        for stand_name, board_config in self.KNOWN_BOARDS.items():
            if stand_name in self.bc.stands:
                board_info = BoardInfo(
                    name=f"Плата {stand_name}",
                    board_type=board_config['type'],
                    status="waiting"
                )
                self.boards[stand_name] = board_info
    
    def is_view_only(self, stand_name: str) -> bool:
        """Проверяет, только ли просмотр доступен для платы"""
        config = self.KNOWN_BOARDS.get(stand_name, {})
        return config.get('view_only', False)
    
    def can_flash(self, stand_name: str) -> bool:
        """Проверяет, можно ли прошивать плату"""
        config = self.KNOWN_BOARDS.get(stand_name, {})
        return config.get('can_flash', False)
    
    # ============================================================
    # ПРОВЕРКА ПЛАТЫ
    # ============================================================
    
    def check_board(self, stand_name: str) -> Dict:
        """
        Проверяет состояние платы на стенде.
        Для OrangePi - просто проверяет подключение и базовую информацию.
        """
        if not self.bc.is_connected(stand_name):
            return {'connected': False, 'error': f'Нет подключения к {stand_name}'}
        
        board_config = self.KNOWN_BOARDS.get(stand_name)
        if not board_config:
            return {'connected': False, 'error': f'Нет конфигурации для {stand_name}'}
        
        result = {
            'stand': stand_name,
            'board_type': board_config['type'],
            'connected': False,
            'view_only': board_config.get('view_only', False),
            'checks': {}
        }
        
        self.logger.info(f"Проверка платы на {stand_name}...")
        
        if board_config.get('view_only'):
            # Для OrangePi - простая проверка
            success, stdout, stderr = self.bc.execute_command(stand_name, "whoami && hostname && uptime")
            if success:
                result['connected'] = True
                result['whoami'] = stdout.split('\n')[0] if stdout else ''
                result['hostname'] = stdout.split('\n')[1] if len(stdout.split('\n')) > 1 else ''
                result['uptime'] = stdout.split('\n')[2] if len(stdout.split('\n')) > 2 else ''
                
                # Проверяем домашнюю папку
                home = board_config['paths'].get('home', '/home/orangepi')
                success, stdout, stderr = self.bc.execute_command(
                    stand_name, f"ls {home} 2>/dev/null && echo 'OK'"
                )
                result['checks']['home_exists'] = success and 'OK' in stdout
                
                if stand_name in self.boards:
                    self.boards[stand_name].connected = True
                    self.boards[stand_name].status = "connected"
                    self.boards[stand_name].last_check = datetime.now()
                
                self.logger.info(f"Плата {stand_name} подключена (только просмотр)")
        else:
            # Для основных стендов - полная проверка
            paths = board_config['paths']
            
            # Проверка папки с прошивками
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"test -d {paths['firmware_dir']} && echo 'EXISTS'"
            )
            result['checks']['firmware_dir'] = success and 'EXISTS' in stdout
            
            # Проверка исполняемого файла
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"test -f {paths['firmware_dir']}/{paths['executable']} && echo 'EXISTS'"
            )
            result['checks']['executable'] = success and 'EXISTS' in stdout
            
            # Проверка конфига
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"test -f {paths['firmware_dir']}/{paths['config']} && echo 'EXISTS'"
            )
            result['checks']['config_file'] = success and 'EXISTS' in stdout
            
            # Проверка процесса
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"ps aux | grep -v grep | grep {paths['executable']}"
            )
            result['checks']['process_running'] = success and paths['executable'] in stdout
            if result['checks']['process_running']:
                for line in stdout.split('\n'):
                    if paths['executable'] in line and 'grep' not in line:
                        parts = line.split()
                        if len(parts) > 1:
                            result['pid'] = parts[1]
                            break
            
            # Активная прошивка
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"ls -la {paths['firmware_dir']}/{paths['executable']} 2>/dev/null"
            )
            if success and '->' in stdout:
                link_target = stdout.split('->')[-1].strip()
                result['active_firmware'] = link_target
            
            if result['checks']['firmware_dir'] and result['checks']['executable']:
                result['connected'] = True
                
                if stand_name in self.boards:
                    self.boards[stand_name].connected = True
                    self.boards[stand_name].status = "running" if result['checks']['process_running'] else "ready"
                    self.boards[stand_name].firmware = result.get('active_firmware', 'unknown')
                    self.boards[stand_name].last_check = datetime.now()
        
        return result
    
    def check_all_boards(self) -> Dict[str, Dict]:
        """Проверяет платы на всех подключенных стендах"""
        results = {}
        for stand_name in self.bc.stands:
            if self.bc.is_connected(stand_name):
                results[stand_name] = self.check_board(stand_name)
        return results
    
    # ============================================================
    # ПРОСМОТР ФАЙЛОВ (ДЛЯ ORANGEPI)
    # ============================================================
    
    def browse_files(self, stand_name: str, path: str = "/") -> Dict:
        """
        Просмотр файлов на плате (для OrangePi или любого стенда).
        
        Args:
            stand_name: Имя стенда
            path: Путь для просмотра
            
        Returns:
            Словарь с содержимым папки
        """
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"ls -la --time-style=long-iso {path} 2>/dev/null"
        )
        
        if not success:
            return {'success': False, 'error': stderr, 'path': path}
        
        files = []
        for line in stdout.strip().split('\n'):
            if not line.startswith('total') and line.strip():
                parts = line.split()
                if len(parts) >= 8:
                    name = ' '.join(parts[7:])
                    if name in ['.', '..']:
                        continue
                    
                    files.append({
                        'name': name,
                        'is_dir': line.startswith('d'),
                        'size': int(parts[4]) if parts[4].isdigit() else 0,
                        'permissions': parts[0],
                        'owner': parts[2] if len(parts) > 2 else '',
                        'group': parts[3] if len(parts) > 3 else '',
                        'date': parts[5] if len(parts) > 5 else '',
                        'time': parts[6] if len(parts) > 6 else ''
                    })
        
        # Сортировка: папки первыми
        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        return {
            'success': True,
            'path': path,
            'files': files,
            'count': len(files)
        }
    
    def get_system_info(self, stand_name: str) -> Dict:
        """
        Получает системную информацию о плате.
        Работает для всех типов плат.
        """
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        info = {}
        
        commands = {
            'hostname': 'hostname',
            'uptime': 'uptime',
            'kernel': 'uname -r',
            'arch': 'uname -m',
            'os': 'cat /etc/os-release 2>/dev/null | head -3',
            'cpu': 'cat /proc/cpuinfo 2>/dev/null | grep "model name" | head -1 | cut -d: -f2',
            'memory': 'free -h 2>/dev/null | head -2',
            'disk': 'df -h / 2>/dev/null | tail -1',
            'who': 'whoami'
        }
        
        for key, cmd in commands.items():
            success, stdout, stderr = self.bc.execute_command(stand_name, cmd, timeout=5)
            if success:
                info[key] = stdout.strip()
        
        return {
            'success': True,
            'stand': stand_name,
            'info': info
        }
    
    # ============================================================
    # ПРОШИВКА ПЛАТЫ (ТОЛЬКО ДЛЯ ГОЗ/АРКТИКА/C1M)
    # ============================================================
    
    def flash_firmware(self, stand_name: str, firmware_name: str,
                       backup: bool = True) -> Dict:
        """
        Прошивает плату: ln -sf {firmware_name} 1po2_1n
        Только для ГОЗ/Арктика/C1M.
        """
        if not self.can_flash(stand_name):
            return {
                'success': False,
                'error': f'Прошивка недоступна для {stand_name}. Только просмотр.'
            }
        
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        board_config = self.KNOWN_BOARDS.get(stand_name)
        paths = board_config['paths']
        firmware_dir = paths['firmware_dir']
        executable = paths['executable']
        
        self.logger.info(f"Прошивка платы на {stand_name}: {firmware_name} -> {executable}")
        
        # Проверяем наличие прошивки
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"test -f {firmware_dir}/{firmware_name} && echo 'EXISTS'"
        )
        
        if not success or 'EXISTS' not in stdout:
            return {
                'success': False,
                'error': f'Файл прошивки {firmware_name} не найден в {firmware_dir}'
            }
        
        # Бэкап текущей прошивки
        current_fw = None
        if backup:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            success, stdout, stderr = self.bc.execute_command(
                stand_name,
                f"readlink {firmware_dir}/{executable} 2>/dev/null || echo ''"
            )
            current_fw = stdout.strip()
            
            if current_fw:
                backup_name = f"{current_fw}.backup_{timestamp}"
                self.bc.execute_command(
                    stand_name,
                    f"cp {firmware_dir}/{current_fw} {firmware_dir}/{backup_name}"
                )
                self.logger.info(f"Бэкап: {backup_name}")
        
        # Останавливаем процесс
        self.bc.execute_command(stand_name, f"pkill -f {executable} 2>/dev/null; sleep 1")
        
        # Создаем симлинк
        command = f"cd {firmware_dir} && rm -f {executable} && ln -sf {firmware_name} {executable}"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if not success:
            return {'success': False, 'error': f'Ошибка: {stderr}'}
        
        if stand_name in self.boards:
            self.boards[stand_name].firmware = firmware_name
        
        self.flash_history.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stand': stand_name,
            'firmware': firmware_name,
            'previous': current_fw
        })
        
        return {
            'success': True,
            'message': f'Плата {stand_name} прошита: {firmware_name}',
            'firmware': firmware_name,
            'backup_created': backup
        }
    
    def flash_default(self, stand_name: str) -> Dict:
        """Прошивает плату прошивкой 'mpo'"""
        return self.flash_firmware(stand_name, "mpo", backup=True)
    
    def get_firmware_list(self, stand_name: str) -> List[str]:
        """Список доступных прошивок"""
        if not self.can_flash(stand_name) or not self.bc.is_connected(stand_name):
            return []
        
        paths = self.KNOWN_BOARDS[stand_name]['paths']
        executable = paths['executable']
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"cd {paths['firmware_dir']} && ls -1 2>/dev/null"
        )
        
        if not success:
            return []
        
        return [line.strip() for line in stdout.split('\n')
                if line.strip() and not line.endswith('.cfg') 
                and '.backup' not in line and line.strip() != executable]
    
    def get_active_firmware(self, stand_name: str) -> Optional[str]:
        """Возвращает имя активной прошивки"""
        if not self.can_flash(stand_name) or not self.bc.is_connected(stand_name):
            return None
        
        paths = self.KNOWN_BOARDS[stand_name]['paths']
        success, stdout, stderr = self.bc.execute_command(
            stand_name,
            f"readlink {paths['firmware_dir']}/{paths['executable']} 2>/dev/null"
        )
        
        return os.path.basename(stdout.strip()) if success and stdout.strip() else None
    
    # ============================================================
    # ЗАПУСК / ОСТАНОВКА ПРОЦЕССА
    # ============================================================
    
    def start_process(self, stand_name: str, path: str = None) -> Dict:
        """Запускает исполняемый файл на плате"""
        if not self.can_flash(stand_name):
            return {'success': False, 'error': f'Запуск процессов недоступен для {stand_name}'}
        
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        board_config = self.KNOWN_BOARDS[stand_name]
        paths = board_config['paths']
        executable = paths['executable']
        work_dir = path or paths['firmware_dir']
        
        # Проверяем, не запущен ли уже
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"pgrep -f {executable} 2>/dev/null"
        )
        if success and stdout.strip():
            return {
                'success': False,
                'error': f'Процесс {executable} уже запущен (PID: {stdout.strip()})',
                'already_running': True
            }
        
        self.logger.info(f"Запуск {executable} на {stand_name}...")
        
        command = f"cd {work_dir} && nohup ./{executable} > /dev/null 2>&1 & echo $!"
        success, stdout, stderr = self.bc.execute_command(stand_name, command)
        
        if not success:
            return {'success': False, 'error': stderr}
        
        pid = stdout.strip()
        time.sleep(1)
        
        success, stdout, stderr = self.bc.execute_command(stand_name, f"kill -0 {pid} 2>&1")
        
        if success:
            if stand_name in self.boards:
                self.boards[stand_name].status = "running"
            
            return {
                'success': True,
                'message': f'{executable} запущен (PID: {pid})',
                'pid': pid
            }
        else:
            return {
                'success': False,
                'error': 'Процесс запустился, но сразу завершился',
                'pid': pid
            }
    
    def stop_process(self, stand_name: str, force: bool = False) -> Dict:
        """
        Останавливает процесс на плате.
        slay -> SIGTERM -> SIGKILL
        """
        if not self.can_flash(stand_name):
            return {'success': False, 'error': f'Остановка процессов недоступна для {stand_name}'}
        
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        executable = self.KNOWN_BOARDS[stand_name]['paths']['executable']
        
        self.logger.info(f"Остановка {executable} на {stand_name}...")
        
        # Проверяем, запущен ли
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"pgrep -f {executable} 2>/dev/null"
        )
        
        if not success or not stdout.strip():
            return {
                'success': True,
                'message': f'{executable} не был запущен',
                'was_running': False
            }
        
        pids = stdout.strip().split('\n')
        
        # Пробуем slay
        if not force:
            self.bc.execute_command(stand_name, f"slay {executable} 2>/dev/null")
            time.sleep(1)
            
            success, stdout, stderr = self.bc.execute_command(
                stand_name, f"pgrep -f {executable} 2>/dev/null"
            )
            if not success or not stdout.strip():
                if stand_name in self.boards:
                    self.boards[stand_name].status = "ready"
                return {'success': True, 'message': f'{executable} остановлен через slay', 'method': 'slay'}
        
        # SIGTERM или SIGKILL
        signal = "KILL" if force else "TERM"
        self.bc.execute_command(stand_name, f"pkill -{signal} -f {executable} 2>/dev/null")
        time.sleep(1)
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"pgrep -f {executable} 2>/dev/null"
        )
        
        if not success or not stdout.strip():
            if stand_name in self.boards:
                self.boards[stand_name].status = "ready"
            return {'success': True, 'message': f'{executable} остановлен через SIG{signal}', 'method': signal}
        
        # Если не сработало - SIGKILL
        if not force:
            self.bc.execute_command(stand_name, f"pkill -KILL -f {executable} 2>/dev/null")
            time.sleep(1)
            
            success, stdout, stderr = self.bc.execute_command(
                stand_name, f"pgrep -f {executable} 2>/dev/null"
            )
            
            if not success or not stdout.strip():
                if stand_name in self.boards:
                    self.boards[stand_name].status = "ready"
                return {'success': True, 'message': f'{executable} остановлен через SIGKILL', 'method': 'SIGKILL'}
        
        return {'success': False, 'error': f'Не удалось остановить {executable}'}
    
    def restart_process(self, stand_name: str, path: str = None) -> Dict:
        """Перезапускает процесс"""
        self.logger.info(f"Перезапуск процесса на {stand_name}...")
        
        stop_result = self.stop_process(stand_name)
        time.sleep(2)
        start_result = self.start_process(stand_name, path)
        
        return {
            'success': start_result['success'],
            'stop': stop_result,
            'start': start_result,
            'message': 'Процесс перезапущен' if start_result['success'] else 'Ошибка перезапуска'
        }
    
    # ============================================================
    # СКРИПТЫ
    # ============================================================
    
    def run_script(self, stand_name: str, script_name: str,
                   args: str = "", timeout: int = 30) -> Dict:
        """Запускает скрипт на стенде"""
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        board_config = self.KNOWN_BOARDS.get(stand_name, {})
        scripts_dir = board_config.get('paths', {}).get('scripts', '/home/pkrv/scripts')
        
        script_path = script_name if script_name.startswith('/') else f"{scripts_dir}/{script_name}"
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"test -f {script_path} && echo 'EXISTS'"
        )
        
        if not success or 'EXISTS' not in stdout:
            return {'success': False, 'error': f'Скрипт не найден: {script_path}'}
        
        self.bc.execute_command(stand_name, f"chmod +x {script_path}")
        
        command = f"{script_path} {args}" if args else script_path
        success, stdout, stderr = self.bc.execute_command(stand_name, command, timeout=timeout)
        
        self.script_history.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stand': stand_name,
            'script': script_path,
            'success': success
        })
        
        return {
            'success': success,
            'script': script_path,
            'stdout': stdout,
            'stderr': stderr
        }
    
    def list_scripts(self, stand_name: str) -> List[Dict]:
        """Список скриптов на стенде"""
        if not self.bc.is_connected(stand_name):
            return []
        
        board_config = self.KNOWN_BOARDS.get(stand_name, {})
        scripts_dir = board_config.get('paths', {}).get('scripts', '/home/pkrv/scripts')
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"ls -la {scripts_dir}/*.sh {scripts_dir}/*.py 2>/dev/null"
        )
        
        if not success:
            return []
        
        scripts = []
        for line in stdout.strip().split('\n'):
            if line.startswith('-'):
                parts = line.split()
                if len(parts) >= 8:
                    name = ' '.join(parts[7:])
                    scripts.append({
                        'name': name,
                        'path': f"{scripts_dir}/{name}",
                        'size': int(parts[4]) if parts[4].isdigit() else 0
                    })
        
        return scripts
    
    # ============================================================
    # ЛОГИ
    # ============================================================
    
    def read_logs(self, stand_name: str, lines: int = 50) -> Dict:
        """Читает последние строки лога"""
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        board_config = self.KNOWN_BOARDS.get(stand_name, {})
        log_path = board_config.get('paths', {}).get('logs', '/var/log/1po2_1n.log')
        
        success, stdout, stderr = self.bc.execute_command(
            stand_name, f"tail -n {lines} {log_path} 2>/dev/null"
        )
        
        return {
            'success': success,
            'log_file': log_path,
            'lines': stdout.strip().split('\n') if stdout else []
        }
    
    # ============================================================
    # ДИАГНОСТИКА
    # ============================================================
    
    def run_diagnostics(self, stand_name: str) -> Dict:
        """Полная диагностика платы"""
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        self.logger.info(f"Диагностика платы {stand_name}...")
        
        diag = {
            'stand': stand_name,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'board': self.check_board(stand_name),
            'system': self.get_system_info(stand_name)
        }
        
        if self.can_flash(stand_name):
            diag['firmwares'] = self.get_firmware_list(stand_name)
            diag['active_firmware'] = self.get_active_firmware(stand_name)
        
        return diag
    
    # ============================================================
    # ИНФОРМАЦИЯ
    # ============================================================
    
    def get_board_info(self, stand_name: str) -> Optional[Dict]:
        if stand_name in self.boards:
            return self.boards[stand_name].to_dict()
        return None
    
    def get_all_boards(self) -> Dict[str, Dict]:
        return {name: board.to_dict() for name, board in self.boards.items()}
    
    def get_history(self) -> Dict:
        return {
            'flash': self.flash_history[-20:],
            'script': self.script_history[-20:]
        }


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ BOARD INTERFACE")
    print("=" * 60)
    
    from bench_connector import BenchConnector
    
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(2)
    
    bi = BoardInterface(bc)
    
    print("\nДоступные платы:")
    for name, info in bi.get_all_boards().items():
        print(f"  {name}: {info['type']}")
    
    print("\nПримеры:")
    print("  bc.connect_to_stand('OrangePi')")
    print("  bi.browse_files('OrangePi', '/home/orangepi')")
    print("  bi.get_system_info('OrangePi')")
    print()
    print("  bc.connect_to_stand('ГОЗ')")
    print("  bi.flash_firmware('ГОЗ', 'mpo')")
    print("  bi.start_process('ГОЗ')")
    print("  bi.stop_process('ГОЗ')")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nЗавершение...")
        bc.stop_monitoring()
        bc.disconnect_all()
