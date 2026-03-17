"""Main entry point for Sakura Flow application."""
import sys
import logging
import threading
from pathlib import Path

# Обработка путей для запуска
if __name__ == "__main__":
    file_path = Path(__file__).resolve()
    parent_dir = file_path.parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    try:
        import src
        sys.modules['src'] = src
    except:
        pass
    from src import admin, ui, config
    from src.proxy import engine  # <-- ИМПОРТИРУЕМ НАШ МОНСТР-ДВИЖОК
else:
    from . import admin, ui, config
    from .proxy import engine

# Настройка логирования
logging.basicConfig(
    filename=config.LOG_FILE,
    filemode="w",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def start_ws_proxy():
    """Фоновая функция для запуска WebSocket прокси."""
    # Стандартные IP серверов Telegram
    default_dc_ips = {
        1: '149.154.175.50',
        2: '149.154.167.220',
        3: '149.154.175.100',
        4: '149.154.167.91',
        5: '91.108.56.130'
    }
    try:
        logging.info("🚀 Запуск фонового TG WebSocket Proxy на 127.0.0.1:1080...")
        # Запускаем блокирующую функцию прокси
        engine.run_proxy(port=1080, dc_opt=default_dc_ips, host='127.0.0.1')
    except Exception as e:
        logging.error(f"❌ Критическая ошибка прокси: {e}")

def main():
    """Точка входа в приложение."""
    logging.info("Запуск Sakura Flow")  
    
    # Проверка прав администратора
    if not admin.is_admin():
        logging.info("Запрос прав администратора...")
        admin.run_as_admin()
        return  # Прерываем выполнение в текущем процессе
    
    # --- ЗАПУСКАЕМ ТЕЛЕГРАМ-ПРОКСИ В ФОНЕ ---
    proxy_thread = threading.Thread(target=start_ws_proxy, daemon=True)
    proxy_thread.start()
    
    # Получаем все .bat файлы
    bat_files = [
        f for f in config.BAT_DIR.glob("*.bat") 
        if f.name.lower() not in ["service.bat", "general.bat"]
    ]
    
    # Запуск интерфейса
    sys.exit(ui.create_tray_app(bat_files))

if __name__ == "__main__":
    main()
