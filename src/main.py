"""Main entry point for Sakura Flow application with TG Proxy."""
import sys
import os
import logging
import threading
from pathlib import Path

# --- УНИВЕРСАЛЬНАЯ ИЗОЛЯЦИЯ ПУТЕЙ (ДЛЯ СКРИПТА И EXE) ---
if getattr(sys, 'frozen', False):
    # ПУТЬ ДЛЯ EXE: Берем папку, где лежит SakuraFlow.exe
    BASE_DIR = Path(sys.executable).resolve().parent
    # Добавляем корень в пути поиска, чтобы видеть tg_ws_proxy.py рядом с EXE
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    # Добавляем _internal для импорта src
    internal_dir = BASE_DIR / "_internal"
    if str(internal_dir) not in sys.path:
        sys.path.insert(0, str(internal_dir))
else:
    # ПУТЬ ДЛЯ СКРИПТА: Стандартная логика
    file_path = Path(__file__).resolve()
    BASE_DIR = file_path.parent.parent
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

# Пытаемся импортировать модули из src
try:
    import src
    sys.modules['src'] = src
    from src import admin, ui, config
except ImportError:
    # Если запущен из src напрямую
    import admin, ui, config

# Пытаемся импортировать ТГ-движок (теперь он точно найдется)
try:
    import tg_ws_proxy 
except ImportError:
    # Если файл лежит в src во время разработки
    try:
        from src import tg_ws_proxy
    except ImportError:
        tg_ws_proxy = None

# Настройка логирования (используем config.LOG_FILE, который уже привязан к BASE_DIR)
logging.basicConfig(
    filename=config.LOG_FILE,
    filemode="w",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def start_tg_proxy_thread():
    """Запуск WebSocket-прокси для Telegram на порту 1080."""
    if not tg_ws_proxy:
        logging.error("Движок Telegram (tg_ws_proxy.py) не найден!")
        return

    dc_opt = {
        1: '149.154.175.50', 2: '149.154.167.220',
        3: '149.154.175.100', 4: '149.154.167.220',
        5: '91.108.56.100'
    }
    try:
        logging.info("--- ЗАПУСК TG PROXY (127.0.0.1:1080) ---")
        tg_ws_proxy.run_proxy(port=1080, dc_opt=dc_opt, host='127.0.0.1')
    except Exception as e:
        logging.error(f"Ошибка WebSocket-прокси: {e}")

def main():
    """Точка входа в приложение."""
    logging.info(f"START SAKURA FLOW. CWD: {os.getcwd()}")
    
    if not admin.is_admin():
        logging.info("Запрос прав администратора...")
        admin.run_as_admin()
        return

    # Запуск ТГ-прокси в фоне
    proxy_thread = threading.Thread(target=start_tg_proxy_thread, daemon=True)
    proxy_thread.start()
    
    # Получаем список стратегий
    bat_files = [
        f for f in config.BAT_DIR.glob("*.bat") 
        if f.name.lower() not in ["service.bat", "general.bat"]
    ]
    
    sys.exit(ui.create_tray_app(bat_files))

if __name__ == "__main__":
    main()
