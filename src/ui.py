"""UI/Tray interface functions for Sakura flow by Ekcler."""
import os
import sys
import subprocess
import re
import threading
import ctypes
import logging
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction, 
                             QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLineEdit, QTextEdit, QLabel, QMessageBox)
from PyQt5.QtGui import QIcon, QFont, QCursor
from PyQt5.QtCore import Qt, QTimer

# --- ФИКС ИКОНКИ В ПАНЕЛИ ЗАДАЧ ---
try:
    myappid = 'ekcler.sakuraflow.v1.2'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# Импорты проекта
try:
    from .config import BASE_DIR
    from . import service, autostart, state, tools
except ImportError:
    from src.config import BASE_DIR
    from src import service, autostart, state, tools

# --- УНИВЕРСАЛЬНЫЙ ПУТЬ ДЛЯ РЕСУРСОВ (ИСПРАВЛЯЕТ ТРЕЙ В .EXE) ---
def get_resource_path(relative_path):
    """Универсальный поиск файлов для VS Code и PyInstaller .exe"""
    if hasattr(sys, '_MEIPASS'):
        # Если запущено из .exe (режим --onefile)
        return os.path.join(sys._MEIPASS, relative_path)
    
    # Если запущено из VS Code (ищем от корня проекта)
    # Определяем корень проекта относительно этого файла (src/ui.py)
    current_dir = Path(__file__).parent.parent.resolve()
    return str(current_dir / relative_path)

# ПРОВЕРКА ПУТЕЙ (Сакура сама найдет свои иконки)
FINAL_ICON = get_resource_path("icons/moonstone.ico")
FINAL_CHECK = get_resource_path("icons/check.png")

# ТЕСТ ПУТИ В КОНСОЛЬ (Чтобы ты видел, где она ищет)
print(f"🌸 Ищу иконку тут: {FINAL_ICON}")

