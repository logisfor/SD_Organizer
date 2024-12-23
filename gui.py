import sys
import os
import threading
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QLineEdit, QTextEdit, QFileDialog, QVBoxLayout,
    QHBoxLayout, QProgressBar, QMessageBox, QProgressDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from organizer import process_all_files, OutputFolderHandler
import PyQt5
from update_checker import UpdateChecker

plugin_path = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt', 'plugins')
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path
from PyQt5 import QtCore

VERSION = "1.0.0"

class Communicate(QObject):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

class SDOrganizerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.version = VERSION
        self.init_ui()
        self.observer = None
        self.thread = None
        self.c = Communicate()
        self.c.log_signal.connect(self.update_log)
        self.c.progress_signal.connect(self.update_progress)
        self.c.finished_signal.connect(self.on_finished)
        self.update_checker = UpdateChecker(self.version)
        self.check_for_updates()

    def init_ui(self):
        self.setWindowTitle(f"StableDiffusion Organizer v{self.version}")
        self.setGeometry(100, 100, 800, 600)
        self.setStyleSheet("background-color: #2c2c2c; color: #d3d3d3;")

        title = QLabel("Организатор генераций StableDiffusion", self)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)

        # Сначала output
        output_label = QLabel("Папка output:", self)
        self.output_entry = QLineEdit(self)
        self.output_entry.setStyleSheet("background-color: #4c4c4c; color: #d3d3d3;")
        output_button = QPushButton("Обзор...", self)
        output_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d3d3d3;
            }
            QPushButton:hover {
                background-color: #5c5c5c;
            }
        """)
        output_button.clicked.connect(lambda: self.select_folder(self.output_entry))
        output_layout = QHBoxLayout()
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_entry)
        output_layout.addWidget(output_button)

        # Затем project
        project_label = QLabel("Папка проекта:", self)
        self.project_entry = QLineEdit(self)
        self.project_entry.setStyleSheet("background-color: #4c4c4c; color: #d3d3d3;")
        project_button = QPushButton("Обзор...", self)
        project_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d3d3d3;
            }
            QPushButton:hover {
                background-color: #5c5c5c;
            }
        """)
        project_button.clicked.connect(lambda: self.select_folder(self.project_entry))
        project_layout = QHBoxLayout()
        project_layout.addWidget(project_label)
        project_layout.addWidget(self.project_entry)
        project_layout.addWidget(project_button)

        start_button = QPushButton("Начать обработку", self)
        start_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d3d3d3;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #5c5c5c;
            }
        """)
        start_button.clicked.connect(lambda: self.start_processing())

        stop_button = QPushButton("Остановить слежение", self)
        stop_button.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #d3d3d3;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #5c5c5c;
            }
        """)
        stop_button.clicked.connect(self.stop_processing)
        stop_button.setEnabled(False)
        self.stop_button = stop_button

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(start_button)
        buttons_layout.addWidget(stop_button)

        # Шкала прогресса
        progress_bar = QProgressBar(self)
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                color: #d3d3d3;
            }
            QProgressBar::chunk {
                background-color: #5c5c5c;
            }
        """)
        progress_bar.setValue(0)
        self.progress_bar = progress_bar

        # Поле логов
        log_label = QLabel("Логи:", self)
        log_text = QTextEdit(self)
        log_text.setReadOnly(True)
        log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1c1c1c;
                color: #b3b3b3;
            }
        """)
        self.log_text = log_text

        # Размещение элементов
        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addLayout(output_layout)    # Сначала output
        layout.addLayout(project_layout)   # Потом project
        layout.addLayout(buttons_layout)
        layout.addWidget(progress_bar)
        layout.addWidget(log_label)
        layout.addWidget(log_text)

        self.setLayout(layout)

    def select_folder(self, entry):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder:
            entry.setText(folder)

    def start_processing(self):
        project_folder = self.project_entry.text().strip()
        output_folder = self.output_entry.text().strip()

        if not project_folder or not output_folder:
            self.log("ОШИБКА: Выберите обе папки!")
            return

        if os.path.abspath(project_folder) == os.path.abspath(output_folder):
            self.log("ОШИБКА: Папки 'project' и 'output' не должны совпадать.")
            return

        self.stop_button.setEnabled(True)

        # Запускаем обработку в отдельном потоке
        thread = threading.Thread(target=self.run_watchdog, args=(output_folder, project_folder), daemon=True)
        thread.start()

    def run_watchdog(self, output_folder, project_folder):
        try:
            # Сбрасываем флаг остановки при старте
            self.stop_flag = False
            
            # Обработка существующих файлов
            self.c.log_signal.emit("Начинаем обработку существующих файлов...")
            generator = process_all_files(output_folder, project_folder, log_callback=self.c.log_signal.emit)

            total = 0
            for processed, total_files, result in generator:
                if total_files > total:
                    total = total_files
                progress = int((processed / total) * 100) if total > 0 else 0
                self.c.progress_signal.emit(progress)

            self.c.log_signal.emit("Обработка существующих файлов завершена.")

            # Настройка слежения за новой папкой
            self.c.log_signal.emit("Настраиваем слежение за новой папкой и её содержимым...")
            event_handler = OutputFolderHandler(project_folder, self.c.log_signal.emit)
            observer = Observer()
            observer.schedule(event_handler, output_folder, recursive=True)
            self.observer = observer
            observer.start()
            self.c.log_signal.emit(f"Слежение за папкой '{output_folder}' началось.")

            # Бесконечный цикл до получения сигнала остановки
            while not getattr(self, 'stop_flag', False):
                observer.join(timeout=1)

        except Exception as e:
            self.c.log_signal.emit(f"Ошибка: {e}")
        finally:
            if self.observer:
                self.observer.stop()
                self.observer.join()
                self.observer = None  # Очищаем ссылку на observer
            self.c.log_signal.emit("Слежение завершено.")
            self.c.finished_signal.emit()

    def stop_processing(self):
        self.stop_flag = True
        self.c.log_signal.emit("Остановка слежения...")
        self.stop_button.setEnabled(False)

    def update_log(self, message):
        self.log_text.append(message)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def on_finished(self):
        self.stop_button.setEnabled(False)

    def log(self, message):
        self.c.log_signal.emit(message)

    def closeEvent(self, event):
        if self.observer:
            self.observer.stop()
            self.observer.join()
        event.accept()

    def check_for_updates(self):
        update_info = self.update_checker.check_for_updates()
        if update_info['available']:
            reply = QMessageBox.question(
                self, 
                'Доступно обновление',
                f"Доступна новая версия {update_info['version']}\n\n"
                f"Изменения:\n{update_info['changes']}\n\n"
                "Установить обновление?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.download_update(update_info['download_url'])

    def download_update(self, url):
        progress = QProgressDialog("Загрузка обновления...", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        
        def update_progress(percent):
            progress.setValue(int(percent))
        
        temp_path = self.update_checker.download_update(url, update_progress)
        if temp_path:
            # Запускаем новую версию и закрываем текущую
            os.startfile(temp_path)
            self.close()

def main():
    app = QApplication(sys.argv)
    gui = SDOrganizerGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()