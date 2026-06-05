"""
Панель просмотра и управления процессами на стендах.
Поиск, завершение (kill/slay), запуск, мониторинг.
"""

import sys
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QLineEdit,
    QHeaderView, QGroupBox, QSplitter, QTextEdit, QMessageBox,
    QCheckBox, QProgressBar, QFrame, QAbstractItemView
)
from PyQt5.QtCore import (
    Qt, QTimer, pyqtSignal, QThread
)
from PyQt5.QtGui import (
    QColor, QFont, QBrush
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.bench_connector import BenchConnector
    from core.process_manager import ProcessManager, ProcessInfo
    from logger.log_manager import LogManager
except ImportError:
    BenchConnector = None
    ProcessManager = None
    ProcessInfo = None
    LogManager = None


# ============================================================
# ПОТОК ОБНОВЛЕНИЯ ПРОЦЕССОВ
# ============================================================

class ProcessRefreshThread(QThread):
    """Поток для получения списка процессов без зависания GUI"""
    
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, pm, stand_name: str, sort_by: str = "cpu"):
        super().__init__()
        self.pm = pm
        self.stand_name = stand_name
        self.sort_by = sort_by
    
    def run(self):
        try:
            processes = self.pm.get_process_list(self.stand_name, sort_by=self.sort_by)
            self.finished.emit(processes)
        except Exception as e:
            self.error.emit(str(e))


class KillProcessThread(QThread):
    """Поток для завершения процесса"""
    
    finished = pyqtSignal(dict)
    
    def __init__(self, pm, stand_name: str, target: str, signal: str, force: bool):
        super().__init__()
        self.pm = pm
        self.stand_name = stand_name
        self.target = target
        self.signal = signal
        self.force = force
    
    def run(self):
        result = self.pm.kill_process(self.stand_name, self.target, self.signal, self.force)
        self.finished.emit(result)


# ============================================================
# ПАНЕЛЬ ПРОЦЕССОВ
# ============================================================

