"""UI/Tray interface functions for Sakura Flow by Ekcler."""
import subprocess
import re
import sys
import threading
import time
import ctypes
import logging
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QTextEdit, QLabel, QMessageBox, QScrollArea)
from PyQt5.QtGui import QDesktopServices, QIcon, QFont, QCursor
from PyQt5.QtCore import QUrl, Qt, QTimer, QMetaObject, Q_ARG

try:
    myappid = 'ekcler.sakuraflow.v1.2'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

try:
    from .config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from . import service, autostart, state, tools
except ImportError:
    from src.config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from src import service, autostart, state, tools


class ListEditorWindow(QWidget):
    def __init__(self, restart_func, list_type="general", start_menu=None, actions=None):
        super().__init__()
        self.restart_func = restart_func
        self.list_type = list_type
        self.start_menu = start_menu
        self.actions = actions
        self.init_ui()

    def init_ui(self):
        if self.list_type == "general":
            self.setWindowTitle("Sakura Blocklist Editor")
            title = "Domains (one per line):"
            default_text = tools.read_blocklist()
        else:
            self.setWindowTitle("Sakura Ignore List Editor")
            title = "Domains to ignore (one per line):"
            default_text = tools.read_ignore_list()
        
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
        layout.addWidget(QLabel(title))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(default_text)
        layout.addWidget(self.text_edit)

        self.save_btn = QPushButton("SAVE AND RESTART SERVICE")
        self.save_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_btn)
        self.setLayout(layout)

    def save_data(self):
        if self.list_type == "general":
            tools.save_blocklist(self.text_edit.toPlainText())
        else:
            tools.save_ignore_list(self.text_edit.toPlainText())
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
        self.ignore_list_editor = None
        self._tg_proxy_on = False
        self._socks5_running = False
        self._auto_add_on = False
        self._ipv6_on = True
        self.init_ui()
        
        app_state = state.load_state()
        self.tg_port_input.setText(str(app_state.get("mtproto_port", 1080)))
        self.tg_host_input.setText(app_state.get("mtproto_host", "127.0.0.1"))
        self.tg_secret_input.setText(app_state.get("mtproto_secret", "efac191ac9b83e4c0c8c4e5e7c6a6b6d"))
        
        self._add_site_on = app_state.get("auto_add_enabled", False)
        self.add_site_interval_input.setText(str(app_state.get("auto_add_interval", 60)))
        if self._add_site_on:
            self.add_site_toggle_btn.setText("OFF")
            self.add_site_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(180, 60, 80, 0.4); border: 1px solid rgba(255, 85, 85, 0.4); color: #ff6b6b; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 77, 136, 0.3); border: 1px solid #ff4d88; }
            """)
        else:
            self.add_site_toggle_btn.setText("ON")
            self.add_site_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)
        
        if app_state.get("mtproto_enabled", False):
            self._socks5_running = True
            self.socks5_toggle_btn.setText("STOP")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(255, 77, 136, 0.25); border: 1px solid #ff4d88; color: #ff7aa2; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 122, 162, 0.35); border: 1px solid #ff7aa2; }
            """)
        
        self.log_area.append("Ready!")
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

    def log_append(self, text, color=None):
        """Thread-safe log append. color: 'green', 'red' or None."""
        if color:
            html = f'<span style="color: {color};">{text}</span>'
        else:
            html = text
        QMetaObject.invokeMethod(self.log_area, "append", Qt.QueuedConnection, Q_ARG(str, html))

    def init_ui(self):
        self.setWindowTitle("Sakura Flow Tools by Ekcler")
        self.setFixedSize(450, 750)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(Qt.Window)
        self.setStyleSheet("""
            QWidget { background-color: #0b0a12; color: #e8e8f0; font-family: 'Segoe UI'; }
            QLineEdit { 
                background-color: rgba(45, 35, 60, 0.6); 
                border: 1px solid rgba(108, 92, 231, 0.3); 
                padding: 5px; border-radius: 4px; color: #e8e8f0;
            }
            QLineEdit:focus { border: 1px solid #ff7aa2; }
            QPushButton { 
                background-color: rgba(255, 122, 162, 0.12); 
                border: 1px solid rgba(255, 122, 162, 0.35); 
                color: #ff7aa2; padding: 8px; border-radius: 4px; font-weight: 500;
            }
            QPushButton:hover { 
                background-color: rgba(255, 122, 162, 0.22); 
                border: 1px solid #ff4d88; 
            }
            QPushButton:pressed { background-color: rgba(255, 77, 136, 0.35); }
            QTextEdit { 
                background-color: rgba(18, 11, 26, 0.8); 
                border: 1px solid rgba(108, 92, 231, 0.25); 
                font-family: 'Consolas'; font-size: 11px; color: #c8c8d8;
            }
            QLabel { color: #ff7aa2; font-weight: 600; }
            QScrollArea { background-color: #0b0a12; border: none; }
        """)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: #0b0a12; border: none; }")
        
        scroll_content = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        layout.addWidget(QLabel("Blocklist Management:"))
        blocklist_row = QHBoxLayout()
        self.edit_list_btn = QPushButton("📝 Edit General Blocklist")
        self.edit_ignore_btn = QPushButton("📝 Edit Ignore List")
        blocklist_row.addWidget(self.edit_list_btn)
        blocklist_row.addWidget(self.edit_ignore_btn)
        layout.addLayout(blocklist_row)

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
        layout.addWidget(QLabel("MTPROTO PROXY:"))
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

        secret_layout = QHBoxLayout()
        secret_layout.addWidget(QLabel("Secret:"))
        self.tg_secret_input = QLineEdit()
        self.tg_secret_input.setPlaceholderText("efac191ac9b83e4c0c8c4e5e7c6a6b6d")
        self.tg_secret_input.setText("efac191ac9b83e4c0c8c4e5e7c6a6b6d")
        secret_layout.addWidget(self.tg_secret_input)
        self.copy_secret_btn = QPushButton("Copy")
        self.copy_secret_btn.setFixedWidth(60)
        secret_layout.addWidget(self.copy_secret_btn)
        layout.addLayout(secret_layout)

        self.socks5_toggle_btn = QPushButton("START")
        self.socks5_toggle_btn.setStyleSheet("""
            QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
            QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
        """)
        layout.addWidget(self.socks5_toggle_btn)

        layout.addSpacing(10)
        layout.addWidget(QLabel("AUTO ADD SITE:"))
        add_site_row = QHBoxLayout()
        self.add_site_toggle_btn = QPushButton("OFF")
        self.add_site_toggle_btn.setStyleSheet("""
            QPushButton { background-color: rgba(180, 60, 80, 0.4); border: 1px solid rgba(255, 85, 85, 0.4); color: #ff6b6b; font-weight: bold; padding: 10px; border-radius: 4px; }
            QPushButton:hover { background-color: rgba(255, 77, 136, 0.3); border: 1px solid #ff4d88; }
        """)
        add_site_row.addWidget(self.add_site_toggle_btn)
        self.add_site_interval_input = QLineEdit()
        self.add_site_interval_input.setPlaceholderText("interval (sec)")
        self.add_site_interval_input.setFixedWidth(150)
        add_site_row.addWidget(self.add_site_interval_input)
        add_site_row.addStretch()
        layout.addLayout(add_site_row)

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
        layout.addWidget(QLabel("IPv6:"))
        self.ipv6_toggle_btn = QPushButton("ON")
        self.ipv6_toggle_btn.setStyleSheet("""
            QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
            QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
        """)
        layout.addWidget(self.ipv6_toggle_btn)
        
        ipv6_warning = QLabel("⚠️ turn off if bypass does not work")
        ipv6_warning.setStyleSheet("color: #ff6b6b; font-size: 10px;")
        layout.addWidget(ipv6_warning)

        layout.addSpacing(10)
        self.traffic_label = QLabel("📊 TRAFFIC | UP: 0.0 KB/s | DOWN: 0.0 KB/s")
        self.traffic_label.setStyleSheet("color: #50fa7b; font-family: 'Consolas'; font-size: 12px;")
        layout.addWidget(self.traffic_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        
        scroll_content.setLayout(layout)
        scroll.setWidget(scroll_content)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

        self.edit_list_btn.clicked.connect(self.open_list_editor)
        self.edit_ignore_btn.clicked.connect(self.open_ignore_editor)
        self.ping_btn.clicked.connect(self.run_ping_logic)
        self.trace_btn.clicked.connect(lambda: tools.run_tracert(self.host_input.text()) if self.host_input.text() else None)
        self.test_dns_btn.clicked.connect(self.run_custom_dns_test)
        self.dns_best_btn.clicked.connect(self.run_best_dns_test)
        self.reset_dns_btn.clicked.connect(self.run_reset_dns)
        self.apply_dns_btn.clicked.connect(self.apply_best_dns)
        self.socks5_toggle_btn.clicked.connect(self.toggle_socks5_proxy)
        self.copy_secret_btn.clicked.connect(self.copy_secret)
        self.add_site_toggle_btn.clicked.connect(self.toggle_add_site)
        self.add_site_interval_input.textChanged.connect(self.on_add_site_interval_changed)
        self.ipv6_toggle_btn.clicked.connect(self.toggle_ipv6)

    def _update_socks5_btn_state(self):
        """Update button state based on actual proxy status."""
        if tools.is_any_proxy_running():
            self.socks5_toggle_btn.setText("STOP")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(255, 77, 136, 0.25); border: 1px solid #ff4d88; color: #ff7aa2; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 122, 162, 0.35); border: 1px solid #ff7aa2; }
            """)
        else:
            self.socks5_toggle_btn.setText("START")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)

    def toggle_add_site(self):
        self._add_site_on = not self._add_site_on
        state.save_state(auto_add_enabled=self._add_site_on)
        if self._add_site_on:
            self.add_site_toggle_btn.setText("OFF")
            self.add_site_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(180, 60, 80, 0.4); border: 1px solid rgba(255, 85, 85, 0.4); color: #ff6b6b; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 77, 136, 0.3); border: 1px solid #ff4d88; }
            """)
            self.add_site_toggle_btn.update()
            self.log_append("Auto add site enabled")
        else:
            self.add_site_toggle_btn.setText("ON")
            self.add_site_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)
            self.add_site_toggle_btn.update()
            self.log_append("Auto add site disabled")

    def on_add_site_interval_changed(self, val):
        try:
            interval = int(val)
            if interval > 0:
                state.save_state(auto_add_interval=interval)
        except ValueError:
            pass

    def toggle_ipv6(self):
        self._ipv6_on = not self._ipv6_on
        state.save_state(ipv6_enabled=self._ipv6_on)
        if self._ipv6_on:
            self.ipv6_toggle_btn.setText("ON")
            self.ipv6_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)
            tools.enable_ipv6()
            self.log_append("IPv6 enabled")
        else:
            self.ipv6_toggle_btn.setText("OFF")
            self.ipv6_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(180, 60, 80, 0.4); border: 1px solid rgba(255, 85, 85, 0.4); color: #ff6b6b; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 77, 136, 0.3); border: 1px solid #ff4d88; }
            """)
            tools.disable_ipv6()
            self.log_append("IPv6 disabled")
        self.log_append("Restart required for changes to take effect")

    def copy_secret(self):
        secret = self.tg_secret_input.text().strip()
        QApplication.clipboard().setText(secret)
        self.log_append(f"Secret copied: {secret}")

    def toggle_socks5_proxy(self):
        port = int(self.tg_port_input.text().strip() or "1080")
        host = self.tg_host_input.text().strip() or "127.0.0.1"
        secret = self.tg_secret_input.text().strip() or "efac191ac9b83e4c0c8c4e5e7c6a6b6d"
        
        state.save_state(
            mtproto_enabled=True,
            mtproto_port=port,
            mtproto_host=host,
            mtproto_secret=secret
        )
        
        self.log_append(f"[DEBUG] toggle_mtproto: {host}:{port}")
        
        if self.socks5_toggle_btn.text() == "STOP":
            self.log_append("Stopping MTPROTO proxy...")
            self.socks5_toggle_btn.setText("START")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)
            def do_stop():
                try:
                    tools.stop_socks5_proxy(port=port, host=host)
                    state.save_state(mtproto_enabled=False)
                    self.log_append("MTPROTO proxy stopped", "green")
                except Exception as e:
                    self.log_append(f"ERROR: {e}", "red")
            threading.Thread(target=do_stop, daemon=True).start()
        else:
            self.log_append("Starting MTPROTO proxy...")
            self.socks5_toggle_btn.setText("STOP")
            self.socks5_toggle_btn.setStyleSheet("""
                QPushButton { background-color: rgba(255, 77, 136, 0.25); border: 1px solid #ff4d88; color: #ff7aa2; font-weight: bold; padding: 10px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 122, 162, 0.35); border: 1px solid #ff7aa2; }
            """)
            def do_start():
                try:
                    success = tools.start_socks5_proxy(port=port, host=host, secret=secret)
                    if success:
                        self.log_append("MTPROTO proxy started", "green")
                    else:
                        self.log_append(f"Failed to start MTPROTO proxy on {host}:{port}", "red")
                except Exception as e:
                    self.log_append(f"ERROR: {e}", "red")
            threading.Thread(target=do_start, daemon=True).start()

    def update_proxy_btn_state(self, btn, is_on):
        if is_on:
            btn.setText("ON")
            btn.setStyleSheet("""
                QPushButton { background-color: rgba(45, 80, 60, 0.5); border: 1px solid rgba(123, 237, 159, 0.4); color: #7bed9f; font-weight: bold; padding: 5px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(46, 213, 115, 0.25); border: 1px solid #2ed573; }
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet("""
                QPushButton { background-color: rgba(180, 60, 80, 0.4); border: 1px solid rgba(255, 85, 85, 0.4); color: #ff6b6b; font-weight: bold; padding: 5px; border-radius: 4px; }
                QPushButton:hover { background-color: rgba(255, 77, 136, 0.3); border: 1px solid #ff4d88; }
            """)

    def open_list_editor(self):
        self.list_editor = ListEditorWindow(self.restart_func, "general", self.start_menu, self.actions)
        self.list_editor.show()
        self.list_editor.activateWindow()

    def open_ignore_editor(self):
        self.ignore_list_editor = ListEditorWindow(self.restart_func, "ignore", self.start_menu, self.actions)
        self.ignore_list_editor.show()
        self.ignore_list_editor.activateWindow()

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

    def toggle_strategy(btn, actions):
        """Toggle strategy on/off."""
        if tools.is_winws_running():
            state.save_state(last_bat=None, stopped=True)
            threading.Thread(target=lambda: (service.stop_service(), service.delete_service(), update_start_btn(btn, False)), daemon=True).start()
        else:
            app_state = state.load_state()
            last_bat = app_state.get("last_bat")
            if not last_bat:
                last_bat = bat_files[0].stem if bat_files else "zapret-general"
            bat_path = None
            for b in bat_files:
                if b.stem == last_bat:
                    bat_path = b
                    break
            if not bat_path:
                bat_path = bat_files[0]
            state.save_state(last_bat=bat_path.stem, stopped=False)
            threading.Thread(target=lambda: service.start_service(bat_path, bat_path.stem), daemon=True).start()
            update_start_btn(btn, True)

    def update_start_btn(btn, running):
        """Update Start button based on winws running state."""
        if running:
            btn.setText("  ⏹️ Stop")
            if CHECK_ICON_PATH.exists():
                btn.setIcon(QIcon(str(CHECK_ICON_PATH)))
        else:
            btn.setText("  ⚡ Start")
            btn.setIcon(QIcon())

    start_btn = QAction("  ⚡ Start", menu)
    update_start_btn(start_btn, tools.is_winws_running())
    start_btn.triggered.connect(lambda: toggle_strategy(start_btn, {}))
    menu.addAction(start_btn)
    menu.addAction("  🌐 Internet Settings", lambda: subprocess.Popen("control ncpa.cpl", shell=True))
    menu.addAction("  🛠️ Network Tools", lambda: open_tools(quick_restart, None, {}))
    menu.addSeparator()

    autostart_action = menu.addAction("  🔄 Autostart")
    autostart_action.setCheckable(True)
    autostart_action.setChecked(autostart.is_autostart_enabled())
    autostart_action.toggled.connect(lambda chk: autostart.enable_autostart() if chk else autostart.disable_autostart())

    menu.addSeparator()
    menu.addAction("  🚪 Exit", lambda: (service.stop_service(), QApplication.quit()))

    tray.activated.connect(lambda r: menu.popup(QCursor.pos()) if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.setContextMenu(menu)

    return app.exec_()