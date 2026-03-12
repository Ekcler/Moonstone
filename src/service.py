"""Windows service management functions for Sakura Flow."""
import subprocess
import re
import sys
import logging
from pathlib import Path

try:
    from .config import SERVICE_NAME, BAT_DIR, ENCODING
except ImportError:
    from src.config import SERVICE_NAME, BAT_DIR, ENCODING

def run_cmd(cmd):
    """Выполнение команды оболочки."""
    logging.info(f"Выполнение команды: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding=ENCODING)
        return result
    except Exception as e:
        logging.error(f"Ошибка команды: {e}")
        return None

def service_exists():
    """Проверка существования службы."""
    result = run_cmd(f'sc.exe query "{SERVICE_NAME}"')
    return result and (SERVICE_NAME in result.stdout)

def get_service_display_name():
    """Получение имени службы."""
    if not service_exists(): return None
    result = run_cmd(f'sc.exe qc "{SERVICE_NAME}"')
    if result and result.returncode == 0:
        match = re.search(r'DISPLAY_NAME\s*:\s*(.+)', result.stdout)
        if match: return match.group(1).strip()
    return None

def parse_bat_file(batch_path):
    """Парсинг .bat файла с подстановкой портов Rocket League."""
    logging.info(f"Разбор стратегии: {batch_path}")
    with open(batch_path, 'r', encoding=ENCODING) as f:
        bat_content = f.read()

    base_zapret = batch_path.parent
    bin_dir = base_zapret / "bin"
    lists_dir = base_zapret / "lists"
    configs_dir = base_zapret / "configs"

    # 1. Вшиваем порты Rocket League
    game_ports = "1-65535"
    bat_content = bat_content.replace("%GameFilter%", game_ports)

    # 2. Извлекаем команду winws.exe
    start_match = re.search(r'start\s+"[^"]*"\s+/min\s+"([^"]+)"\s+(.+)', bat_content, re.DOTALL)
    if not start_match:
        sys.exit("Ошибка: winws.exe не найден в батнике")

    executable = str(bin_dir / "winws.exe")
    args = start_match.group(2).strip().replace('^', '').replace('\n', ' ').strip()

    # 3. Заменяем макросы путей
    replacements = {
        "%BIN%": str(bin_dir) + "\\",
        "%LISTS%": str(lists_dir) + "\\",
        "%CONFIGS%": str(configs_dir) + "\\",
        "%~dp0": str(base_zapret) + "\\"
    }

    for macro, real_path in replacements.items():
        args = args.replace(macro, real_path)
        executable = executable.replace(macro, real_path)

    # Очистка путей от двойных слешей
    args = args.replace("\\\\", "\\")
    
    logging.info(f"Команда готова. EXE: {executable}")
    return executable, args

def create_service(batch_path, display_version):
    """Создание службы."""
    executable, args = parse_bat_file(batch_path)
    service_display = f"Sakura Flow DPI Bypass version[{display_version}]"
    quoted_exe = f'"{executable}"' if ' ' in str(executable) else str(executable)
    bin_path_value = f'{quoted_exe} {args}'
    
    cmd_args = [
        'sc.exe', 'create', SERVICE_NAME, 'start=', 'auto',
        'displayname=', service_display, 'binPath=', bin_path_value
    ]
    subprocess.run(cmd_args, capture_output=True, text=True, encoding=ENCODING)

def start_service(batch_path, display_version):
    """Запуск службы."""
    if service_exists():
        stop_service()
        delete_service()
    create_service(batch_path, display_version)
    run_cmd(f'sc.exe start "{SERVICE_NAME}"')

def stop_service():
    """Остановка."""
    if service_exists():
        run_cmd(f'sc.exe stop "{SERVICE_NAME}"')
        run_cmd('sc.exe stop "WinDivert"')

def delete_service():
    """Удаление."""
    if service_exists():
        run_cmd(f'sc.exe delete "{SERVICE_NAME}"')
