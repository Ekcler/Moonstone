import subprocess
import psutil
import socket
import threading
import time
import logging
import asyncio
import signal
import re
import os
from pathlib import Path
from ping3 import ping

try:
    from .config import BASE_DIR, ENCODING
    from . import state
except ImportError:
    from src.config import BASE_DIR, ENCODING
    from src import state

_last_io = None
LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-general.txt"
EXCLUDE_LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-exclude-user.txt"

def is_mtproto_enabled():
    return state.load_state().get("mtproto_enabled", False)


_proxies = {}
_proxy_lock = threading.Lock()


def get_ping(host):
    try:
        p = ping(host, unit='ms')
        if p:
            return round(p, 2)
        else:
            return 'Timeout'
    except:
        return 'Error'


def run_tracert(host):
    subprocess.Popen(['cmd', '/c', f'tracert {host} & pause'], creationflags=subprocess.CREATE_NEW_CONSOLE)


def get_traffic_stats():
    global _last_io
    try:
        net_io = psutil.net_io_counters()
        now_io = (net_io.bytes_sent, net_io.bytes_recv)
        if _last_io is None:
            _last_io = now_io
            return 0.0, 0.0
        up = (now_io[0] - _last_io[0]) / 1024
        down = (now_io[1] - _last_io[1]) / 1024
        _last_io = now_io
        return max(0, round(up, 1)), max(0, round(down, 1))
    except:
        return 0.0, 0.0


def read_blocklist():
    try:
        if not LIST_PATH.exists():
            return ""
        return LIST_PATH.read_text(encoding=ENCODING)
    except:
        return ""


def save_blocklist(text):
    try:
        LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIST_PATH.write_text(text.strip(), encoding=ENCODING)
        return True
    except:
        return False


def read_ignore_list():
    try:
        if not EXCLUDE_LIST_PATH.exists():
            return ""
        return EXCLUDE_LIST_PATH.read_text(encoding=ENCODING)
    except:
        return ""


def save_ignore_list(text):
    try:
        EXCLUDE_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXCLUDE_LIST_PATH.write_text(text.strip(), encoding=ENCODING)
        return True
    except:
        return False


def find_best_dns():
    dns_list = {"Cloudflare": "1.1.1.1", "Google": "8.8.8.8", "Yandex": "77.88.8.8", "Quad9": "9.9.9.9"}
    results = {}
    for name, ip in dns_list.items():
        p = get_ping(ip)
        if isinstance(p, (float, int)):
            results[name] = (ip, p)
    if not results:
        return None, "All DNS timed out"
    best_name = min(results, key=lambda k: results[k][1])
    return results[best_name][0], f"{best_name} [{results[best_name][0]}] ({results[best_name][1]}ms)"


def get_active_interface():
    try:
        for name, stats in psutil.net_if_stats().items():
            if stats.isup and not name.startswith("Loopback"):
                addrs = psutil.net_if_addrs().get(name, [])
                if any(a.family == 2 and not a.address.startswith("127.") for a in addrs):
                    return name
    except:
        pass
    return None


def set_system_dns(dns_ip):
    iface = get_active_interface()
    if not iface:
        return False, "Interface not found"
    try:
        subprocess.run(['netsh', 'interface', 'ip', 'set', 'dns', f'name={iface}', 'source=static', f'address={dns_ip}'], capture_output=True)
        return True, iface
    except Exception as e:
        return False, str(e)


def reset_system_dns():
    iface = get_active_interface()
    if not iface:
        return False, "Interface not found"
    try:
        subprocess.run(['netsh', 'interface', 'ip', 'set', 'dns', f'name={iface}', 'source=dhcp'], capture_output=True)
        return True, iface
    except Exception as e:
        return False, str(e)


def set_mtproto_enabled(enabled):
    state.save_state(mtproto_enabled=enabled)
    logging.info(f"[MTPROTO] Enabled: {enabled}")


def get_mtproto_enabled():
    return is_mtproto_enabled()


def _get_process_using_port(port):
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port:
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        return f"{proc.name()} (PID {conn.pid})"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return f"PID {conn.pid}"
        return None
    except Exception:
        return None


