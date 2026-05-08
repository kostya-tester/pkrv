"""
Главное окно приложения Bench Manager.
Объединяет все панели: стенды, файлы, загрузку, процессы, скрипты.
"""

import sys
import os
import time
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QStatusBar, QFrame, QSplitter,
    QTextEdit, QScrollBar, QApplication, QMessageBox, QProgressBar
)
from PyQt5.QtCore import (
    Qt, QTimer, QSize, pyqtSignal
)
from PyQt5.QtGui import (
    QPixmap, QFont, QIcon, QPalette, QColor
)

# Пути
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# Импорт модулей
sys.path.insert(0, BASE_DIR)

try:
    from core.bench_connector import BenchConnector
    from core.file_transfer import FileTransfer
    from core.file_manager import FileManager
    from core.process_manager import ProcessManager
    from core.board_interface import BoardInterface
    from logger.log_manager import LogManager
    from gui.file_uploader import FileUploaderWidget, DARK_THEME
except ImportError as e:
    print(f"Ошибка импорта: {e}")
    BenchConnector = None
    FileTransfer = None
    FileManager = None
    ProcessManager = None
    BoardInterface = None
    LogManager = None
    FileUploaderWidget = None
    DARK_THEME = ""


# ============================================================
# ПАНЕЛЬ ПРОЦЕССОВ (простая версия)
# ============================================================

class ProcessPanel(QWidget):
    """Панель управления процессами на стендах"""
    
    def __init__(self, bench_connector=None, process_manager=None):
        super().__init__()
        self.bc = bench_connector
        self.pm = process_manager
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Заголовок
        title = QLabel("УПРАВЛЕНИЕ ПРОЦЕССАМИ")
        title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Выбор стенда
        stand_layout = QHBoxLayout()
        stand_layout.addWidget(QLabel("Стенд:"))
        self.stand_combo = QComboBox()
        self.stand_combo.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
        stand_layout.addWidget(self.stand_combo)
        stand_layout.addStretch()
        layout.addLayout(stand_layout)
        
        # Действия с процессами
        actions_group = QGroupBox("Действия")
        actions_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("ЗАПУСТИТЬ ./1po2_1n")
        self.btn_start.clicked.connect(self.start_process)
        actions_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("ОСТАНОВИТЬ (slay)")
        self.btn_stop.setObjectName("btnCancel")
        self.btn_stop.clicked.connect(self.stop_process)
        actions_layout.addWidget(self.btn_stop)
        
        self.btn_restart = QPushButton("ПЕРЕЗАПУСТИТЬ")
        self.btn_restart.clicked.connect(self.restart_process)
        actions_layout.addWidget(self.btn_restart)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        # Статус процесса
        self.status_label = QLabel("Статус: не проверен")
        self.status_label.setStyleSheet("color: #8a8aaa; font-size: 13px;")
        layout.addWidget(self.status_label)
        
        # Лог
        log_group = QGroupBox("Результат")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
    
    def start_process(self):
        stand = self.stand_combo.currentText()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Запуск процесса на {stand}...")
        self.status_label.setText("Статус: запускается...")
    
    def stop_process(self):
        stand = self.stand_combo.currentText()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Остановка процесса на {stand}...")
        self.status_label.setText("Статус: останавливается...")
    
    def restart_process(self):
        stand = self.stand_combo.currentText()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Перезапуск процесса на {stand}...")
        self.status_label.setText("Статус: перезапуск...")

# Импорт QComboBox (если не импортирован выше)
from PyQt5.QtWidgets import QComboBox, QGroupBox


# ============================================================
# ПАНЕЛЬ ПЛАТЫ
# ============================================================