class ProcessViewer(QWidget):
    """
    Панель управления процессами на стендах.
    
    Возможности:
    - Просмотр списка процессов
    - Сортировка по CPU, памяти, PID, имени
    - Поиск процессов
    - Завершение (SIGTERM, SIGKILL, slay)
    - Запуск ./1po2_1n
    - Мониторинг потребления ресурсов
    - Защита от завершения системных процессов
    """
    
    def __init__(self, bench_connector=None, process_manager=None):
        super().__init__()
        self.bc = bench_connector
        self.pm = process_manager
        
        self.refresh_thread = None
        self.kill_thread = None
        self.current_processes: List[ProcessInfo] = []
        
        self.setup_ui()
        self.setup_timer()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # === ЗАГОЛОВОК ===
        title = QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ НА СТЕНДАХ")
        title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)
        
        # === ПАНЕЛЬ УПРАВЛЕНИЯ ===
        control_frame = QFrame()
        control_frame.setStyleSheet("""
            QFrame {
                background-color: #252545;
                border: 1px solid #3a3a6a;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        control_layout = QHBoxLayout(control_frame)
        control_layout.setSpacing(15)
        
        # Выбор стенда
        control_layout.addWidget(QLabel("Стенд:"))
        self.stand_combo = QComboBox()
        self.stand_combo.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
        self.stand_combo.currentTextChanged.connect(self.on_stand_changed)
        control_layout.addWidget(self.stand_combo)
        
        control_layout.addSpacing(20)
        
        # Сортировка
        control_layout.addWidget(QLabel("Сорт.:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["CPU", "Память", "PID", "Имя"])
        self.sort_combo.currentTextChanged.connect(self.refresh_processes)
        control_layout.addWidget(self.sort_combo)
        
        control_layout.addSpacing(20)
        
        # Поиск
        control_layout.addWidget(QLabel("Поиск:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("PID или имя процесса...")
        self.search_edit.setMinimumWidth(150)
        self.search_edit.textChanged.connect(self.filter_processes)
        control_layout.addWidget(self.search_edit)
        
        control_layout.addStretch()
        
        # Кнопка обновления
        refresh_btn = QPushButton("ОБНОВИТЬ")
        refresh_btn.clicked.connect(self.refresh_processes)
        control_layout.addWidget(refresh_btn)
        
        main_layout.addWidget(control_frame)
        
        # === ТАБЛИЦА ПРОЦЕССОВ ===
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(7)
        self.process_table.setHorizontalHeaderLabels([
            "PID", "Имя", "CPU %", "Память %", "Пользователь", "Статус", "Защита"
        ])
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.process_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.process_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.process_table.setAlternatingRowColors(True)
        self.process_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e32;
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                color: #e0e0e0;
                gridline-color: #2a2a4a;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #4a4ad2;
            }
            QHeaderView::section {
                background-color: #2a2a4a;
                color: #a0b0ff;
                padding: 6px;
                border: none;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        self.process_table.setMinimumHeight(250)
        main_layout.addWidget(self.process_table)
        
        # === СТАТУС ===
        self.status_label = QLabel("Процессы не загружены")
        self.status_label.setStyleSheet("color: #6a6aaa; padding: 5px;")
        main_layout.addWidget(self.status_label)
        
        # === КНОПКИ ДЕЙСТВИЙ ===
        actions_frame = QFrame()
        actions_frame.setStyleSheet("""
            QFrame {
                background-color: #252545;
                border: 1px solid #3a3a6a;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setSpacing(10)
        
        # Завершение
        self.kill_btn = QPushButton("ЗАВЕРШИТЬ (SIGTERM)")
        self.kill_btn.clicked.connect(lambda: self.kill_selected("SIGTERM"))
        actions_layout.addWidget(self.kill_btn)
        
        self.force_kill_btn = QPushButton("УБИТЬ (SIGKILL)")
        self.force_kill_btn.setObjectName("btnCancel")
        self.force_kill_btn.clicked.connect(lambda: self.kill_selected("SIGKILL"))
        actions_layout.addWidget(self.force_kill_btn)
        
        self.slay_btn = QPushButton("SLAY")
        self.slay_btn.clicked.connect(self.slay_selected)
        actions_layout.addWidget(self.slay_btn)
        
        actions_layout.addSpacing(20)
        
        # Запуск 1po2_1n
        self.start_btn = QPushButton("ЗАПУСТИТЬ ./1po2_1n")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66bb6a;
            }
        """)
        self.start_btn.clicked.connect(self.start_1po2_1n)
        actions_layout.addWidget(self.start_btn)
        
        self.restart_btn = QPushButton("ПЕРЕЗАПУСТИТЬ")
        self.restart_btn.clicked.connect(self.restart_1po2_1n)
        actions_layout.addWidget(self.restart_btn)
        
        actions_layout.addStretch()
        
        # Защита
        self.force_cb = QCheckBox("Force mode (отключить защиту)")
        self.force_cb.setStyleSheet("color: #ff9800; font-weight: bold;")
        actions_layout.addWidget(self.force_cb)
        
        main_layout.addWidget(actions_frame)
        
        # === ПРОГРЕСС ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # === ЛОГ ===
        log_group = QGroupBox("Лог операций")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a2e;
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                color: #a0a0c0;
                font-family: 'Consolas', monospace;
                font-size: 10px;
            }
        """)
        log_layout.addWidget(self.log_text)
        
        clear_log_btn = QPushButton("ОЧИСТИТЬ ЛОГ")
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_layout.addWidget(clear_log_btn)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
    
    def setup_timer(self):
        """Таймер автообновления"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_processes)
        self.timer.start(10000)  # каждые 10 секунд
        
        self.auto_refresh_cb = QCheckBox("Автообновление")
        self.auto_refresh_cb.setChecked(True)
        self.auto_refresh_cb.toggled.connect(
            lambda checked: self.timer.start(10000) if checked else self.timer.stop()
        )
        # Добавим чекбокс перед статусом (в layout)
        # Уже есть в UI, можно не добавлять повторно
    
    def set_managers(self, bc, pm):
        """Устанавливает менеджеры"""
        self.bc = bc
        self.pm = pm
        self.update_stand_list()
    
    def update_stand_list(self):
        """Обновляет список стендов в комбобоксе"""
        if self.bc:
            self.stand_combo.clear()
            for stand_name in self.bc.stands:
                self.stand_combo.addItem(stand_name)
    
    # ============================================================
    # ОБНОВЛЕНИЕ ПРОЦЕССОВ
    # ============================================================
    
    def on_stand_changed(self, stand_name: str):
        """Стенд изменен"""
        self.refresh_processes()
    
    def refresh_processes(self):
        """Обновляет список процессов"""
        if not self.pm:
            self.add_log("ProcessManager не настроен")
            return
        
        stand_name = self.stand_combo.currentText()
        if not stand_name:
            return
        
        if not self.bc or not self.bc.is_connected(stand_name):
            self.status_label.setText(f"Стенд {stand_name} не подключен")
            self.process_table.setRowCount(0)
            return
        
        sort_map = {"CPU": "cpu", "Память": "mem", "PID": "pid", "Имя": "name"}
        sort_by = sort_map.get(self.sort_combo.currentText(), "cpu")
        
        self.status_label.setText("Загрузка процессов...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)  # бесконечный прогресс
        
        self.refresh_thread = ProcessRefreshThread(self.pm, stand_name, sort_by)
        self.refresh_thread.finished.connect(self.on_processes_loaded)
        self.refresh_thread.error.connect(self.on_process_error)
        self.refresh_thread.start()
    
    def on_processes_loaded(self, processes: List[ProcessInfo]):
        """Процессы загружены"""
        self.current_processes = processes
        self.filter_processes()
        
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Загружено процессов: {len(processes)}")
        
        # Статистика
        total_cpu = sum(p.cpu for p in processes)
        total_mem = sum(p.mem for p in processes)
        self.add_log(f"Обновлено: {len(processes)} процессов | CPU: {total_cpu:.1f}% | MEM: {total_mem:.1f}%")
    
    def on_process_error(self, error: str):
        """Ошибка загрузки"""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Ошибка: {error}")
        self.add_log(f"[ОШИБКА] {error}")
    
    def filter_processes(self):
        """Фильтрует и отображает процессы"""
        search = self.search_edit.text().strip().lower()
        
        if search:
            filtered = []
            for p in self.current_processes:
                try:
                    pid = int(search)
                    if p.pid == pid:
                        filtered.append(p)
                        continue
                except ValueError:
                    pass
                
                if search in p.name.lower() or search in p.cmdline.lower():
                    filtered.append(p)
        else:
            filtered = self.current_processes
        
        self.display_processes(filtered)
    
    def display_processes(self, processes: List[ProcessInfo]):
        """Отображает процессы в таблице"""
        self.process_table.setRowCount(len(processes))
        
        for row, proc in enumerate(processes):
            # PID
            pid_item = QTableWidgetItem(str(proc.pid))
            pid_item.setTextAlignment(Qt.AlignCenter)
            self.process_table.setItem(row, 0, pid_item)
            
            # Имя
            name_item = QTableWidgetItem(proc.name)
            self.process_table.setItem(row, 1, name_item)
            
            # CPU
            cpu_item = QTableWidgetItem(f"{proc.cpu:.1f}")
            cpu_item.setTextAlignment(Qt.AlignCenter)
            if proc.cpu > 50:
                cpu_item.setForeground(QColor("#f44336"))
            elif proc.cpu > 20:
                cpu_item.setForeground(QColor("#ff9800"))
            self.process_table.setItem(row, 2, cpu_item)
            
            # Память
            mem_item = QTableWidgetItem(f"{proc.mem:.1f}")
            mem_item.setTextAlignment(Qt.AlignCenter)
            if proc.mem > 50:
                mem_item.setForeground(QColor("#f44336"))
            elif proc.mem > 20:
                mem_item.setForeground(QColor("#ff9800"))
            self.process_table.setItem(row, 3, mem_item)
            
            # Пользователь
            user_item = QTableWidgetItem(proc.user)
            self.process_table.setItem(row, 4, user_item)
            
            # Статус
            status_item = QTableWidgetItem(proc.status)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.process_table.setItem(row, 5, status_item)
            
            # Защита
            if proc.is_protected:
                protect_item = QTableWidgetItem("ЗАЩИЩЕН")
                protect_item.setForeground(QColor("#f44336"))
                protect_item.setFont(QFont("", -1, QFont.Bold))
            elif proc.is_warning:
                protect_item = QTableWidgetItem("ВАЖНЫЙ")
                protect_item.setForeground(QColor("#ff9800"))
            else:
                protect_item = QTableWidgetItem("-")
                protect_item.setForeground(QColor("#4caf50"))
            
            protect_item.setTextAlignment(Qt.AlignCenter)
            self.process_table.setItem(row, 6, protect_item)
        
        self.process_table.resizeColumnsToContents()
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    
    # ============================================================
    # ДЕЙСТВИЯ С ПРОЦЕССАМИ
    # ============================================================
    
    def get_selected_process(self) -> Optional[str]:
        """Возвращает PID или имя выбранного процесса"""
        row = self.process_table.currentRow()
        if row >= 0:
            pid_item = self.process_table.item(row, 0)
            if pid_item:
                return pid_item.text()
        return None
    
    def kill_selected(self, signal: str):
        """Завершает выбранный процесс"""
        target = self.get_selected_process()
        if not target:
            QMessageBox.warning(self, "Внимание", "Выберите процесс в таблице!")
            return
        
        stand_name = self.stand_combo.currentText()
        force = self.force_cb.isChecked()
        
        if not force:
            # Проверяем, не защищен ли процесс
            for proc in self.current_processes:
                if str(proc.pid) == target and proc.is_protected:
                    reply = QMessageBox.warning(
                        self, "Защищенный процесс!",
                        f"Процесс {proc.name} (PID:{proc.pid}) защищен!\n\n"
                        "Продолжить?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        return
                    force = True
                    break
        
        signal_name = "SIGTERM" if signal == "SIGTERM" else "SIGKILL"
        
        self.add_log(f"Завершение: {target} сигналом {signal_name} на {stand_name}...")
        
        self.kill_thread = KillProcessThread(self.pm, stand_name, target, signal, force)
        self.kill_thread.finished.connect(self.on_kill_finished)
        self.kill_thread.start()
        
        self.kill_btn.setEnabled(False)
        self.force_kill_btn.setEnabled(False)
        self.slay_btn.setEnabled(False)
    
    def slay_selected(self):
        """Завершает процесс через slay"""
        target = self.get_selected_process()
        if not target:
            QMessageBox.warning(self, "Внимание", "Выберите процесс в таблице!")
            return
        
        stand_name = self.stand_combo.currentText()
        
        self.add_log(f"Slay: {target} на {stand_name}...")
        
        if self.pm:
            result = self.pm.kill_slay(stand_name, target)
            self.on_kill_finished(result)
    
    def on_kill_finished(self, result: dict):
        """Обработчик завершения процесса"""
        self.kill_btn.setEnabled(True)
        self.force_kill_btn.setEnabled(True)
        self.slay_btn.setEnabled(True)
        
        if result.get('success'):
            self.add_log(f"  [OK] {result.get('message', 'Готово')}")
        else:
            self.add_log(f"  [FAIL] {result.get('error', 'Ошибка')}")
        
        # Обновляем список
        QTimer.singleShot(500, self.refresh_processes)
    
    def start_1po2_1n(self):
        """Запускает ./1po2_1n на стенде"""
        stand_name = self.stand_combo.currentText()
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        self.add_log(f"Запуск ./1po2_1n на {stand_name}...")
        
        if self.pm:
            result = self.pm.start_1po2_1n(stand_name)
            if result.get('success'):
                self.add_log(f"  [OK] {result.get('message', 'Запущен')}")
            else:
                self.add_log(f"  [FAIL] {result.get('error', 'Ошибка')}")
            
            QTimer.singleShot(1000, self.refresh_processes)
    
    def restart_1po2_1n(self):
        """Перезапускает ./1po2_1n"""
        stand_name = self.stand_combo.currentText()
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        reply = QMessageBox.question(
            self, "Перезапуск",
            f"Перезапустить 1po2_1n на {stand_name}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.add_log(f"Перезапуск 1po2_1n на {stand_name}...")
        
        if self.pm:
            result = self.pm.restart_1po2_1n(stand_name)
            if result.get('success'):
                self.add_log(f"  [OK] Процесс перезапущен")
            else:
                self.add_log(f"  [FAIL] {result.get('error', 'Ошибка')}")
            
            QTimer.singleShot(1000, self.refresh_processes)
    
    # ============================================================
    # ЛОГ
    # ============================================================
    
    def add_log(self, message: str):
        """Добавляет сообщение в лог"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ============================================================
# ТЕСТ
# ============================================================

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 12px;
        }
    """)
    
    viewer = ProcessViewer()
    viewer.setWindowTitle("Управление процессами")
    viewer.resize(800, 600)
    viewer.show()
    
    sys.exit(app.exec_())