def start_mtproto_proxy(port=1080, host='127.0.0.1', secret=None):
    global _proxies
    
    key = (host, port)
    
    with _proxy_lock:
        if key in _proxies and _proxies[key]['thread'] and _proxies[key]['thread'].is_alive():
            if _check_mtproto_traffic(port):
                logging.info(f"[MTPROTO] Proxy {host}:{port} already running")
                return True
            else:
                logging.info(f"[MTPROTO] Proxy {host}:{port} thread dead but key exists, cleaning up")
                try:
                    del _proxies[key]
                except:
                    pass

    logging.debug(f"[MTPROTO] Proxy {host}:{port} starting...")

    try:
        from src.proxy.config import proxy_config
        from src import tg_ws_proxy
        logging.info(f"[MTPROTO] Import via 'from src' worked")
    except ImportError:
        from proxy.config import proxy_config
        import tg_ws_proxy
        logging.info(f"[MTPROTO] Import via 'import' worked")

    dc_opt = {
        4: '149.154.167.91'
    }

    app_state = state.load_state()
    
    # Поддержка кастомных DC из настроек (DC->IP в UI)
    custom_dc = app_state.get("custom_dc_redirects", {})
    if custom_dc:
        dc_opt.update(custom_dc)
    if secret is None:
        secret = app_state.get("proxy_secret", "efac191ac9b83e4c0c8c4e5e7c6a6b6d")

    for attempt in range(3):
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test_sock.bind((host, port))
            test_sock.close()
            break
        except OSError as e:
            test_sock.close()
            if attempt < 2:
                time.sleep(0.5)
                continue
            proc_info = _get_process_using_port(port)
            if proc_info:
                reason = f"Port {port} already used by: {proc_info}"
                logging.error(f"[MTPROTO] {reason}")
                return False
            else:
                reason = f"Port {port} already in use: {e}"
                logging.error(f"[MTPROTO] {reason}")
                return False
    
    import asyncio
    stop_event = asyncio.Event()
    thread_error: list = [None]
    
    def _run():
        loop = None
        try:
            logging.info(f"[MTPROTO] _run before config, port={port}, host={host}")
            proxy_config.port = port
            proxy_config.host = host
            proxy_config.secret = secret
            proxy_config.dc_redirects = dc_opt
            proxy_config.fake_tls_domain = ''
            proxy_config.fallback_cfproxy = True
            proxy_config.fallback_cfproxy_priority = True
            proxy_config.cfproxy_user_domain = ''
            
            # Initialize balancer with CF proxy domains
            try:
                from src.proxy.balancer import balancer
                from src.proxy.config import CFPROXY_DEFAULT_DOMAINS
                balancer.update_domains_list(CFPROXY_DEFAULT_DOMAINS)
            except ImportError:
                from proxy.balancer import balancer
                from proxy.config import CFPROXY_DEFAULT_DOMAINS
                balancer.update_domains_list(CFPROXY_DEFAULT_DOMAINS)
            
            logging.info(f"[MTPROTO] proxy_config set: {proxy_config.port}:{proxy_config.host}")
            
            logging.info(f"[MTPROTO] Creating event loop...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logging.info(f"[MTPROTO] Event loop set, calling run...")
            
            try:
                loop.run_until_complete(tg_ws_proxy._run(stop_event))
                logging.info("[MTPROTO] run_until_complete returned")
            except Exception as e:
                logging.error(f"[MTPROTO] run_until_complete error: {e}", exc_info=True)
                raise
            finally:
                logging.info(f"[MTPROTO] Closing loop")
                loop.close()
        except Exception as e:
            thread_error[0] = str(e)
            logging.error(f"[MTPROTO] Proxy error: {e}", exc_info=True)
            import traceback
            logging.error(f"[MTPROTO] Traceback: {traceback.format_exc()}")
        finally:
            logging.info(f"[MTPROTO] _run finally")
            with _proxy_lock:
                if key in _proxies:
                    _proxies[key]['running'] = False
                    _proxies[key]['thread'] = None
            if loop and not loop.is_closed():
                try:
                    loop.close()
                except:
                    pass
    
    thread = threading.Thread(target=_run, daemon=True, name=f'MTPROTO-{port}')
    thread.start()
    logging.info(f"[MTPROTO] Thread started, waiting for server...")
    
    for _ in range(10):
        if thread_error[0]:
            reason = f"Startup error: {thread_error[0]}"
            logging.error(f"[MTPROTO] Proxy failed to start - {reason}")
            return False
        if _check_mtproto_traffic(port):
            break
        time.sleep(0.5)
    else:
        if thread_error[0]:
            reason = f"Startup error: {thread_error[0]}"
            logging.error(f"[MTPROTO] Proxy failed to start - {reason}")
            return False
        reason = "Port not listening after 5s"
        logging.error(f"[MTPROTO] Proxy failed to start - {reason}")
        return False
    
    with _proxy_lock:
        _proxies[key] = {
            'thread': thread,
            'stop_event': stop_event,
            'port': port,
            'host': host,
            'running': True
        }
    
    set_mtproto_enabled(True)
    logging.info(f"[MTPROTO] Proxy start: {host}:{port}")
    return True


def stop_mtproto_proxy(port, host='127.0.0.1'):
    global _proxies
    
    logging.info(f"[MTPROTO] stop_mtproto_proxy called: {host}:{port}")
    
    key = (host, port)
    
    proxy = None
    with _proxy_lock:
        proxy = _proxies.pop(key, None)
    
    if proxy:
        try:
            stop_evt = proxy.get('stop_event')
            thread = proxy.get('thread')
            if stop_evt:
                stop_evt.set()
            if thread:
                thread.join(timeout=3)
        except Exception as e:
            logging.error(f"[MTPROTO] Stop error: {e}")
        
        logging.info(f"[MTPROTO] Proxy {host}:{port} stopped")
    
    set_mtproto_enabled(False)
    return True


def is_mtproto_proxy_running(port=1080, host='127.0.0.1'):
    with _proxy_lock:
        key = (host, port)
        proxy = _proxies.get(key)
        
        if not proxy:
            return _check_mtproto_traffic(port)
        
        thread = proxy.get('thread')
        if not thread or not thread.is_alive():
            if proxy.get('running'):
                logging.warning(f"[MTPROTO] Proxy {host}:{port} marked as running but thread dead")
            return _check_mtproto_traffic(port)
        
        return _check_mtproto_traffic(port)


def _check_mtproto_traffic(port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect(('127.0.0.1', port))
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            sock.close()
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port:
                    if conn.status == 'ESTABLISHED' or conn.status == 'LISTENING':
                        return True
            return False
    except Exception as e:
        logging.warning(f"[MTPROTO] _check_mtproto_traffic error: {e}")
        return False


def is_mtproto_running():
    with _proxy_lock:
        return any(p.get('thread') and p['thread'].is_alive() for p in _proxies.values())


def is_winws_running():
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and proc.info['name'].lower() == 'winws.exe':
                return True
    except Exception as e:
        logging.warning(f"[winws] Check error: {e}")
    return False


def is_ipv6_disabled():
    try:
        result = subprocess.run([
            'reg', 'query',
            'HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip6\\Parameters',
            '/v', 'DisabledComponents'
        ], capture_output=True, text=True, shell=True)
        if 'DisabledComponents' in result.stdout:
            match = re.search(r'DisabledComponents\s+REG_DWORD\s+0x([0-9a-fA-F]+)', result.stdout)
            if match:
                value = int(match.group(1), 16)
                return value != 0
        return False
    except:
        return False


def disable_ipv6():
    try:
        result = subprocess.run([
            'reg', 'add',
            'HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip6\\Parameters',
            '/v', 'DisabledComponents', '/t', 'REG_DWORD',         '/d', '255', '/f'
        ], capture_output=True, shell=True)
        logging.info("[IPv6] Disabled via registry")
        return result.returncode == 0
    except Exception as e:
        logging.error(f"[IPv6] Error: {e}")
        return False


def enable_ipv6():
    try:
        result = subprocess.run([
            'reg', 'delete',
            'HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip6\\Parameters',
            '/v', 'DisabledComponents', '/f'
        ], capture_output=True, shell=True)
        logging.info("[IPv6] Enabled via registry")
        return result.returncode == 0
    except Exception as e:
        logging.error(f"[IPv6] Error: {e}")
        return False


def clear_discord_cache():
    import shutil
    msgs = []
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and proc.info['name'].lower() == 'discord.exe':
                proc.terminate()
                proc.wait(timeout=5)
                msgs.append("Discord.exe closed")
                break
    except Exception as e:
        msgs.append(f"Failed to close Discord: {e}")

    cache_dir = Path(os.environ.get('APPDATA', '')) / 'discord'
    for folder in ['Cache', 'Code Cache', 'GPUCache']:
        p = cache_dir / folder
        if p.exists():
            try:
                shutil.rmtree(p)
                msgs.append(f"Deleted {folder}")
            except Exception as e:
                msgs.append(f"Failed to delete {folder}: {e}")
        else:
            msgs.append(f"{folder} not found")
    return " | ".join(msgs)


GAME_FILTER_PATH = BASE_DIR / "zapret" / "utils" / "game_filter.enabled"
IPSET_PATH = BASE_DIR / "zapret" / "lists" / "ipset-all.txt"


def get_game_filter_mode():
    if not GAME_FILTER_PATH.exists():
        return "disabled"
    mode = GAME_FILTER_PATH.read_text(encoding="utf-8").strip().lower()
    return mode if mode in ("all", "tcp", "udp") else "disabled"


def set_game_filter_mode(mode):
    if mode == "disabled":
        try:
            GAME_FILTER_PATH.unlink()
        except FileNotFoundError:
            pass
    else:
        GAME_FILTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        GAME_FILTER_PATH.write_text(mode, encoding="utf-8")
    
    if get_game_filter_mode() != mode:
        logging.error(f"[GameFilter] Verification failed: expected {mode}, got {get_game_filter_mode()}")
        return False
    return True


def get_ipset_status():
    if not IPSET_PATH.exists():
        return "any"
    text = IPSET_PATH.read_text(encoding="utf-8").strip()
    if not text:
        return "any"
    if text == "203.0.113.113/32":
        return "none"
    return "loaded"


def set_ipset_mode(mode):
    IPSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if mode == "any":
        IPSET_PATH.write_text("", encoding="utf-8")
    elif mode == "none":
        IPSET_PATH.write_text("203.0.113.113/32", encoding="utf-8")
    elif mode == "loaded":
        backup = IPSET_PATH.with_suffix(".txt.backup")
        if backup.exists():
            IPSET_PATH.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    
    if get_ipset_status() != mode:
        logging.error(f"[IPSet] Verification failed: expected {mode}, got {get_ipset_status()}")
        return False
    return True