"""Windows service management functions for Sakura Flow (Final Fix)."""
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
    logging.info(f"Выполнение команды: {cmd}")
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding=ENCODING)
    except Exception as e:
        logging.error(f"Ошибка команды: {e}")
        return None


def service_exists():
    result = run_cmd(f'sc.exe query "{SERVICE_NAME}"')
    return result and result.stdout


def get_service_display_name():
    if not service_exists():
        return None
    result = run_cmd(f'sc.exe qc "{SERVICE_NAME}"')
    if result and result.returncode == 0:
        match = re.search(r'DISPLAY_NAME\s*:\s*(.+)', result.stdout)
        if match:
            return match.group(1).strip()
    return None


def parse_bat_file(batch_path):
    logging.info(f"Разбор стратегии: {batch_path}")
    with open(batch_path, 'r', encoding=ENCODING) as f:
        bat_content = f.read()

    base_zapret = BAT_DIR
    bin_dir = base_zapret / "bin"
    lists_dir = base_zapret / "lists"
    game_ports = "1-65535"
    bat_content = bat_content.replace("%GameFilter%", game_ports)

    start_match = re.search(r'start\s+"[^"]*"\s+/min\s+"?[^"\s]+"?\s+(.+)', bat_content, re.DOTALL)
    if not start_match:
        sys.exit("Ошибка: winws.exe не найден в батнике")

    executable = str(bin_dir / "winws.exe")
    args = start_match.group(1).strip().replace('^', '').replace('\n', ' ').strip()

    replacements = {
        "%BIN%": str(bin_dir) + "\\",
        "%LISTS%": str(lists_dir) + "\\",
        "%~dp0": str(base_zapret) + "\\"
    }
    for macro, real_path in replacements.items():
        args = args.replace(macro, real_path)

    args = args.replace("\\\\", "\\")
    return executable, args


def create_service(batch_path, display_version):
    executable, args = parse_bat_file(batch_path)
    bin_dir = Path(executable).parent
    service_display = f"Sakura Flow DPI Bypass version[{display_version}]"
    bin_path_value = f'cmd.exe /c "cd /d "{bin_dir}" && "{executable}" {args}"'

    cmd_args = [
        'sc.exe', 'create', SERVICE_NAME, 'start=', 'auto',
        'displayname=', service_display, 'binPath=', bin_path_value
    ]
    subprocess.run(cmd_args, capture_output=True, text=True, encoding=ENCODING)


def start_service(batch_path, display_version):
    if service_exists():
        stop_service()
        delete_service()

    create_service(batch_path, display_version)
    run_cmd(f'sc.exe start "{SERVICE_NAME}"')


def stop_service():
    if service_exists():
        logging.info("Остановка SakuraFlowService и очистка процессов...")
        run_cmd(f'sc.exe stop "{SERVICE_NAME}"')
        run_cmd('taskkill /F /IM winws.exe /T')
        run_cmd('sc.exe stop "WinDivert"')
    else:
        return None


def delete_service():
    if service_exists():
        run_cmd(f'sc.exe delete "{SERVICE_NAME}"')
    else:
        return None
