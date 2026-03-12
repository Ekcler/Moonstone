"""UI/Tray interface functions for Sakura Flow."""
import subprocess
import re
import sys
import threading
import logging
from pathlib import Path

# Добавлен QCursor в импорты для работы ЛКМ
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QFont, QCursor
from PyQt5.QtCore import Qt

# Импорты из твоего проекта
try:
    from .config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from . import service, autostart, state
except ImportError:
    from src.config import ICON_PATH, CHECK_ICON_PATH, BASE_DIR
    from src import service, autostart, state

def open_dns_settings():
    """Открывает окно сетевых подключений Windows."""
    try:
        subprocess.Popen("control ncpa.cpl", shell=True)
        logging.info("Открыто окно настроек сетевых подключений")
    except Exception as e:
        logging.error(f"Ошибка при открытии DNS: {e}")

def create_start_handler(batch_path, start_menu, actions):
    """Обработчик запуска сервиса."""
    def handler():
        display_version = batch_path.stem
        state.save_state(last_bat=batch_path.stem, stopped=False)
        threading.Thread(
            target=lambda: service.start_service(batch_path, display_version),
            daemon=True
        ).start()
        update_menu_styles(start_menu, actions, batch_path.stem)
    return handler

def on_stop(start_menu, actions):
    """Обработчик остановки."""
    state.save_state(last_bat=None, stopped=True)
    threading.Thread(
        target=lambda: (
            service.stop_service(),
            service.delete_service(),
            update_menu_styles(start_menu, actions, None)
        ),
        daemon=True
    ).start()

def update_menu_styles(start_menu, actions, active_version):
    """Подсветка активного батника (жирный шрифт + иконка)."""
    try:
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
        start_menu.update()
    except Exception as e:
        logging.error(f"Ошибка обновления стилей: {e}")

def create_tray_app(bat_files):
    """Создание основного приложения трея."""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = QSystemTrayIcon(QIcon(str(ICON_PATH)))
    tray.setToolTip("Sakura Flow")

    menu = QMenu()
    
    menu.setStyleSheet("""
        QMenu {
            background-color: #0f0a12; 
            color: #ffffff;
            border: 1px solid #3d1b28;
            font-size: 14px;
        }
        QMenu::item { padding: 6px 28px 6px 12px; }
        QMenu::item:selected { background-color: #2d1621; }
        QMenu::separator { height: 1px; background: #3d1b28; margin: 4px; }
    """)

    # --- START ---
    start_menu = QMenu("  Start", menu)
    start_menu.setIcon(QIcon(str(ICON_PATH)))
    start_menu.setStyleSheet(menu.styleSheet())
    
    actions = {}
    for bat in bat_files:
        action = start_menu.addAction(bat.stem)
        action.triggered.connect(create_start_handler(bat, start_menu, actions))
        actions[bat] = action
    menu.addMenu(start_menu)

    # --- DNS ---
    dns_action = menu.addAction("  🌐 DNS")
    dns_action.triggered.connect(open_dns_settings)

    menu.addSeparator()

    # --- STOP / AUTOSTART ---
    stop_action = menu.addAction("  Stop")
    stop_action.triggered.connect(lambda: on_stop(start_menu, actions))

    autostart_action = menu.addAction("  Autostart")
    autostart_action.setCheckable(True)
    autostart_action.setChecked(autostart.is_autostart_enabled())
    autostart_action.toggled.connect(lambda chk: autostart.enable_autostart() if chk else autostart.disable_autostart())

    menu.addSeparator()

    # --- EXIT ---
    exit_action = menu.addAction("  Exit")
    exit_action.triggered.connect(lambda: (service.stop_service(), tray.hide(), QApplication.quit()))

    # --- ЛОГИКА ЛКМ (Левая кнопка мыши) ---
    def on_tray_activated(reason):
        # 3 - это Trigger (ЛКМ), 2 - это DoubleClick
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            # Показываем меню в позиции курсора
            menu.popup(QCursor.pos())

    tray.activated.connect(on_tray_activated)

    # Привязываем меню к ПКМ (стандартно)
    tray.setContextMenu(menu)
    tray.show()

    # Восстановление состояния при запуске
    display_name = service.get_service_display_name()
    active_version = None
    if display_name:
        match = re.search(r'version\[([^\]]+)\]', display_name)
        if match: active_version = match.group(1)
    update_menu_styles(start_menu, actions, active_version)

    # Автозапуск последнего сервиса
    app_state = state.load_state()
    if app_state["last_bat"] and not app_state["stopped"]:
        for bat in bat_files:
            if bat.stem == app_state["last_bat"]:
                threading.Thread(target=lambda: service.start_service(bat, bat.stem), daemon=True).start()
                update_menu_styles(start_menu, actions, bat.stem)
                break

    return app.exec_()