# --- ОКНО РЕДАКТОРА СПИСКОВ ---
class ListEditorWindow(QWidget):
    def __init__(self, restart_func):
        super().__init__()
        self.restart_func = restart_func
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Sakura Blocklist Editor 📝")
        self.setFixedSize(400, 500)
        self.setWindowIcon(QIcon(FINAL_ICON))
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QWidget { background-color: #0f0a12; color: #ffffff; font-family: 'Segoe UI'; }
            QTextEdit { background-color: #1a141d; border: 1px solid #3d1b28; color: #ff79c6; font-family: 'Consolas'; }
            QPushButton { background-color: #2d1621; border: 1px solid #3d1b28; padding: 10px; border-radius: 3px; font-weight: bold; }
            QPushButton:hover { background-color: #3d1b28; }
        """)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Domains (one per line):"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(tools.read_blocklist())
        layout.addWidget(self.text_edit)
        self.save_btn = QPushButton("💾 SAVE AND RESTART SERVICE")
        self.save_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_btn)
        self.setLayout(layout)

    def save_data(self):
        if tools.save_blocklist(self.text_edit.toPlainText()):
            QMessageBox.information(self, "Success", "List updated! Service will restart.")
            self.restart_func()
            self.close()

# --- ОКНО СЕТЕВЫХ ИНСТРУМЕНТОВ ---
class NetworkToolsWindow(QWidget):
    def __init__(self, restart_func):
        super().__init__()
        self.restart_func = restart_func
        self.best_dns_found = None
        self.list_editor = None 
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

    def init_ui(self):
        self.setWindowTitle("Sakura flow Tools")
        self.setFixedSize(400, 600)
        self.setWindowIcon(QIcon(FINAL_ICON))
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QWidget { background-color: #0f0a12; color: #ffffff; font-family: 'Segoe UI'; }
            QLineEdit { background-color: #1a141d; border: 1px solid #3d1b28; padding: 5px; border-radius: 3px; }
            QPushButton { background-color: #2d1621; border: 1px solid #3d1b28; padding: 8px; border-radius: 3px; }
            QPushButton:hover { background-color: #3d1b28; }
            QTextEdit { background-color: #1a141d; border: 1px solid #3d1b28; font-family: 'Consolas'; font-size: 11px; }
            QLabel { color: #ff79c6; font-weight: bold; }
        """)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Blocklist Management:"))
        self.edit_list_btn = QPushButton("📝 Edit General Blocklist")
        layout.addWidget(self.edit_list_btn)
        layout.addSpacing(10)
        layout.addWidget(QLabel("Network Utilities:"))
        self.host_input = QLineEdit(); self.host_input.setPlaceholderText("google.com")
        layout.addWidget(self.host_input)
        net_btn_layout = QHBoxLayout()
        self.ping_btn = QPushButton("Ping"); self.trace_btn = QPushButton("Trace")
        net_btn_layout.addWidget(self.ping_btn); net_btn_layout.addWidget(self.trace_btn)
        layout.addLayout(net_btn_layout)
        layout.addSpacing(10)
        layout.addWidget(QLabel("DNS Optimizer & Tester:"))
        dns_input_layout = QHBoxLayout()
        self.dns_input = QLineEdit(); self.dns_input.setPlaceholderText("Enter IP (e.g. 1.1.1.1)")
        self.test_dns_btn = QPushButton("Test")
        dns_input_layout.addWidget(self.dns_input); dns_input_layout.addWidget(self.test_dns_btn)
        layout.addLayout(dns_input_layout)
        dns_ctrl_layout = QHBoxLayout()
        self.dns_best_btn = QPushButton("⚡ Find Best"); self.reset_dns_btn = QPushButton("🔄 Reset DNS")
        dns_ctrl_layout.addWidget(self.dns_best_btn); dns_ctrl_layout.addWidget(self.reset_dns_btn)
        layout.addLayout(dns_ctrl_layout)
        self.apply_dns_btn = QPushButton("✅ Apply Best DNS"); self.apply_dns_btn.hide()
        layout.addWidget(self.apply_dns_btn)
        layout.addSpacing(10)
        self.traffic_label = QLabel("TRAFFIC | UP: 0.0 KB/s | DOWN: 0.0 KB/s")
        self.traffic_label.setStyleSheet("color: #50fa7b; font-family: 'Consolas'; font-size: 12px;")
        layout.addWidget(self.traffic_label)
        self.log_area = QTextEdit(); self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        self.setLayout(layout)
        
        self.edit_list_btn.clicked.connect(self.open_list_editor)
        self.ping_btn.clicked.connect(lambda: self.log_area.append(f"Ping {self.host_input.text()}: {tools.get_ping(self.host_input.text())} ms") if self.host_input.text() else None)
        self.trace_btn.clicked.connect(lambda: tools.run_tracert(self.host_input.text()) if self.host_input.text() else None)
        self.test_dns_btn.clicked.connect(self.run_custom_dns_test)
        self.dns_best_btn.clicked.connect(self.run_best_dns_test)
        self.reset_dns_btn.clicked.connect(self.run_reset_dns)
        self.apply_dns_btn.clicked.connect(self.apply_best_dns)

    def open_list_editor(self):
        self.list_editor = ListEditorWindow(self.restart_func); self.list_editor.show(); self.list_editor.activateWindow()

    def update_stats(self):
        up, down = tools.get_traffic_stats()
        self.traffic_label.setText(f"TRAFFIC | UP: {up} KB/s | DOWN: {down} KB/s")

    def run_custom_dns_test(self):
        dns = self.dns_input.text().strip()
        if dns:
            res = tools.get_ping(dns); self.log_area.append(f"DNS {dns}: {res} ms")
            if isinstance(res, (float, int)): self.best_dns_found = dns; self.apply_dns_btn.show()

    def run_best_dns_test(self):
        self.log_area.append("Scanning DNS..."); ip, info = tools.find_best_dns()
        self.log_area.append(f"Best: {info}")
        if ip: self.best_dns_found = ip; self.apply_dns_btn.show()

    def apply_best_dns(self):
        if self.best_dns_found:
            s, i = tools.set_system_dns(self.best_dns_found)
            self.log_area.append(f"DNS Set: {s} ({i})"); self.apply_dns_btn.hide()

    def run_reset_dns(self):
        s, i = tools.reset_system_dns(); self.log_area.append(f"DNS Reset: {s} ({i})")

# --- ЛОГИКА ОБНОВЛЕНИЯ СТИЛЕЙ ---
def update_menu_styles(start_menu, actions, active_version):
    """Подсветка активного батника внутри Start."""
    try:
        check_icon = QIcon(FINAL_CHECK) if os.path.exists(FINAL_CHECK) else QIcon()
        for bat, action in actions.items():
            if bat.stem == active_version:
                font = QFont(); font.setBold(True); action.setFont(font)
                action.setIcon(check_icon)
            else:
                action.setFont(QFont()); action.setIcon(QIcon())
        start_menu.update()
    except Exception as e:
        logging.error(f"Style Error: {e}")

# --- ТРЕЙ-МЕНЕДЖЕР ---
tools_window = None
def open_tools(restart_func):
    global tools_window
    if tools_window is None: tools_window = NetworkToolsWindow(restart_func)
    tools_window.show(); tools_window.activateWindow()

def create_tray_app(bat_files):
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # ПРИНУДИТЕЛЬНОЕ ИМЯ И ИКОНКА
    app.setApplicationName("Sakura flow")
    app_icon = QIcon(FINAL_ICON)
    app.setWindowIcon(app_icon)
    
    # Создаем трей
    tray = QSystemTrayIcon(app_icon)
    tray.setToolTip("Sakura flow")
    tray.show()
    
    menu = QMenu()
    menu.setStyleSheet("""
        QMenu { background-color: #0f0a12; color: #ffffff; border: 1px solid #3d1b28; font-size: 14px; }
        QMenu::item { padding: 8px 32px 8px 12px; }
        QMenu::item:selected { background-color: #2d1621; }
        QMenu::separator { height: 1px; background: #3d1b28; margin: 4px; }
    """)

    def quick_restart():
        app_state = state.load_state()
        if app_state["last_bat"]:
            for b in bat_files:
                if b.stem == app_state["last_bat"]:
                    threading.Thread(target=lambda: service.start_service(b, b.stem), daemon=True).start()
                    break

    # 1. Start Menu
    start_menu = QMenu("  Start", menu); start_menu.setStyleSheet(menu.styleSheet())
    actions = {}
    for bat in bat_files:
        action = start_menu.addAction(bat.stem)
        action.triggered.connect(lambda checked, b=bat: (
            state.save_state(last_bat=b.stem, stopped=False), 
            threading.Thread(target=lambda: service.start_service(b, b.stem), daemon=True).start(), 
            update_menu_styles(start_menu, actions, b.stem)
        ))
        actions[bat] = action
    menu.addMenu(start_menu)

    menu.addAction("  🌐 Internet Settings", lambda: subprocess.Popen("control ncpa.cpl", shell=True))
    menu.addAction("  🛠️ Network Tools", lambda: open_tools(quick_restart))
    menu.addSeparator()

    menu.addAction("  Stop", lambda: (
        state.save_state(last_bat=None, stopped=True), 
        threading.Thread(target=lambda: (
            service.stop_service(), 
            service.delete_service(), 
            update_menu_styles(start_menu, actions, None)
        ), daemon=True).start()
    ))
    
    autostart_action = menu.addAction("  Autostart")
    autostart_action.setCheckable(True)
    autostart_action.setChecked(autostart.is_autostart_enabled())
    autostart_action.toggled.connect(lambda chk: autostart.enable_autostart() if chk else autostart.disable_autostart())

    menu.addSeparator()
    menu.addAction("  Exit", lambda: (service.stop_service(), QApplication.quit()))

    # Открытие меню по клику на иконку
    tray.activated.connect(lambda r: menu.popup(QCursor.pos()) if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.setContextMenu(menu)

    # Восстановление активного состояния
    display_name = service.get_service_display_name()
    active_version = None
    if display_name:
        # Извлекаем имя стратегии из квадратных скобок (Sakura flow [имя])
        match = re.search(r'\[([^\]]+)\]', display_name)
        if match: active_version = match.group(1)
    
    update_menu_styles(start_menu, actions, active_version)

    return app.exec_()
