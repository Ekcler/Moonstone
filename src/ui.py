"""UI/Tray interface functions for Sakura Flow by Ekcler."""
import subprocess
import re
import sys
import threading
import ctypes
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QTextEdit, QLabel, QMessageBox)
from PyQt5.QtGui import QDesktopServices, QIcon, QFont, QCursor
from PyQt5.QtCore import QUrl, Qt, QTimer

try:
    myappid = 'ekcler.sakuraflow.v1.2'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

try:
    from .config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from . import service, autostart, state, tools
    try:
        from . import tg_ws_proxy
    except ImportError:
        tg_ws_proxy = None
except ImportError:
    from src.config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from src import service, autostart, state, tools
    try:
        from src import tg_ws_proxy
    except ImportError:
        tg_ws_proxy = None


class ListEditorWindow(QWidget):
    def __init__(self, restart_func, start_menu=None, actions=None):
        super().__init__()
        self.restart_func = restart_func
        self.start_menu = start_menu
        self.actions = actions
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Sakura Blocklist Editor")
        self.setFixedSize(400, 500)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
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

        self.save_btn = QPushButton("SAVE AND RESTART SERVICE")
        self.save_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_btn)
        self.setLayout(layout)

    def save_data(self):
        if tools.save_blocklist(self.text_edit.toPlainText()):
            service.stop_service()
            service.delete_service()
            if self.start_menu and self.actions:
                update_menu_styles(self.start_menu, self.actions, None)
            QMessageBox.information(self, "Success", "List updated! Service stopped.")
            self.close()