class BoardPanel(QWidget):
    """Панель работы с платами (прошивка, скрипты)"""
    
    def __init__(self, bench_connector=None, board_interface=None):
        super().__init__()
        self.bc = bench_connector
        self.bi = board_interface
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        title = QLabel("РАБОТА С ПЛАТАМИ")
        title.setStyleSheet("color: #a0b0ff; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Выбор стенда
        stand_layout = QHBoxLayout()
        stand_layout.addWidget(QLabel("Стенд:"))
        self.stand_combo = QComboBox()
        self.stand_combo.addItems(["ГОЗ", "Арктика", "C1M", "OrangePi"])
        stand_layout.addWidget(self.stand_combo)
        stand_layout.addStretch()
        layout.addLayout(stand_layout)
        
        # Прошивка
        flash_group = QGroupBox("Прошивка платы")
        flash_layout = QHBoxLayout()
        
        self.firmware_combo = QComboBox()
        self.firmware_combo.addItems(["mpo", "factory", "backup"])
        self.firmware_combo.setEditable(True)
        flash_layout.addWidget(QLabel("Прошивка:"))
        flash_layout.addWidget(self.firmware_combo)
        
        self.btn_flash = QPushButton("ПРОШИТЬ (ln -sf)")
        self.btn_flash.clicked.connect(self.flash_board)
        flash_layout.addWidget(self.btn_flash)
        
        flash_group.setLayout(flash_layout)
        layout.addWidget(flash_group)
        
        # Скрипты
        scripts_group = QGroupBox("Запуск скриптов")
        scripts_layout = QHBoxLayout()
        
        self.script_combo = QComboBox()
        self.script_combo.addItems(["flash_firmware.py", "read_sensors.py", "run_test.py"])
        self.script_combo.setEditable(True)
        scripts_layout.addWidget(QLabel("Скрипт:"))
        scripts_layout.addWidget(self.script_combo)
        
        self.btn_run_script = QPushButton("ЗАПУСТИТЬ")
        self.btn_run_script.clicked.connect(self.run_script)
        scripts_layout.addWidget(self.btn_run_script)
        
        scripts_group.setLayout(scripts_layout)
        layout.addWidget(scripts_group)
        
        # Лог
        log_group = QGroupBox("Результат")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
    
    def flash_board(self):
        stand = self.stand_combo.currentText()
        fw = self.firmware_combo.currentText()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Прошивка {stand}: ln -sf {fw} 1po2_1n")
    
    def run_script(self):
        stand = self.stand_combo.currentText()
        script = self.script_combo.currentText()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] Запуск скрипта {script} на {stand}")


# ============================================================
# ГЛАВНОЕ ОКНО
# ============================================================

