"""Main entry point for Sakura Flow application."""
import sys
import os
import logging
import threading
import time
from pathlib import Path

try:
    import win32api
    import win32con
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    internal_dir = BASE_DIR / "_internal"
    if str(internal_dir) not in sys.path:
        sys.path.insert(0, str(internal_dir))
else: 
    file_path = Path(__file__).resolve()    
    BASE_DIR = file_path.parent.parent
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

try:
    import src  
    sys.modules['src'] = src    
    from src import admin, ui, config, service, tools, state, autostart
except ImportError:
    import admin, ui, config, service, tools, state, autostart

def _set_defaults():
    app_state = state.load_state()
    if app_state.get("game_filter_mode") is None:
        tools.set_game_filter_mode("all")
        state.save_state(game_filter_mode="all")
    if app_state.get("ipset_mode") is None:
        tools.set_ipset_mode("any")
        state.save_state(ipset_mode="any")

try:
    import tg_ws_proxy 
except ImportError:
    try:
        from src import tg_ws_proxy
    except ImportError:
        tg_ws_proxy = None

logging.basicConfig(
    filename=config.LOG_FILE,
    filemode="w",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

_current_bat = None
_restart_func = None

def on_wake():
    global _current_bat, _restart_func
    logging.info("Компьютер проснулся! Проверяю службу...")
    
    if _current_bat and _restart_func:
        time.sleep(2)
        try:
            service.stop_service()
            service.delete_service()
            _restart_func()
            logging.info("Служба перезапущена после пробуждения")
        except Exception as e:
            logging.error(f"Ошибка перезапуска службы: {e}")
    
    app_state = state.load_state()
    if app_state.get("mtproto_enabled", False):
        time.sleep(3)
        try:
            port = app_state.get("mtproto_port", 1443)
            host = app_state.get("mtproto_host", "127.0.0.1")
            secret = app_state.get("mtproto_secret", None)
            tools.stop_mtproto_proxy(port=port, host=host)
            time.sleep(1)
            tools.start_mtproto_proxy(port=port, host=host, secret=secret)
            logging.info("MTProto прокси перезапущен после пробуждения")
        except Exception as e:
            logging.error(f"Ошибка перезапуска MTProto прокси: {e}")

def register_sleep_handler(restart_func, current_bat):
    global _current_bat, _restart_func
    _current_bat = current_bat
    _restart_func = restart_func
    
    if not HAS_WIN32:
        logging.info("win32api не установлен, обработка сна недоступна")
        return
    
    try:
        def WndProc(hwnd, msg, wParam, lParam):
            if msg == win32con.WM_POWERBROADCAST:
                if wParam == win32con.PBT_APMRESUMEAUTOMATIC:
                    logging.info("Событие пробуждения!")
                    threading.Thread(target=on_wake, daemon=True).start()
            return win32gui.DefWindowProc(hwnd, msg, wParam, lParam)
        
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = WndProc
        wc.lpszClassName = "SakuraFlowPower"
        win32gui.RegisterClass(wc)
        hwnd = win32gui.CreateWindow("SakuraFlowPower", "SakuraFlow", 0, 0, 0, 0, 0, 0, 0, 0, None)
        
        logging.info("Обработчик сна зарегистрирован")
    except Exception as e:
        logging.error(f"Ошибка регистрации обработчика сна: {e}")

def main():
    try:
        _main_inner()
    except Exception as e:
        logging.error(f"FATAL: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

def _main_inner():
    logging.info(f"START SAKURA FLOW. CWD: {os.getcwd()}")
    
    if not admin.is_admin():
        logging.info("Запрос прав администратора...")
        admin.run_as_admin()
        return
    
    autostart.fix_autostart_path()
    
    _set_defaults()

    bat_files = [
        f for f in config.BAT_DIR.glob("*.bat") 
        if f.name.lower() not in ["service.bat", "general.bat"]
    ]

    app_state = state.load_state()
    if app_state.get("mtproto_enabled", False):
        logging.info("[MTPROTO] Восстановление прокси после запуска")
        port = app_state.get("mtproto_port", 1443)
        host = app_state.get("mtproto_host", "127.0.0.1")
        secret = app_state.get("mtproto_secret", "efac191ac9b83e4c0c8c4e5e7c6a6b6d")
        if not tools.start_mtproto_proxy(port=port, host=host, secret=secret):
            logging.warning("[MTPROTO] Не удалось восстановить прокси")

    last_bat = app_state.get("last_bat")
    if last_bat:
        logging.info(f"[STRATEGY] Восстановление стратегии: {last_bat}")
        for b in bat_files:
            if b.stem == last_bat:
                threading.Thread(target=lambda b=b: service.start_service(b, b.stem), daemon=True).start()
                break

    exit_code = ui.create_tray_app(bat_files, register_sleep_handler)
    
    app_state = state.load_state()
    port = app_state.get("mtproto_port", 1443)
    host = app_state.get("mtproto_host", "127.0.0.1")
    tools.stop_mtproto_proxy(port=port, host=host)
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()  # вызовет _main_inner через main()
