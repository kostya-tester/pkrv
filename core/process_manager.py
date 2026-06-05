"""
Модуль управления процессами на стендах.
Просмотр, поиск, завершение процессов.
Защита от завершения системных процессов.
Работает на Windows и Linux через BenchConnector.
"""

import sys
import os
import time
import re
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.bench_connector import BenchConnector, LogManager
except ImportError:
    from bench_connector import BenchConnector, LogManager


# ============================================================
# СПИСОК ЗАЩИЩЕННЫХ ПРОЦЕССОВ (НЕЛЬЗЯ УБИТЬ)
# ============================================================

PROTECTED_PROCESSES = [
    # Системные процессы Linux
    "systemd", "init", "kthreadd", "ksoftirqd", "migration",
    "rcu_sched", "watchdog", "kworker", "kswapd", "khugepaged",
    "cron", "rsyslogd", "dbus-daemon", "agetty", "sshd",
    "udevd", "journald", "networkd", "resolvd", "acpid",
    
    # Критичные для системы
    "bash", "sh", "zsh", "getty", "login",
    "polkitd", "accounts-daemon", "upowerd",
    
    # SSH и сеть
    "sshd:", "ssh-agent", "dhclient", "wpa_supplicant",
    "NetworkManager", "netplan", "systemd-networkd",
    
    # Собственные процессы (чтобы не убить сам bench-менеджер)
    "python", "python3", "bench_manager",
]

# Процессы, которые требуют подтверждения перед убийством
WARNING_PROCESSES = [
    "apache2", "nginx", "mysql", "postgres", "mongod",
    "docker", "containerd", "kubelet", "kube-proxy",
    "firewalld", "iptables", "ufw",
]


class ProcessInfo:
    """Информация о процессе"""
    
    def __init__(self, pid: int, name: str, cpu: float = 0, mem: float = 0, 
                 user: str = "", status: str = "", cmdline: str = ""):
        self.pid = pid
        self.name = name
        self.cpu = cpu
        self.mem = mem
        self.user = user
        self.status = status
        self.cmdline = cmdline
        self.is_protected = self._check_protected()
        self.is_warning = self._check_warning()
    
    def _check_protected(self) -> bool:
        """Проверяет, защищен ли процесс"""
        name_lower = self.name.lower()
        cmd_lower = self.cmdline.lower()
        for protected in PROTECTED_PROCESSES:
            if protected.lower() in name_lower or protected.lower() in cmd_lower:
                return True
        return False
    
    def _check_warning(self) -> bool:
        """Проверяет, требует ли процесс подтверждения"""
        name_lower = self.name.lower()
        for warn in WARNING_PROCESSES:
            if warn.lower() in name_lower:
                return True
        return False
    
    def to_dict(self) -> Dict:
        return {
            'pid': self.pid,
            'name': self.name,
            'cpu': self.cpu,
            'mem': self.mem,
            'user': self.user,
            'status': self.status,
            'cmdline': self.cmdline[:100] if self.cmdline else '',
            'is_protected': self.is_protected,
            'is_warning': self.is_warning,
            'can_kill': not self.is_protected
        }
    
    def __repr__(self):
        return f"PID:{self.pid} {self.name} CPU:{self.cpu}% MEM:{self.mem}%"


