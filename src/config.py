import sys
from pathlib import Path

# Определение базы
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

SERVICE_NAME = "SakuraFlowService"
TASK_NAME = "SakuraFlowAutostart"

ICON_PATH = BASE_DIR / "icons" / "moonstone.ico"
CHECK_ICON_PATH = BASE_DIR / "icons" / "check.ico"

# ПАПКА С ЗАПРЕТОМ (Важно!)
BAT_DIR = BASE_DIR / "zapret"

# ФАЙЛЫ СОСТОЯНИЯ (Новые названия)
LOG_FILE = BASE_DIR / "sakura_flow.log"
STATE_FILE = BASE_DIR / "sakura_state.json"

ENCODING = "cp866"
