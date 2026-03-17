import sys
import os
from pathlib import Path

# --- КРИТИЧЕСКИЙ ФИКС ПУТЕЙ ДЛЯ ОДНОГО ФАЙЛА ---
if getattr(sys, 'frozen', False):
    # Если запущен .exe (--onefile), все ресурсы лежат в Temp папке _MEIPASS
    # Но логи и конфиги должны лежать РЯДОМ с .exe на диске
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Если запущен из VS Code
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    BASE_DIR = BUNDLE_DIR

SERVICE_NAME = "SakuraFlowService"
TASK_NAME = "SakuraFlowAutostart"

# Иконки и Батники берем из BUNDLE_DIR (внутри экзешника)
ICON_PATH = BUNDLE_DIR / "icons" / "moonstone.ico"
CHECK_ICON_PATH = BUNDLE_DIR / "icons" / "check.ico"
BAT_DIR = BUNDLE_DIR / "zapret"

# Логи и состояние сохраняем в BASE_DIR (рядом с .exe, чтобы не стирались)
LOG_FILE = BASE_DIR / "sakura_flow.log"
STATE_FILE = BASE_DIR / "sakura_state.json"
# В файле src/config.py
ENCODING = "cp866" 