class ProcessManager:
    """
    Менеджер процессов на стендах.
    
    Возможности:
    - Просмотр списка процессов
    - Поиск процессов по имени/PID
    - Завершение процессов (SIGTERM, SIGKILL)
    - Защита от завершения системных процессов
    - Мониторинг CPU/памяти
    - Проверка результата завершения
    """
    
    def __init__(self, bench_connector: BenchConnector):
        """
        Args:
            bench_connector: Экземпляр BenchConnector
        """
        self.bc = bench_connector
        self.logger = LogManager()
        self.logger.setup(level="INFO")
        
        # История убитых процессов
        self.kill_history: List[Dict] = []
        
        # Защита: минимальный PID (процессы с меньшим PID нельзя убить без флага force)
        self.protected_pid_threshold = 1000
        
        # Флаг для отключения защиты (force mode)
        self.force_mode = False
    
    # ============================================================
    # ПОЛУЧЕНИЕ СПИСКА ПРОЦЕССОВ
    # ============================================================
    
    def get_process_list(self, stand_name: str, sort_by: str = "cpu") -> List[ProcessInfo]:
        """
        Получает список всех процессов на стенде.
        
        Args:
            stand_name: Имя стенда
            sort_by: Сортировка (cpu, mem, pid, name)
            
        Returns:
            Список ProcessInfo
        """
        if not self.bc.is_connected(stand_name):
            self.logger.error(f"Нет подключения к {stand_name}")
            return []
        
        # Команда для получения процессов с CPU и памятью
        command = "ps aux --no-headers 2>/dev/null"
        
        success, stdout, stderr = self.bc.execute_command(stand_name, command, timeout=10)
        
        if not success or not stdout.strip():
            self.logger.error(f"Ошибка получения процессов: {stderr}")
            return []
        
        processes = []
        for line in stdout.strip().split('\n'):
            proc = self._parse_ps_line(line)
            if proc:
                processes.append(proc)
        
        # Сортировка
        if sort_by == "cpu":
            processes.sort(key=lambda p: p.cpu, reverse=True)
        elif sort_by == "mem":
            processes.sort(key=lambda p: p.mem, reverse=True)
        elif sort_by == "pid":
            processes.sort(key=lambda p: p.pid)
        elif sort_by == "name":
            processes.sort(key=lambda p: p.name.lower())
        
        return processes
    
    def _parse_ps_line(self, line: str) -> Optional[ProcessInfo]:
        """Парсит строку вывода ps aux"""
        if not line.strip():
            return None
        
        parts = line.split(None, 10)
        if len(parts) < 11:
            return None
        
        try:
            user = parts[0]
            pid = int(parts[1])
            cpu = float(parts[2])
            mem = float(parts[3])
            status = parts[7] if len(parts) > 7 else ""
            cmdline = parts[10] if len(parts) > 10 else ""
            
            # Имя процесса - последняя часть cmdline или команда
            name = cmdline.split('/')[-1] if '/' in cmdline else cmdline.split()[0] if cmdline else parts[10]
            if not name:
                name = f"PID:{pid}"
            
            return ProcessInfo(pid, name, cpu, mem, user, status, cmdline)
        except (ValueError, IndexError):
            return None
    
    # ============================================================
    # ПОИСК ПРОЦЕССОВ
    # ============================================================
    
    def find_by_name(self, stand_name: str, process_name: str) -> List[ProcessInfo]:
        """
        Находит процессы по имени (частичное совпадение).
        
        Args:
            stand_name: Имя стенда
            process_name: Имя или часть имени процесса
            
        Returns:
            Список найденных процессов
        """
        all_processes = self.get_process_list(stand_name)
        
        found = []
        search_lower = process_name.lower()
        
        for proc in all_processes:
            if search_lower in proc.name.lower() or search_lower in proc.cmdline.lower():
                found.append(proc)
        
        return found
    
    def find_by_pid(self, stand_name: str, pid: int) -> Optional[ProcessInfo]:
        """
        Находит процесс по PID.
        
        Args:
            stand_name: Имя стенда
            pid: PID процесса
            
        Returns:
            ProcessInfo или None
        """
        all_processes = self.get_process_list(stand_name)
        
        for proc in all_processes:
            if proc.pid == pid:
                return proc
        
        return None
    
    def search_processes(self, stand_name: str, query: str) -> List[ProcessInfo]:
        """
        Универсальный поиск процессов.
        Принимает PID (число) или имя (строка).
        
        Args:
            stand_name: Имя стенда
            query: PID или имя процесса
            
        Returns:
            Список найденных процессов
        """
        # Проверяем, число ли это
        try:
            pid = int(query)
            proc = self.find_by_pid(stand_name, pid)
            return [proc] if proc else []
        except ValueError:
            return self.find_by_name(stand_name, query)
    
    # ============================================================
    # ЗАВЕРШЕНИЕ ПРОЦЕССОВ
    # ============================================================
    
    def kill_process(self, stand_name: str, process_identifier: str,
                     signal: str = "SIGTERM", force: bool = False) -> Dict:
        """
        Завершает процесс на стенде.
        
        Args:
            stand_name: Имя стенда
            process_identifier: PID (число) или имя процесса
            signal: Сигнал (SIGTERM - мягкое завершение, SIGKILL - принудительное)
            force: Игнорировать защиту (использовать осторожно!)
            
        Returns:
            Словарь с результатом операции
        """
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        # Находим процессы
        processes = self.search_processes(stand_name, process_identifier)
        
        if not processes:
            return {
                'success': False,
                'error': f'Процесс "{process_identifier}" не найден на {stand_name}'
            }
        
        # Проверяем защиту
        if not force:
            for proc in processes:
                if proc.is_protected:
                    return {
                        'success': False,
                        'error': f'Процесс {proc.name} (PID:{proc.pid}) защищен от завершения!',
                        'protected': True,
                        'hint': 'Используйте force=True для принудительного завершения'
                    }
                
                if proc.is_warning:
                    self.logger.warning(f"Процесс {proc.name} (PID:{proc.pid}) требует осторожности!")
        
        # Определяем команду для kill
        signal_map = {
            "SIGTERM": "TERM",
            "SIGKILL": "KILL",
            "SIGINT": "INT",
            "SIGHUP": "HUP",
            "SIGSTOP": "STOP",
            "SIGCONT": "CONT",
            "TERM": "TERM",
            "KILL": "KILL",
            "INT": "INT",
            "HUP": "HUP",
            "STOP": "STOP",
            "CONT": "CONT",
        }
        
        kill_signal = signal_map.get(signal.upper(), "TERM")
        
        results = []
        killed_count = 0
        failed_count = 0
        
        for proc in processes:
            self.logger.info(f"Завершение процесса: {proc.name} (PID:{proc.pid}) сигналом {kill_signal}")
            
            # Выполняем kill
            command = f"kill -{kill_signal} {proc.pid} 2>&1"
            success, stdout, stderr = self.bc.execute_command(stand_name, command, timeout=10)
            
            # Ждем и проверяем
            time.sleep(0.5)
            
            # Проверяем, завершился ли процесс
            check_command = f"kill -0 {proc.pid} 2>&1"
            check_success, check_stdout, check_stderr = self.bc.execute_command(stand_name, check_command, timeout=5)
            
            is_dead = not check_success
            
            result_entry = {
                'pid': proc.pid,
                'name': proc.name,
                'signal': kill_signal,
                'killed': is_dead,
                'error': stderr if not success else None
            }
            results.append(result_entry)
            
            if is_dead:
                killed_count += 1
                self.logger.info(f"  Процесс {proc.name} (PID:{proc.pid}) успешно завершен")
            else:
                failed_count += 1
                self.logger.warning(f"  Не удалось завершить {proc.name} (PID:{proc.pid})")
                
                # Если не получилось SIGTERM, пробуем SIGKILL
                if kill_signal == "TERM" and not force:
                    self.logger.info(f"  Пробуем SIGKILL для {proc.name}...")
                    force_kill_cmd = f"kill -KILL {proc.pid} 2>&1"
                    fk_success, fk_stdout, fk_stderr = self.bc.execute_command(stand_name, force_kill_cmd, timeout=10)
                    
                    time.sleep(0.3)
                    fk_check, _, _ = self.bc.execute_command(stand_name, f"kill -0 {proc.pid} 2>&1", timeout=5)
                    
                    if not fk_check:
                        result_entry['killed'] = True
                        result_entry['signal'] = 'KILL'
                        killed_count += 1
                        failed_count -= 1
                        self.logger.info(f"  Процесс {proc.name} завершен через SIGKILL")
        
        # Сохраняем в историю
        history_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stand': stand_name,
            'target': process_identifier,
            'signal': kill_signal,
            'force': force,
            'processes': results,
            'killed_count': killed_count,
            'failed_count': failed_count
        }
        self.kill_history.append(history_entry)
        
        # Формируем ответ
        if len(processes) == 1:
            proc = processes[0]
            if killed_count == 1:
                return {
                    'success': True,
                    'message': f'Процесс "{proc.name}" (PID:{proc.pid}) успешно завершен',
                    'process': proc.to_dict(),
                    'results': results
                }
            else:
                return {
                    'success': False,
                    'error': f'Не удалось завершить процесс "{proc.name}" (PID:{proc.pid})',
                    'process': proc.to_dict(),
                    'results': results
                }
        else:
            return {
                'success': failed_count == 0,
                'message': f'Завершено процессов: {killed_count}, ошибок: {failed_count}',
                'killed_count': killed_count,
                'failed_count': failed_count,
                'results': results
            }
    
    def kill_by_name(self, stand_name: str, process_name: str,
                     signal: str = "SIGTERM", force: bool = False) -> Dict:
        """Завершает все процессы с указанным именем"""
        return self.kill_process(stand_name, process_name, signal, force)
    
    def kill_by_pid(self, stand_name: str, pid: int,
                    signal: str = "SIGTERM", force: bool = False) -> Dict:
        """Завершает процесс по PID"""
        return self.kill_process(stand_name, str(pid), signal, force)
    
    def kill_slay(self, stand_name: str, process_name: str) -> Dict:
        """
        Использует команду slay для завершения процесса.
        slay - более агрессивный способ завершения.
        
        Args:
            stand_name: Имя стенда
            process_name: Имя процесса
            
        Returns:
            Результат операции
        """
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        self.logger.info(f"Завершение через slay: {process_name} на {stand_name}")
        
        # Сначала пробуем slay
        command = f"slay {process_name} 2>&1"
        success, stdout, stderr = self.bc.execute_command(stand_name, command, timeout=10)
        
        if success:
            time.sleep(0.5)
            # Проверяем, что процесс умер
            remaining = self.find_by_name(stand_name, process_name)
            if not remaining:
                self.logger.info(f"Процесс {process_name} успешно завершен через slay")
                
                history_entry = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'stand': stand_name,
                    'target': process_name,
                    'signal': 'SLAY',
                    'force': True,
                    'killed_count': 1,
                    'failed_count': 0
                }
                self.kill_history.append(history_entry)
                
                return {
                    'success': True,
                    'message': f'Процесс "{process_name}" завершен через slay'
                }
            
        # Если slay не сработал, пробуем kill
        self.logger.warning(f"slay не сработал, пробуем kill...")
        return self.kill_process(stand_name, process_name, "SIGKILL", force=True)
    
    # ============================================================
    # ЗАПУСК ПРОЦЕССОВ
    # ============================================================
    
    def start_process(self, stand_name: str, command: str, 
                      background: bool = True) -> Dict:
        """
        Запускает процесс на стенде.
        
        Args:
            stand_name: Имя стенда
            command: Команда для запуска
            background: Запустить в фоне
            
        Returns:
            Результат с PID если удалось запустить
        """
        if not self.bc.is_connected(stand_name):
            return {'success': False, 'error': f'Нет подключения к {stand_name}'}
        
        # Формируем команду
        if background:
            full_command = f"nohup {command} > /dev/null 2>&1 & echo $!"
        else:
            full_command = command
        
        self.logger.info(f"Запуск процесса на {stand_name}: {command}")
        
        success, stdout, stderr = self.bc.execute_command(stand_name, full_command, timeout=10)
        
        if success:
            # Получаем PID для фоновых процессов
            pid = None
            if background and stdout.strip().isdigit():
                pid = int(stdout.strip())
                self.logger.info(f"Процесс запущен с PID: {pid}")
                
                # Проверяем, что процесс действительно запущен
                time.sleep(0.3)
                check_success, _, _ = self.bc.execute_command(
                    stand_name, f"kill -0 {pid} 2>&1", timeout=5
                )
                
                if not check_success:
                    return {
                        'success': False,
                        'error': 'Процесс запустился, но сразу завершился',
                        'pid': pid
                    }
            
            return {
                'success': True,
                'message': f'Процесс запущен: {command}',
                'pid': pid,
                'stdout': stdout.strip(),
                'stderr': stderr.strip()
            }
        else:
            self.logger.error(f"Ошибка запуска: {stderr}")
            return {
                'success': False,
                'error': stderr.strip() or 'Неизвестная ошибка запуска'
            }
    
    def start_1po2_1n(self, stand_name: str, path: str = ".") -> Dict:
        """
        Запускает исполняемый файл 1po2_1n на стенде.
        
        Args:
            stand_name: Имя стенда
            path: Путь к исполняемому файлу
            
        Returns:
            Результат запуска
        """
        command = f"cd {path} && ./1po2_1n"
        return self.start_process(stand_name, command)
    
    def stop_1po2_1n(self, stand_name: str) -> Dict:
        """
        Останавливает процесс 1po2_1n на стенде.
        Сначала пробует slay, затем kill.
        
        Args:
            stand_name: Имя стенда
            
        Returns:
            Результат операции
        """
        return self.kill_slay(stand_name, "1po2_1n")
    
    def restart_1po2_1n(self, stand_name: str, path: str = ".") -> Dict:
        """
        Перезапускает 1po2_1n: останавливает и запускает заново.
        
        Args:
            stand_name: Имя стенда
            path: Путь к исполняемому файлу
            
        Returns:
            Результат операции
        """
        self.logger.info(f"Перезапуск 1po2_1n на {stand_name}")
        
        # Останавливаем
        stop_result = self.stop_1po2_1n(stand_name)
        
        # Ждем
        time.sleep(1)
        
        # Запускаем
        start_result = self.start_1po2_1n(stand_name, path)
        
        return {
            'success': start_result['success'],
            'stop_result': stop_result,
            'start_result': start_result,
            'message': 'Процесс 1po2_1n перезапущен' if start_result['success'] else 'Ошибка перезапуска'
        }
    
    # ============================================================
    # МОНИТОРИНГ ПРОЦЕССА
    # ============================================================
    
    def monitor_process(self, stand_name: str, process_identifier: str,
                        interval: int = 2, duration: int = 10) -> List[Dict]:
        """
        Мониторит потребление ресурсов процессом.
        
        Args:
            stand_name: Имя стенда
            process_identifier: PID или имя процесса
            interval: Интервал опроса (сек)
            duration: Длительность мониторинга (сек)
            
        Returns:
            Список снимков состояния процесса
        """
        if not self.bc.is_connected(stand_name):
            return []
        
        snapshots = []
        start_time = time.time()
        
        self.logger.info(f"Мониторинг процесса {process_identifier} на {stand_name} ({duration}с)...")
        
        while time.time() - start_time < duration:
            processes = self.search_processes(stand_name, process_identifier)
            
            if not processes:
                self.logger.warning(f"Процесс {process_identifier} не найден (возможно, завершился)")
                break
            
            for proc in processes:
                snapshots.append({
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'pid': proc.pid,
                    'name': proc.name,
                    'cpu': proc.cpu,
                    'mem': proc.mem,
                    'status': proc.status
                })
            
            time.sleep(interval)
        
        return snapshots
    
    # ============================================================
    # ПРОВЕРКА СОСТОЯНИЯ ПРОЦЕССА
    # ============================================================
    
    def is_running(self, stand_name: str, process_identifier: str) -> bool:
        """
        Проверяет, запущен ли процесс.
        
        Args:
            stand_name: Имя стенда
            process_identifier: PID или имя процесса
            
        Returns:
            True если процесс запущен
        """
        processes = self.search_processes(stand_name, process_identifier)
        return len(processes) > 0
    
    def check_1po2_1n(self, stand_name: str) -> Dict:
        """
        Проверяет состояние процесса 1po2_1n.
        
        Returns:
            Информация о процессе
        """
        processes = self.find_by_name(stand_name, "1po2_1n")
        
        if not processes:
            return {
                'running': False,
                'message': 'Процесс 1po2_1n не запущен'
            }
        
        return {
            'running': True,
            'message': f'Процесс 1po2_1n запущен',
            'instances': len(processes),
            'processes': [p.to_dict() for p in processes]
        }
    
    # ============================================================
    # ТОП ПРОЦЕССОВ
    # ============================================================
    
    def get_top_processes(self, stand_name: str, count: int = 10) -> List[ProcessInfo]:
        """
        Возвращает топ процессов по CPU.
        
        Args:
            stand_name: Имя стенда
            count: Количество процессов
            
        Returns:
            Список процессов
        """
        processes = self.get_process_list(stand_name, sort_by="cpu")
        return processes[:count]
    
    def get_heavy_processes(self, stand_name: str, cpu_threshold: float = 50.0,
                            mem_threshold: float = 20.0) -> List[ProcessInfo]:
        """
        Находит процессы с высоким потреблением ресурсов.
        
        Args:
            stand_name: Имя стенда
            cpu_threshold: Порог CPU (%)
            mem_threshold: Порог памяти (%)
            
        Returns:
            Список тяжелых процессов
        """
        processes = self.get_process_list(stand_name)
        
        heavy = []
        for proc in processes:
            if proc.cpu > cpu_threshold or proc.mem > mem_threshold:
                heavy.append(proc)
        
        return heavy
    
    # ============================================================
    # ИСТОРИЯ
    # ============================================================
    
    def get_kill_history(self, limit: int = 20) -> List[Dict]:
        """Возвращает историю завершенных процессов"""
        return self.kill_history[-limit:]
    
    def clear_kill_history(self):
        """Очищает историю"""
        self.kill_history.clear()
        self.logger.info("История очищена")
    
    # ============================================================
    # ЗАЩИТА
    # ============================================================
    
    def add_protected_process(self, process_name: str):
        """Добавляет процесс в список защищенных"""
        if process_name.lower() not in [p.lower() for p in PROTECTED_PROCESSES]:
            PROTECTED_PROCESSES.append(process_name)
            self.logger.info(f"Добавлен в защищенные: {process_name}")
    
    def remove_protected_process(self, process_name: str):
        """Удаляет процесс из списка защищенных"""
        for p in PROTECTED_PROCESSES:
            if p.lower() == process_name.lower():
                PROTECTED_PROCESSES.remove(p)
                self.logger.info(f"Удален из защищенных: {process_name}")
                return
    
    def set_force_mode(self, enabled: bool):
        """Включает/выключает режим принудительного завершения"""
        self.force_mode = enabled
        if enabled:
            self.logger.warning("РЕЖИМ FORCE ВКЛЮЧЕН - защита отключена!")
        else:
            self.logger.info("Режим force выключен - защита включена")
    
    def get_protected_list(self) -> List[str]:
        """Возвращает список защищенных процессов"""
        return PROTECTED_PROCESSES.copy()


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ PROCESS MANAGER")
    print("=" * 60)
    
    from bench_connector import BenchConnector
    
    bc = BenchConnector()
    bc.start_monitoring()
    time.sleep(2)
    
    pm = ProcessManager(bc)
    
    print("\nДоступные стенды:")
    for name, info in bc.get_all_stands_info().items():
        status = "ONLINE" if info['status'] == 'online' else "OFFLINE"
        print(f"  {name}: {status}")
    
    # Пример использования:
    print("\n" + "=" * 60)
    print("Примеры команд:")
    print("=" * 60)
    print("""
    # Подключиться к стенду
    bc.connect_to_stand('ГОЗ')
    
    # Список процессов
    processes = pm.get_process_list('ГОЗ')
    
    # Топ-10 по CPU
    top = pm.get_top_processes('ГОЗ', 10)
    
    # Найти процесс
    found = pm.find_by_name('ГОЗ', '1po2_1n')
    
    # Проверить, запущен ли
    status = pm.check_1po2_1n('ГОЗ')
    
    # Остановить 1po2_1n
    pm.stop_1po2_1n('ГОЗ')
    
    # Запустить 1po2_1n
    pm.start_1po2_1n('ГОЗ', path='/home/pkrv/fpo_cfg')
    
    # Перезапустить
    pm.restart_1po2_1n('ГОЗ', path='/home/pkrv/fpo_cfg')
    
    # Убить любой процесс (с защитой)
    pm.kill_process('ГОЗ', 'my_app', signal='SIGTERM')
    
    # Убить принудительно (игнорируя защиту)
    pm.kill_process('ГОЗ', 'my_app', signal='SIGKILL', force=True)
    
    # Мониторить процесс 10 секунд
    snapshots = pm.monitor_process('ГОЗ', '1po2_1n', interval=1, duration=10)
    
    # История завершений
    history = pm.get_kill_history()
    """)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nЗавершение...")
        bc.stop_monitoring()
        bc.disconnect_all()
