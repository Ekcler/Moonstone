"""Main entry point for Sakura Flow application with TG Proxy."""
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

def start_proxy_thread():
    app_state = state.load_state()
    auto_switch = app_state.get("auto_switch_enabled", False)
    
    if auto_switch:
        proxies = app_state.get("proxies", state.DEFAULT_PROXIES)
        enabled_proxies = [p for p in proxies if p.get("enabled", True)]
        
        if len(enabled_proxies) >= 2:
            for proxy in enabled_proxies:
                tools.start_socks5_proxy(port=proxy['port'], host=proxy['host'])
            
            timeout = app_state.get("auto_switch_timeout", 5)
            tools.set_auto_switch_config(True, timeout=timeout)
            tools.start_auto_switch()
            
            logging.info(f"[SOCKS5] Multi-proxy started: {len(enabled_proxies)} proxies, auto-switch enabled")
            return True
        else:
            logging.info("[SOCKS5] Not enough enabled proxies for auto-switch")
    
    port = app_state.get("proxies", state.DEFAULT_PROXIES)[0].get("port", 1080)
    host = app_state.get("proxies", state.DEFAULT_PROXIES)[0].get("host", "127.0.0.1")
    return tools.start_socks5_proxy(port=port, host=host)


def stop_proxy_thread():
    tools.stop_auto_switch()
    tools._stop_all_proxies()

_current_bat = None
_restart_func = None

def on_wake():
    global _current_bat, _restart_func
    logging.info("Компьютер проснулся! Проверяю службу...")
    
    if _current_bat and _restart_func:
        time.sleep(2)
        try:
            service.stop_service()
            time.sleep(1)
            _restart_func()
            logging.info("Служба перезапущена после пробуждения")
        except Exception as e:
            logging.error(f"Ошибка перезапуска службы: {e}")
    
    app_state = state.load_state()
    auto_switch = app_state.get("auto_switch_enabled", False)
    
    if app_state.get("socks5_enabled", False) or auto_switch:
        time.sleep(3)
        try:
            if auto_switch:
                proxies = app_state.get("proxies", state.DEFAULT_PROXIES)
                enabled_proxies = [p for p in proxies if p.get("enabled", True)]
                
                for p in proxies:
                    tools.stop_socks5_proxy(port=p['port'], host=p['host'])
                time.sleep(1)
                
                for proxy in enabled_proxies:
                    tools.start_socks5_proxy(port=proxy['port'], host=proxy['host'])
                
                timeout = app_state.get("auto_switch_timeout", 5)
                tools.set_auto_switch_config(True, timeout=timeout)
                tools.start_auto_switch()
                
                logging.info(f"Auto-switch перезапущен ({len(enabled_proxies)} proxies)")
            else:
                stop_proxy_thread()
                time.sleep(1)
                start_proxy_thread()
                logging.info("Прокси перезапущен после пробуждения")
        except Exception as e:
            logging.error(f"Ошибка перезапуска прокси: {e}")

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
    logging.info(f"START SAKURA FLOW. CWD: {os.getcwd()}")
    
    if not admin.is_admin():
        logging.info("Запрос прав администратора...")
        admin.run_as_admin()
        return
    
    autostart.fix_autostart_path()
    
    tools.start_auto_monitor()
    
    app_state = state.load_state()
    if app_state.get("mtproto_enabled", False):
        logging.info("[MTPROTO] Восстановление прокси после запуска")
        port = app_state.get("mtproto_port", 1080)
        host = app_state.get("mtproto_host", "127.0.0.1")
        secret = app_state.get("mtproto_secret", "efac191ac9b83e4c0c8c4e5e7c6a6b6d")
        tools.start_socks5_proxy(port=port, host=host, secret=secret)
    elif app_state.get("socks5_enabled", False):
        logging.info("[SOCKS5] Восстановление прокси после запуска")
        start_proxy_thread()
    
    bat_files = [
        f for f in config.BAT_DIR.glob("*.bat") 
        if f.name.lower() not in ["service.bat", "general.bat"]
    ]
    
    exit_code = ui.create_tray_app(bat_files, register_sleep_handler)
    
    tools.stop_auto_monitor()
    stop_proxy_thread()
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
