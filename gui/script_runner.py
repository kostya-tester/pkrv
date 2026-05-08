"""
Панель запуска скриптов на стендах и платах.
Выбор стенда, выбор скрипта, передача аргументов, просмотр вывода.
"""

import sys
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QGroupBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QSplitter,
    QCheckBox, QProgressBar, QFrame
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer
)
from PyQt5.QtGui import (
    QFont, QColor
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.bench_connector import BenchConnector
    from core.board_interface import BoardInterface
    from core.process_manager import ProcessManager
    from logger.log_manager import LogManager
except ImportError:
    BenchConnector = None
    BoardInterface = None
    ProcessManager = None
    LogManager = None


# ============================================================
# ПОТОК ВЫПОЛНЕНИЯ СКРИПТА
# ============================================================

class ScriptRunThread(QThread):
    """Поток для запуска скрипта без зависания GUI"""
    
    output = pyqtSignal(str)  # построчный вывод
    finished = pyqtSignal(dict)  # результат
    error = pyqtSignal(str)
    
    def __init__(self, bc, stand_name: str, script_path: str, args: str, timeout: int):
        super().__init__()
        self.bc = bc
        self.stand_name = stand_name
        self.script_path = script_path
        self.args = args
        self.timeout = timeout
        self.cancelled = False
    
    def run(self):
        try:
            command = f"{self.script_path} {self.args}" if self.args else self.script_path
            
            self.output.emit(f"$ {command}")
            self.output.emit("-" * 50)
            
            success, stdout, stderr = self.bc.execute_command(
                self.stand_name, command, timeout=self.timeout
            )
            
            if stdout:
                for line in stdout.split('\n'):
                    if self.cancelled:
                        break
                    self.output.emit(line)
            
            if stderr:
                for line in stderr.split('\n'):
                    if line.strip():
                        self.output.emit(f"[STDERR] {line}")
            
            self.output.emit("-" * 50)
            
            if success:
                self.output.emit("[ЗАВЕРШЕНО УСПЕШНО]")
            else:
                self.output.emit(f"[ЗАВЕРШЕНО С ОШИБКОЙ] код: {1 if not success else 0}")
            
            self.finished.emit({
                'success': success,
                'stdout': stdout,
                'stderr': stderr
            })
            
        except Exception as e:
            self.error.emit(str(e))
    
    def cancel(self):
        self.cancelled = True


# ============================================================
# ПАНЕЛЬ ЗАПУСКА СКРИПТОВ
# ============================================================

class ScriptRunner(QWidget):
    """
    Панель запуска скриптов на стендах.
    
    Возможности:
    - Выбор стенда
    - Список доступных скриптов
    - Пользовательский скрипт (ручной ввод)
    - Аргументы командной строки
    - Вывод в реальном времени
    - Отмена выполнения
    - История запусков
    """
    
    # Предустановленные скрипты
    DEFAULT_SCRIPTS = [
        {
            'name': 'Бэкап CVS',
            'script': '/home/pkrv/scripts/backup_cvs.sh',
            'description': 'Создание бэкапа папки CVS'
        },
        {
            'name': 'Прошивка платы',
            'script': '/home/pkrv/scripts/flash_firmware.py',
            'description': 'Прошивка платы указанной прошивкой'
        },
        {
            'name': 'Чтение датчиков',
            'script': '/home/pkrv/scripts/read_sensors.py',
            'description': 'Чтение данных с датчиков платы'
        },
        {
            'name': 'Запуск тестов',
            'script': '/home/pkrv/scripts/run_test.py',
            'description': 'Запуск тестового сценария'
        },
        {
            'name': 'Проверка конфигурации',
            'script': '/home/pkrv/scripts/check_config.sh',
            'description': 'Проверка файла 1po2_1n.cfg'
        },
        {
            'name': 'Перезапуск 1po2_1n',
            'script': '/home/pkrv/scripts/restart_1po2_1n.sh',
            'description': 'Остановка и запуск процесса'
        },
    ]
    
    def __init__(self, bench_connector=None, board_interface=None):
        super().__init__()
        self.bc = bench_connector
        self.bi = board_interface
        
        self.run_thread = None
        self.script_history: List[Dict] = []
        self.available_scripts: List[Dict] = []
        
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # === ЗАГОЛОВОК ===
        title = QLabel("ЗАПУСК СКРИПТОВ НА СТЕНДАХ")
        title.setStyleSheet("color: #a0b0ff; font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)
        
        # === ОСНОВНОЙ СПЛИТТЕР ===
        splitter = QSplitter(Qt.Horizontal)
        
        # === ЛЕВАЯ ПАНЕЛЬ (выбор скрипта) ===
        left_panel = QFrame()
        left_panel.setStyleSheet("""
            QFrame {
                background-color: #252545;
                border: 1px solid #3a3a6a;
                border-radius: 8px;
            }
        """)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)
        
        # Выбор стенда
        stand_group = QGroupBox("Стенд")
        stand_layout = QVBoxLayout()
        
        self.stand_combo = QComboBox()
        self.stand_combo.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
        stand_layout.addWidget(self.stand_combo)
        
        stand_group.setLayout(stand_layout)
        left_layout.addWidget(stand_group)
        
        # Список скриптов
        scripts_group = QGroupBox("Доступные скрипты")
        scripts_layout = QVBoxLayout()
        
        self.scripts_list = QListWidget()
        self.scripts_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e32;
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                color: #e0e0e0;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a4a;
            }
            QListWidget::item:selected {
                background-color: #4a4ad2;
            }
            QListWidget::item:hover {
                background-color: #3a3a6a;
            }
        """)
        self.scripts_list.currentItemChanged.connect(self.on_script_selected)
        scripts_layout.addWidget(self.scripts_list)
        
        # Кнопка обновления списка
        refresh_scripts_btn = QPushButton("ОБНОВИТЬ СПИСОК СО СТЕНДА")
        refresh_scripts_btn.clicked.connect(self.refresh_scripts_list)
        scripts_layout.addWidget(refresh_scripts_btn)
        
        scripts_group.setLayout(scripts_layout)
        left_layout.addWidget(scripts_group)
        
        # Пользовательский скрипт
        custom_group = QGroupBox("Свой скрипт")
        custom_layout = QVBoxLayout()
        
        self.custom_script_edit = QLineEdit()
        self.custom_script_edit.setPlaceholderText("Путь к скрипту на стенде...")
        custom_layout.addWidget(self.custom_script_edit)
        
        custom_group.setLayout(custom_layout)
        left_layout.addWidget(custom_group)
        
        # Аргументы
        args_group = QGroupBox("Аргументы")
        args_layout = QVBoxLayout()
        
        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("Аргументы командной строки...")
        args_layout.addWidget(self.args_edit)
        
        args_group.setLayout(args_layout)
        left_layout.addWidget(args_group)
        
        # Таймаут
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("Таймаут (с):"))
        self.timeout_edit = QLineEdit("30")
        self.timeout_edit.setMaximumWidth(60)
        timeout_layout.addWidget(self.timeout_edit)
        timeout_layout.addStretch()
        left_layout.addLayout(timeout_layout)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        self.run_btn = QPushButton("ЗАПУСТИТЬ")
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66bb6a;
            }
            QPushButton:disabled {
                background-color: #2a2a3a;
                color: #606060;
            }
        """)
        self.run_btn.clicked.connect(self.run_script)
        btn_layout.addWidget(self.run_btn)
        
        self.cancel_btn = QPushButton("ОСТАНОВИТЬ")
        self.cancel_btn.setObjectName("btnCancel")
        self.cancel_btn.clicked.connect(self.cancel_script)
        self.cancel_btn.setEnabled(False)
        btn_layout.addWidget(self.cancel_btn)
        
        left_layout.addLayout(btn_layout)
        
        left_layout.addStretch()
        
        splitter.addWidget(left_panel)
        
        # === ПРАВАЯ ПАНЕЛЬ (вывод) ===
        right_panel = QFrame()
        right_panel.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #3a3a6a;
                border-radius: 8px;
            }
        """)
        right_layout = QVBoxLayout(right_panel)
        
        # Описание скрипта
        self.desc_label = QLabel("Выберите скрипт из списка или введите свой")
        self.desc_label.setStyleSheet("""
            color: #6a6aaa;
            font-size: 11px;
            padding: 8px;
            background-color: #252545;
            border-radius: 5px;
        """)
        self.desc_label.setWordWrap(True)
        right_layout.addWidget(self.desc_label)
        
        # Статус
        self.status_label = QLabel("Готов к запуску")
        self.status_label.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold; padding: 5px;")
        right_layout.addWidget(self.status_label)
        
        # Прогресс
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        
        # Вывод
        output_group = QGroupBox("Вывод скрипта")
        output_layout = QVBoxLayout()
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d1a;
                border: 1px solid #2a2a4a;
                border-radius: 5px;
                color: #00ff00;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        output_layout.addWidget(self.output_text)
        
        # Кнопки для вывода
        output_btn_layout = QHBoxLayout()
        
        clear_output_btn = QPushButton("ОЧИСТИТЬ")
        clear_output_btn.clicked.connect(lambda: self.output_text.clear())
        output_btn_layout.addWidget(clear_output_btn)
        
        self.auto_scroll_cb = QCheckBox("Автопрокрутка")
        self.auto_scroll_cb.setChecked(True)
        output_btn_layout.addWidget(self.auto_scroll_cb)
        
        output_btn_layout.addStretch()
        output_layout.addLayout(output_btn_layout)
        
        output_group.setLayout(output_layout)
        right_layout.addWidget(output_group)
        
        splitter.addWidget(right_panel)
        
        # Пропорции сплиттера
        splitter.setSizes([350, 500])
        
        main_layout.addWidget(splitter)
        
        # === ИСТОРИЯ ===
        history_group = QGroupBox("История запусков")
        history_layout = QHBoxLayout()
        
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(400)
        history_layout.addWidget(self.history_combo)
        
        rerun_btn = QPushButton("ПОВТОРИТЬ")
        rerun_btn.clicked.connect(self.rerun_from_history)
        history_layout.addWidget(rerun_btn)
        
        clear_history_btn = QPushButton("ОЧИСТИТЬ ИСТОРИЮ")
        clear_history_btn.clicked.connect(self.clear_history)
        history_layout.addWidget(clear_history_btn)
        
        history_group.setLayout(history_layout)
        main_layout.addWidget(history_group)
        
        # Загружаем скрипты
        self.load_default_scripts()
    
    # ============================================================
    # УПРАВЛЕНИЕ СКРИПТАМИ
    # ============================================================
    
    def load_default_scripts(self):
        """Загружает предустановленные скрипты"""
        self.available_scripts = self.DEFAULT_SCRIPTS.copy()
        self.update_scripts_list()
    
    def update_scripts_list(self):
        """Обновляет список скриптов в виджете"""
        self.scripts_list.clear()
        
        for script in self.available_scripts:
            item = QListWidgetItem(script['name'])
            item.setToolTip(script.get('description', ''))
            item.setData(Qt.UserRole, script)
            self.scripts_list.addItem(item)
    
    def on_script_selected(self, current, previous):
        """Обработчик выбора скрипта"""
        if current:
            script = current.data(Qt.UserRole)
            if script:
                self.desc_label.setText(
                    f"Скрипт: {script['script']}\n"
                    f"Описание: {script.get('description', 'Нет описания')}"
                )
    
    def refresh_scripts_list(self):
        """Обновляет список скриптов со стенда"""
        stand_name = self.stand_combo.currentText()
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        if self.bi:
            scripts = self.bi.list_scripts(stand_name)
            if scripts:
                self.available_scripts = []
                for s in scripts:
                    self.available_scripts.append({
                        'name': s['name'],
                        'script': s['path'],
                        'description': f"Размер: {s['size']} байт"
                    })
                self.update_scripts_list()
                QMessageBox.information(self, "Обновлено", f"Загружено скриптов: {len(scripts)}")
            else:
                QMessageBox.information(self, "Инфо", "Скрипты не найдены на стенде. Используйте предустановленные.")
    
    # ============================================================
    # ЗАПУСК СКРИПТА
    # ============================================================
    
    def get_script_path(self) -> Optional[str]:
        """Возвращает путь к выбранному скрипту"""
        # Проверяем пользовательский ввод
        custom = self.custom_script_edit.text().strip()
        if custom:
            return custom
        
        # Проверяем выбранный скрипт
        current = self.scripts_list.currentItem()
        if current:
            script = current.data(Qt.UserRole)
            if script:
                return script['script']
        
        return None
    
    def run_script(self):
        """Запускает скрипт"""
        stand_name = self.stand_combo.currentText()
        
        if not self.bc or not self.bc.is_connected(stand_name):
            QMessageBox.warning(self, "Ошибка", f"Стенд {stand_name} не подключен!")
            return
        
        script_path = self.get_script_path()
        if not script_path:
            QMessageBox.warning(self, "Ошибка", "Выберите скрипт или введите путь!")
            return
        
        args = self.args_edit.text().strip()
        
        try:
            timeout = int(self.timeout_edit.text())
        except ValueError:
            timeout = 30
        
        # Блокируем UI
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)
        
        self.output_text.clear()
        self.status_label.setText(f"Выполнение: {script_path}...")
        self.status_label.setStyleSheet("color: #ff9800; font-size: 12px; font-weight: bold;")
        
        # Запускаем поток
        self.run_thread = ScriptRunThread(
            self.bc, stand_name, script_path, args, timeout
        )
        self.run_thread.output.connect(self.on_script_output)
        self.run_thread.finished.connect(self.on_script_finished)
        self.run_thread.error.connect(self.on_script_error)
        self.run_thread.start()
        
        # Сохраняем в историю
        self.add_to_history(stand_name, script_path, args)
    
    def cancel_script(self):
        """Отменяет выполнение скрипта"""
        if self.run_thread and self.run_thread.isRunning():
            self.run_thread.cancel()
            self.output_text.append("\n--- [ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ] ---")
            self.status_label.setText("Остановлено")
            self.status_label.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold;")
        
        self.reset_ui()
    
    def on_script_output(self, line: str):
        """Обработчик вывода скрипта"""
        self.output_text.append(line)
        
        if self.auto_scroll_cb.isChecked():
            scrollbar = self.output_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def on_script_finished(self, result: dict):
        """Скрипт завершен"""
        self.progress_bar.setVisible(False)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if result.get('success'):
            self.status_label.setText("Выполнено успешно")
            self.status_label.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold;")
        else:
            self.status_label.setText("Выполнено с ошибкой")
            self.status_label.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold;")
        
        self.run_thread = None
    
    def on_script_error(self, error: str):
        """Ошибка выполнения"""
        self.output_text.append(f"\n[ОШИБКА] {error}")
        self.status_label.setText(f"Ошибка: {error}")
        self.status_label.setStyleSheet("color: #f44336; font-size: 12px; font-weight: bold;")
        
        self.reset_ui()
    
    def reset_ui(self):
        """Сбрасывает UI после выполнения"""
        self.progress_bar.setVisible(False)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
    
    # ============================================================
    # ИСТОРИЯ
    # ============================================================
    
    def add_to_history(self, stand_name: str, script: str, args: str):
        """Добавляет запуск в историю"""
        entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stand': stand_name,
            'script': script,
            'args': args
        }
        self.script_history.append(entry)
        self.update_history_combo()
    
    def update_history_combo(self):
        """Обновляет комбобокс истории"""
        self.history_combo.clear()
        
        for entry in reversed(self.script_history[-20:]):
            text = f"[{entry['timestamp']}] {entry['stand']}: {entry['script']} {entry['args']}"
            self.history_combo.addItem(text, entry)
    
    def rerun_from_history(self):
        """Повторяет запуск из истории"""
        if self.history_combo.currentIndex() < 0:
            return
        
        entry = self.history_combo.currentData()
        if entry:
            # Восстанавливаем параметры
            index = self.stand_combo.findText(entry['stand'])
            if index >= 0:
                self.stand_combo.setCurrentIndex(index)
            
            self.custom_script_edit.setText(entry['script'])
            self.args_edit.setText(entry['args'])
            
            # Запускаем
            self.run_script()
    
    def clear_history(self):
        """Очищает историю"""
        self.script_history.clear()
        self.history_combo.clear()
    
    def set_managers(self, bc, bi=None):
        """Устанавливает менеджеры"""
        self.bc = bc
        self.bi = bi


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
    
    runner = ScriptRunner()
    runner.setWindowTitle("Запуск скриптов на стендах")
    runner.resize(900, 600)
    runner.show()
    
    sys.exit(app.exec_())
