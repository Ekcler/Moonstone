"""Main entry point for Sakura Flow application."""
import sys
import logging
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
else:
    from . import admin, ui, config

# Настройка логирования
logging.basicConfig(
    filename=config.LOG_FILE,
    filemode="w",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def main():
    """Точка входа в приложение."""
    logging.info("Запуск Sakura Flow")
    
    # Проверка прав администратора
    if not admin.is_admin():
        logging.info("Запрос прав администратора...")
        admin.run_as_admin()
    
    # --- ВОТ ТУТ ИЗМЕНЕНИЕ ---
    # Получаем все .bat файлы, кроме service.bat (чтобы он не мозолил глаза в меню)
    # Берем все .bat, кроме вспомогательных service.bat и самого general.bat
    bat_files = [
        f for f in config.BAT_DIR.glob("*.bat") 
        if f.name.lower() not in ["service.bat", "general.bat"]
    ]

    
    # Запуск интерфейса
    sys.exit(ui.create_tray_app(bat_files))

if __name__ == "__main__":
    main()
