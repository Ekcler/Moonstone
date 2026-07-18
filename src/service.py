"""Windows service management functions for Sakura Flow."""
import os
import subprocess
import re
import sys
import time
import logging
from pathlib import Path

try:
    from .config import SERVICE_NAME, BAT_DIR, CONSOLE_ENCODING
except ImportError:
    from src.config import SERVICE_NAME, BAT_DIR, CONSOLE_ENCODING


BAT_NAME = "_zapret_service.bat"


def _write_bat(executable, args):
    bat_path = BAT_DIR / BAT_NAME
    bat_path.parent.mkdir(parents=True, exist_ok=True)
    bin_dir = Path(executable).parent
    bat_content = f'@cd /d "{bin_dir}" && "{executable}" {args}'
    bat_path.write_text(bat_content, encoding="utf-8")
    logging.info(f"Written service bat: {bat_path}")
    return bat_path


def _wait_service_stopped(timeout=8):
    start = time.time()
    while time.time() - start < timeout:
        result = run_cmd(f'sc.exe query "{SERVICE_NAME}"')
        if result and "STOPPED" in result.stdout:
            return True
        time.sleep(0.5)
    return False


def restart_service(batch_path, display_version):
    if service_exists():
        stop_service()
        _wait_service_stopped()
        delete_service()
    create_service(batch_path, display_version)
    start_service(batch_path, display_version)

    for _ in range(10):
        time.sleep(0.5)
        result = run_cmd(f'sc.exe query "{SERVICE_NAME}"')
        if result and "RUNNING" in result.stdout:
            return True
    logging.error("Service failed to reach RUNNING state")
    return False


def run_cmd(cmd):
    logging.info(f"Выполнение команды: {cmd}")
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding=CONSOLE_ENCODING)
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
    with open(batch_path, 'r', encoding="utf-8") as f:
        bat_content = f.read()

    base_zapret = BAT_DIR
    bin_dir = base_zapret / "bin"
    lists_dir = base_zapret / "lists"

    game_filter_path = base_zapret / "utils" / "game_filter.enabled"
    if game_filter_path.exists():
        mode = game_filter_path.read_text("utf-8").strip().lower()
    else:
        mode = "disabled"

    if mode == "all":
        game_filter_tcp = "1024-65535"
        game_filter_udp = "1024-65535"
    elif mode == "tcp":
        game_filter_tcp = "1024-65535"
        game_filter_udp = "12"
    elif mode == "udp":
        game_filter_tcp = "12"
        game_filter_udp = "1024-65535"
    else:
        game_filter_tcp = "12"
        game_filter_udp = "12"

    game_filter = "1024-65535" if mode != "disabled" else "12"

    bat_content = bat_content.replace("%GameFilter%", game_filter)
    bat_content = bat_content.replace("%GameFilterTCP%", game_filter_tcp)
    bat_content = bat_content.replace("%GameFilterUDP%", game_filter_udp)

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
    bat_path = _write_bat(executable, args)
    service_display = f"Sakura Flow version[{display_version}]"
    bin_path_value = f'cmd.exe /c "{bat_path}"'

    cmd_args = [
        'sc.exe', 'create', SERVICE_NAME, 'start=', 'auto',
        'displayname=', service_display, 'binPath=', bin_path_value
    ]
    subprocess.run(cmd_args, capture_output=True, text=True, encoding=CONSOLE_ENCODING)


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