class MainWindow(QMainWindow):
    """Главное окно приложения Bench Manager"""
    
    def __init__(self):
        super().__init__()
        
        # Инициализация модулей
        self.logger = LogManager() if LogManager else None
        self.bc = None
        self.ft = None
        self.fm = None
        self.pm = None
        self.bi = None
        
        # Настройка окна
        self.setWindowTitle("Bench Manager Pro")
        self.setGeometry(100, 50, 1100, 750)
        self.setMinimumSize(900, 600)
        
        # Применяем стиль
        if DARK_THEME:
            self.setStyleSheet(DARK_THEME)
        
        # Создаем интерфейс
        self.setup_ui()
        self.setup_status_bar()
        
        # Инициализируем модули с задержкой
        QTimer.singleShot(100, self.init_modules)
    
    def setup_ui(self):
        """Создает главный интерфейс"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # ============================================================
        # HEADER
        # ============================================================
        header = self.create_header()
        main_layout.addWidget(header)
        
        # ============================================================
        # ВКЛАДКИ
        # ============================================================
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                background: #1e1e32;
            }
            QTabBar::tab {
                background: #2a2a4a;
                color: #8a8aaa;
                padding: 10px 20px;
                margin-right: 3px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1e1e32;
                color: #a0b0ff;
                border-bottom: 2px solid #4a4ad2;
            }
            QTabBar::tab:hover {
                background: #3a3a6a;
                color: #cdd6f4;
            }
        """)
        
        # Вкладка 1: Загрузка файлов
        self.upload_widget = FileUploaderWidget() if FileUploaderWidget else QWidget()
        self.tab_widget.addTab(self.upload_widget, "ЗАГРУЗКА ФАЙЛОВ")
        
        # Вкладка 2: Процессы
        self.process_panel = ProcessPanel()
        self.tab_widget.addTab(self.process_panel, "ПРОЦЕССЫ")
        
        # Вкладка 3: Платы
        self.board_panel = BoardPanel()
        self.tab_widget.addTab(self.board_panel, "ПЛАТЫ")
        
        # Вкладка 4: Логи
        self.log_panel = self.create_log_panel()
        self.tab_widget.addTab(self.log_panel, "ЛОГИ")
        
        main_layout.addWidget(self.tab_widget)
    
    def create_header(self):
        """Создает панель заголовка с логотипом"""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e1e4a, stop:0.5 #2a2a5a, stop:1 #1e1e4a);
                border-radius: 10px;
                padding: 5px;
            }
        """)
        header.setFixedHeight(70)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 5, 15, 5)
        
        # Логотип
        logo_label = QLabel()
        logo_path = os.path.join(IMAGES_DIR, "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(180, 55, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        else:
            logo_label.setText("BENCH MANAGER")
            logo_label.setStyleSheet("color: #4a4ad2; font-size: 22px; font-weight: bold;")
        layout.addWidget(logo_label)
        
        layout.addStretch()
        
        # Заголовок
        title = QLabel("BENCH MANAGER PRO")
        title.setStyleSheet("""
            color: #cdd6f4;
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
        """)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Индикатор статуса
        self.status_indicator = QLabel("СИСТЕМА ГОТОВА")
        self.status_indicator.setStyleSheet("color: #4caf50; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.status_indicator)
        
        return header
    
    def create_log_panel(self):
        """Создает панель просмотра логов"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("ОБНОВИТЬ")
        refresh_btn.clicked.connect(self.refresh_logs)
        btn_layout.addWidget(refresh_btn)
        
        clear_btn = QPushButton("ОЧИСТИТЬ")
        clear_btn.setObjectName("btnCancel")
        clear_btn.clicked.connect(self.clear_logs)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Текст лога
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a2e;
                border: 1px solid #3a3a6a;
                border-radius: 5px;
                color: #a0a0c0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_viewer)
        
        # Автопрокрутка
        self.auto_scroll = True
        
        return panel
    
    def setup_status_bar(self):
        """Настраивает строку состояния"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_label = QLabel("Готов к работе")
        self.status_bar.addWidget(self.status_label)
        
        self.stand_count_label = QLabel("Стенды: 0/4")
        self.status_bar.addPermanentWidget(self.stand_count_label)
        
        self.time_label = QLabel(datetime.now().strftime('%H:%M:%S'))
        self.status_bar.addPermanentWidget(self.time_label)
        
        # Таймер обновления времени
        timer = QTimer()
        timer.timeout.connect(lambda: self.time_label.setText(datetime.now().strftime('%H:%M:%S')))
        timer.start(1000)
    
    def init_modules(self):
        """Инициализирует модули ядра"""
        if LogManager:
            self.logger = LogManager()
            self.logger.setup(level="INFO", log_file=os.path.join(BASE_DIR, "logs", "bench_manager.log"))
            self.logger.info("Приложение запущено")
        
        if BenchConnector:
            self.bc = BenchConnector()
            self.bc.start_monitoring()
            self.log(f"INFO: BenchConnector инициализирован")
            
            if FileTransfer:
                self.ft = FileTransfer(self.bc)
            
            if FileManager:
                self.fm = FileManager(self.bc)
            
            if ProcessManager:
                self.pm = ProcessManager(self.bc)
                self.process_panel.bc = self.bc
                self.process_panel.pm = self.pm
            
            if BoardInterface:
                self.bi = BoardInterface(self.bc)
                self.board_panel.bc = self.bc
                self.board_panel.bi = self.bi
            
            # Передаем коннектор в виджет загрузки
            if hasattr(self.upload_widget, 'set_bench_connector'):
                self.upload_widget.set_bench_connector(self.bc)
            if hasattr(self.upload_widget, 'set_file_transfer') and self.ft:
                self.upload_widget.set_file_transfer(self.ft)
            
            # Таймер обновления статуса стендов
            self.status_timer = QTimer()
            self.status_timer.timeout.connect(self.update_stand_status)
            self.status_timer.start(3000)
    
    def update_stand_status(self):
        """Обновляет статус стендов в строке состояния"""
        if self.bc:
            online_count = sum(1 for s in self.bc.stands.values() if s.status == "online")
            total = len(self.bc.stands)
            self.stand_count_label.setText(f"Стенды: {online_count}/{total}")
            
            if online_count > 0:
                self.stand_count_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            else:
                self.stand_count_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def log(self, message: str):
        """Добавляет сообщение в лог"""
        if hasattr(self, 'log_viewer'):
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.log_viewer.append(f"[{timestamp}] {message}")
            
            if self.auto_scroll:
                scrollbar = self.log_viewer.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
    
    def refresh_logs(self):
        """Обновляет просмотр логов"""
        if self.logger and self.logger.log_file and os.path.exists(self.logger.log_file):
            try:
                with open(self.logger.log_file, 'r', encoding='utf-8') as f:
                    self.log_viewer.setPlainText(f.read())
            except:
                pass
    
    def clear_logs(self):
        """Очищает просмотр логов"""
        self.log_viewer.clear()
        self.log("Логи очищены")
    
    def closeEvent(self, event):
        """Обработчик закрытия окна"""
        reply = QMessageBox.question(
            self, 'Выход',
            'Вы уверены, что хотите выйти?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.bc:
                self.bc.stop_monitoring()
                self.bc.disconnect_all()
            
            if self.logger:
                self.logger.info("Приложение закрыто")
            
            event.accept()
        else:
            event.ignore()


# ============================================================
# ФУНКЦИЯ ЗАПУСКА
# ============================================================

def main():
    """Запуск приложения"""
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(IMAGES_DIR, "logo.png")))
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