class NetworkToolsWindow(QWidget):
    def __init__(self, restart_func, start_menu=None, actions=None):
        super().__init__()
        self.restart_func = restart_func
        self.start_menu = start_menu
        self.actions = actions
        self.best_dns_found = None
        self.list_editor = None
        self._tg_proxy_on = False
        self._socks5_running = tools.SOCKS5_ENABLED
        self.init_ui()
        self.log_area.append("Ready!")
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

        if self._socks5_running:
            self.start_socks5_proxy()

    def init_ui(self):
        self.setWindowTitle("Sakura Flow Tools by Ekcler")
        self.setFixedSize(400, 650)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(Qt.Window)
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
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("google.com")
        layout.addWidget(self.host_input)
        net_btn_layout = QHBoxLayout()
        self.ping_btn = QPushButton("Ping")
        self.trace_btn = QPushButton("Trace")
        net_btn_layout.addWidget(self.ping_btn)
        net_btn_layout.addWidget(self.trace_btn)
        layout.addLayout(net_btn_layout)

        layout.addSpacing(10)
        layout.addWidget(QLabel("TG PROXY:"))
        self.tg_link_btn = QPushButton("🔗 OPEN LINK")
        self.tg_link_btn.setStyleSheet("""
            QPushButton { background-color: #1a1b2e; border: 1px solid #313244; color: #89b4fa; font-weight: bold; padding: 10px; }
            QPushButton:hover { background-color: #313244; }
        """)
        layout.addWidget(self.tg_link_btn)

        layout.addSpacing(10)
        layout.addWidget(QLabel("SOCKS5 PROXY:"))
        host_port_layout = QHBoxLayout()
        host_port_layout.addWidget(QLabel("Host:"))
        self.tg_host_input = QLineEdit()
        self.tg_host_input.setPlaceholderText("127.0.0.1")
        self.tg_host_input.setText("127.0.0.1")
        host_port_layout.addWidget(self.tg_host_input)
        host_port_layout.addWidget(QLabel("Port:"))
        self.tg_port_input = QLineEdit()
        self.tg_port_input.setPlaceholderText("1080")
        self.tg_port_input.setText("1080")
        host_port_layout.addWidget(self.tg_port_input)
        layout.addLayout(host_port_layout)

        self.socks5_toggle_btn = QPushButton("ON")
        self.socks5_toggle_btn.setStyleSheet("""
            QPushButton { background-color: #1a3d1b; border: 1px solid #50fa7b; color: #50fa7b; font-weight: bold; padding: 10px; }
            QPushButton:hover { background-color: #2d4d2b; }
        """)
        layout.addWidget(self.socks5_toggle_btn)

        layout.addSpacing(10)
        layout.addWidget(QLabel("DNS Optimizer & Tester:"))
        dns_input_layout = QHBoxLayout()
        self.dns_input = QLineEdit()
        self.dns_input.setPlaceholderText("Enter IP (e.g. 1.1.1.1)")
        self.test_dns_btn = QPushButton("Test")
        dns_input_layout.addWidget(self.dns_input)
        dns_input_layout.addWidget(self.test_dns_btn)
        layout.addLayout(dns_input_layout)

        dns_ctrl_layout = QHBoxLayout()
        self.dns_best_btn = QPushButton("⚡ Find Best")
        self.reset_dns_btn = QPushButton("🔄 Reset DNS")
        dns_ctrl_layout.addWidget(self.dns_best_btn)
        dns_ctrl_layout.addWidget(self.reset_dns_btn)
        layout.addLayout(dns_ctrl_layout)

        self.apply_dns_btn = QPushButton("✅ Apply Best DNS")
        self.apply_dns_btn.hide()
        layout.addWidget(self.apply_dns_btn)

        layout.addSpacing(10)
        self.traffic_label = QLabel("📊 TRAFFIC | UP: 0.0 KB/s | DOWN: 0.0 KB/s")
        self.traffic_label.setStyleSheet("color: #50fa7b; font-family: 'Consolas'; font-size: 12px;")
        layout.addWidget(self.traffic_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        self.setLayout(layout)

        self.edit_list_btn.clicked.connect(self.open_list_editor)
        self.ping_btn.clicked.connect(self.run_ping_logic)
        self.trace_btn.clicked.connect(lambda: tools.run_tracert(self.host_input.text()) if self.host_input.text() else None)
        self.test_dns_btn.clicked.connect(self.run_custom_dns_test)
        self.dns_best_btn.clicked.connect(self.run_best_dns_test)
        self.reset_dns_btn.clicked.connect(self.run_reset_dns)
        self.apply_dns_btn.clicked.connect(self.apply_best_dns)
        self.tg_link_btn.clicked.connect(self.copy_tg_link)
        self.socks5_toggle_btn.clicked.connect(self.toggle_socks5_proxy)

        if tools.SOCKS5_ENABLED:
            self.socks5_toggle_btn.setText("OFF")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: #2d1621; border: 1px solid #ff5555; color: #ff5555; font-weight: bold; padding: 10px; }
                QPushButton:hover { background-color: #3d1b28; }
            """)

    def copy_tg_link(self):
        link = "https://t.me/proxy?server=why4ch.live&port=443&secret=717973e23c5681248f58e5004413d687"
        QApplication.clipboard().setText(link)
        QDesktopServices.openUrl(QUrl(link))
        self.log_area.append("TG link copied and opened!")

    def toggle_socks5_proxy(self):
        if not tg_ws_proxy:
            self.log_area.append("Proxy engine not available!")
            return

        self._socks5_running = not self._socks5_running
        if self._socks5_running:
            try:
                port = int(self.tg_port_input.text().strip() or "1080")
                host = self.tg_host_input.text().strip() or "127.0.0.1"
                dc_opt = {
                    1: '149.154.175.50', 2: '149.154.167.220',
                    3: '149.154.175.100', 4: '149.154.167.220',
                    5: '91.108.56.100'
                }
                import socket
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    test_sock.bind((host, port))
                    test_sock.close()
                except OSError:
                    test_sock.close()
                    self._socks5_running = False
                    self.log_area.append(f"Port {port} already in use!")
                    self.socks5_toggle_btn.setText("ON")
                    self.socks5_toggle_btn.setStyleSheet("""
                        QPushButton { background-color: #1a3d1b; border: 1px solid #50fa7b; color: #50fa7b; font-weight: bold; padding: 10px; }
                        QPushButton:hover { background-color: #2d4d2b; }
                    """)
                    return

                self._proxy_thread = threading.Thread(
                    target=tg_ws_proxy.run_proxy,
                    args=(port, dc_opt, None, host),
                    daemon=True)
                self._proxy_thread.start()
                self.socks5_toggle_btn.setText("OFF")
                self.socks5_toggle_btn.setStyleSheet("""
                    QPushButton { background-color: #2d1621; border: 1px solid #ff5555; color: #ff5555; font-weight: bold; padding: 10px; }
                    QPushButton:hover { background-color: #3d1b28; }
                """)
                self.log_area.append(f"SOCKS5 Proxy started: {host}:{port}")
                tools.set_socks5_enabled(True)
            except Exception as e:
                self._socks5_running = False
                self.log_area.append(f"Error: {e}")
        else:
            self.socks5_toggle_btn.setText("ON")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: #1a3d1b; border: 1px solid #50fa7b; color: #50fa7b; font-weight: bold; padding: 10px; }
                QPushButton:hover { background-color: #2d4d2b; }
            """)
            self.log_area.append("SOCKS5 Proxy stopped")
            tools.set_socks5_enabled(False)

    def start_socks5_proxy(self):
        if not tg_ws_proxy:
            return
        try:
            port = int(self.tg_port_input.text().strip() or "1080")
            host = self.tg_host_input.text().strip() or "127.0.0.1"
            dc_opt = {
                1: '149.154.175.50', 2: '149.154.167.220',
                3: '149.154.175.100', 4: '149.154.167.220',
                5: '91.108.56.100'
            }
            import socket
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                test_sock.bind((host, port))
                test_sock.close()
            except OSError:
                test_sock.close()
                self._socks5_running = False
                self.socks5_toggle_btn.setText("ON")
                self.socks5_toggle_btn.setStyleSheet("""
                    QPushButton { background-color: #1a3d1b; border: 1px solid #50fa7b; color: #50fa7b; font-weight: bold; padding: 10px; }
                    QPushButton:hover { background-color: #2d4d2b; }
                """)
                tools.set_socks5_enabled(False)
                return

            self._proxy_thread = threading.Thread(
                target=tg_ws_proxy.run_proxy,
                args=(port, dc_opt, None, host),
                daemon=True)
            self._proxy_thread.start()
            self.socks5_toggle_btn.setText("OFF")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: #2d1621; border: 1px solid #ff5555; color: #ff5555; font-weight: bold; padding: 10px; }
                QPushButton:hover { background-color: #3d1b28; }
            """)
            self.log_area.append(f"SOCKS5 Proxy started: {host}:{port}")
        except Exception as e:
            self._socks5_running = False
            self.log_area.append(f"Error: {e}")
            tools.set_socks5_enabled(False)

    def open_list_editor(self):
        self.list_editor = ListEditorWindow(self.restart_func, self.start_menu, self.actions)
        self.list_editor.show()
        self.list_editor.activateWindow()

    def update_stats(self):
        up, down = tools.get_traffic_stats()
        self.traffic_label.setText(f"TRAFFIC | UP: {up} KB/s | DOWN: {down} KB/s")

    def run_ping_logic(self):
        h = self.host_input.text().strip()
        if h:
            self.log_area.append(f"Ping {h}: {tools.get_ping(h)} ms")

    def run_custom_dns_test(self):
        dns = self.dns_input.text().strip()
        if dns:
            res = tools.get_ping(dns)
            self.log_area.append(f"DNS {dns}: {res} ms")
            if isinstance(res, (float, int)):
                self.best_dns_found = dns
                self.apply_dns_btn.show()

    def run_best_dns_test(self):
        self.log_area.append("Scanning DNS...")
        ip, info = tools.find_best_dns()
        self.log_area.append(f"Best: {info}")
        if ip:
            self.best_dns_found = ip
            self.apply_dns_btn.show()

    def apply_best_dns(self):
        if self.best_dns_found:
            s, i = tools.set_system_dns(self.best_dns_found)
            self.log_area.append(f"DNS Set: {s} ({i})")
            self.apply_dns_btn.hide()

    def run_reset_dns(self):
        s, i = tools.reset_system_dns()
        self.log_area.append(f"DNS Reset: {s} ({i})")


tools_window = None


def open_tools(restart_func, start_menu=None, actions=None):
    global tools_window
    if tools_window is None:
        tools_window = NetworkToolsWindow(restart_func, start_menu, actions)
    tools_window.show()
    tools_window.activateWindow()


def update_menu_styles(start_menu, actions, active_version):
    for bat, action in actions.items():
        if bat.stem == active_version:
            font = QFont()
            font.setBold(True)
            action.setFont(font)
            if CHECK_ICON_PATH.exists():
                action.setIcon(QIcon(str(CHECK_ICON_PATH)))
        else:
            action.setFont(QFont())
            action.setIcon(QIcon())


def create_tray_app(bat_files, register_sleep_handler=None):
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    tray = QSystemTrayIcon(QIcon(str(ICON_PATH)))
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

    if register_sleep_handler:
        app_state = state.load_state()
        current_bat = app_state.get("last_bat")
        register_sleep_handler(quick_restart, current_bat)

    start_menu = QMenu("  ⚡ Start", menu)
    start_menu.setStyleSheet(menu.styleSheet())
    actions = {}
    for bat in bat_files:
        action = start_menu.addAction(bat.stem)
        action.triggered.connect(lambda checked, b=bat: (state.save_state(last_bat=b.stem, stopped=False), threading.Thread(target=lambda: service.start_service(b, b.stem), daemon=True).start(), update_menu_styles(start_menu, actions, b.stem)))
        actions[bat] = action

    menu.addMenu(start_menu)
    menu.addAction("  🌐 Internet Settings", lambda: subprocess.Popen("control ncpa.cpl", shell=True))
    menu.addAction("  🛠️ Network Tools", lambda: open_tools(quick_restart, start_menu, actions))
    menu.addSeparator()
    menu.addAction("  ⏹️ Stop", lambda: (state.save_state(last_bat=None, stopped=True), threading.Thread(target=lambda: (service.stop_service(), service.delete_service(), update_menu_styles(start_menu, actions, None)), daemon=True).start()))

    autostart_action = menu.addAction("  🔄 Autostart")
    autostart_action.setCheckable(True)
    autostart_action.setChecked(autostart.is_autostart_enabled())
    autostart_action.toggled.connect(lambda chk: autostart.enable_autostart() if chk else autostart.disable_autostart())

    menu.addSeparator()
    menu.addAction("  🚪 Exit", lambda: (service.stop_service(), QApplication.quit()))

    tray.activated.connect(lambda r: menu.popup(QCursor.pos()) if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.setContextMenu(menu)

    display_name = service.get_service_display_name()
    active_version = None
    if display_name:
        match = re.search(r'version\[([^\]]+)\]', display_name)
        if match:
            active_version = match.group(1)

    update_menu_styles(start_menu, actions, active_version)

    return app.exec_()
