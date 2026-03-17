"""Windows service management functions for Sakura Flow."""
import subprocess
import re
import sys
import logging
import os
from pathlib import Path

# Импортируем настройки из нашего исправленного конфига
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
    """Ультра-парсинг: маскируем Telegram под Microsoft Windows Update."""
    logging.info(f"Разбор стратегии: {batch_path}")
    with open(batch_path, 'r', encoding=ENCODING) as f:
        bat_content = f.read()

    base_zapret = BAT_DIR 
    bin_dir = base_zapret / "bin"
    lists_dir = base_zapret / "lists"

    # СТРАТЕГИЯ: На портах ТГ прикидываемся Майкрософтом (используем твой .bin файл)
    # Это самый мощный способ пробить "умные" блокировки в 2026-м
    ghost_rules = (
        f"--filter-tcp=5222,8888,8443 --dpi-desync=fake,multisplit "
        f"--dpi-desync-split-pos=1 --dpi-desync-fooling=md5sig --dpi-desync-repeats=6 "
        f"--dpi-desync-split-seqovl-pattern=\"{bin_dir}\\tls_microsoft.bin\" "
        f"--dpi-desync-fake-tls-mod=rnd,dupsid,sni=wcpstatic.microsoft.com --new "
    )

    # Ищем основную команду запуска из батника
    start_match = re.search(r'start\s+"[^"]*"\s+/min\s+"([^"]+)"\s+(.+)', bat_content, re.DOTALL)
    executable = str(bin_dir / "winws.exe")
    args = start_match.group(2).strip().replace('^', '').replace('\n', ' ').strip()

    # Принудительно добавляем порты ТГ в общий перехват драйвера
    if "--wf-tcp=" in args:
        args = args.replace("--wf-tcp=", "--wf-tcp=5222,8888,")
    else:
        args = "--wf-tcp=80,443,5222,8888 " + args

    # Склеиваем: Правила-призраки для ТГ + Твой рабочий конфиг для Ютуба
    final_args = ghost_rules + args

    # Подстановка путей
    replacements = {
        "%BIN%": str(bin_dir) + "\\",
        "%LISTS%": str(lists_dir) + "\\",
        "%~dp0": str(base_zapret) + "\\",
        "%GameFilter%": "1-65535"
    }

    for macro, real_path in replacements.items():
        final_args = final_args.replace(macro, real_path)

    final_args = final_args.replace("\\\\", "\\")
    return executable, final_args


def create_service(batch_path, display_version):
    """Создание службы в Windows."""
    executable, args = parse_bat_file(batch_path)
    service_display = f"Sakura flow [{display_version}]"
    quoted_exe = f'"{executable}"' if ' ' in str(executable) else str(executable)
    bin_path_value = f'{quoted_exe} {args}'
    
    cmd_args = [
        'sc.exe', 'create', SERVICE_NAME, 'start=', 'auto',
        'displayname=', service_display, 'binPath=', bin_path_value
    ]
    subprocess.run(cmd_args, capture_output=True, text=True, encoding=ENCODING)

def start_service(batch_path, display_version):
    """Остановка старой и запуск новой службы."""
    # ПРИНУДИТЕЛЬНО убиваем висящие процессы winws перед стартом
    subprocess.run("taskkill /f /im winws.exe >nul 2>&1", shell=True)
    
    if service_exists():
        stop_service()
        delete_service()
    create_service(batch_path, display_version)
    run_cmd(f'sc.exe start "{SERVICE_NAME}"')

def stop_service():
    """Остановка службы и драйвера."""
    if service_exists():
        run_cmd(f'sc.exe stop "{SERVICE_NAME}"')
        run_cmd('sc.exe stop "WinDivert"')
    # Убиваем процесс, если служба зависла
    subprocess.run("taskkill /f /im winws.exe >nul 2>&1", shell=True)

def delete_service():
    """Удаление службы из системы."""
    if service_exists():
        run_cmd(f'sc.exe delete "{SERVICE_NAME}"')
