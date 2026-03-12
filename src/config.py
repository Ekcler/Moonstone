"""Configuration constants for Sakura Flow application."""
import sys
import os
from pathlib import Path

# Названия
SERVICE_NAME = "SakuraFlowService"
TASK_NAME = "SakuraFlowAutostart"

# КОРРЕКТНОЕ ОПРЕДЕЛЕНИЕ ПУТИ
if getattr(sys, 'frozen', False):
    # Если запущен EXE, берем путь к папке, где лежит сам EXE
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Если запущен скрипт, берем корень проекта
    BASE_DIR = Path(__file__).resolve().parent.parent

# Пути к файлам (теперь они будут искаться рядом с SakuraFlow.exe)
ICON_PATH = BASE_DIR / "icons" / "moonstone.ico"
CHECK_ICON_PATH = BASE_DIR / "icons" / "check.ico"
BAT_DIR = BASE_DIR / "zapret"
LOG_FILE = BASE_DIR / "moonstone.log"
STATE_FILE = BASE_DIR / "moonstone_state.json"

# Кодировка для Windows батников
ENCODING = "cp866" 
