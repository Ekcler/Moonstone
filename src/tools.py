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
import sqlite3
from pathlib import Path
from ping3 import ping

try:
    from .config import BASE_DIR, ENCODING
    from . import state
except ImportError:
    from src.config import BASE_DIR, ENCODING
    from src import state

_QUARANTINE_CHECK_TIMES = {}
_QUARANTINE_CHECK_TIMEOUT = 1800

_last_io = None
LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-general.txt"
EXCLUDE_LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-exclude.txt"
QUARANTINE_LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-quarantine.txt"
MONITOR_INTERVAL = 60
_AUTO_ADD_INTERVAL = 60

_saved_state = state.load_state()
AUTO_ADD_ENABLED = _saved_state.get("auto_add_enabled", False)
MTPROTO_ENABLED = _saved_state.get("socks5_enabled", False)


def is_auto_add_enabled():
    return state.load_state().get("auto_add_enabled", False)


def is_socks5_enabled():
    return state.load_state().get("socks5_enabled", False)


_proxies = {}
_proxy_lock = threading.Lock()

_failed_domains = set()
_failed_domains_max = 1000
_monitor_thread = None
_monitor_running = False


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
        subprocess.run(f'netsh interface ip set dns name="{iface}" source=static address={dns_ip}', shell=True, capture_output=True)
        return True, iface
    except Exception as e:
        return False, str(e)


def reset_system_dns():
    iface = get_active_interface()
    if not iface:
        return False, "Interface not found"
    try:
        subprocess.run(f'netsh interface ip set dns name="{iface}" source=dhcp', shell=True, capture_output=True)
        return True, iface
    except Exception as e:
        return False, str(e)


def read_general_list():
    try:
        if not LIST_PATH.exists():
            return set()
        content = LIST_PATH.read_text(encoding=ENCODING)
        domains = set(line.strip().lower() for line in content.strip().split('\n') if line.strip() and not line.startswith('#'))
        return domains
    except:
        return set()


def read_quarantine_list():
    try:
        if not QUARANTINE_LIST_PATH.exists():
            return {}
        result = {}
        content = QUARANTINE_LIST_PATH.read_text(encoding=ENCODING)
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.lower().split()
            if len(parts) >= 1:
                domain = parts[0]
                timestamp = parts[1] if len(parts) > 1 else "0"
                result[domain] = timestamp
        return result
    except:
        return {}


def add_to_quarantine(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    try:
        current = read_quarantine_list()
        if domain in current:
            return False
        timestamp = str(int(time.time()))
        current[domain] = timestamp
        lines = [f"{d} {t}" for d, t in sorted(current.items())]
        QUARANTINE_LIST_PATH.write_text('\n'.join(lines) + '\n', encoding=ENCODING)
        logging.info(f"[QUARANTINE] {domain} added to quarantine")
        return True
    except Exception as e:
        logging.error(f"[QUARANTINE] Error: {e}")
        return False


def is_in_quarantine(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    return domain in read_quarantine_list()


def move_from_quarantine_to_general(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    try:
        qlist = read_quarantine_list()
        if domain in qlist:
            del qlist[domain]
            QUARANTINE_LIST_PATH.write_text('\n'.join([f"{d} {t}" for d, t in sorted(qlist.items())]) + '\n', encoding=ENCODING)
        success, _ = add_to_general(domain)
        return success
    except Exception as e:
        logging.error(f"[MOVE] Error: {e}")
        return False


def is_whitelisted(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    try:
        if EXCLUDE_LIST_PATH.exists():
            content = EXCLUDE_LIST_PATH.read_text(encoding=ENCODING)
            for line in content.strip().split('\n'):
                line = line.strip().lower()
                if line and not line.startswith('#'):
                    if line == domain or domain.endswith('.' + line):
                        return True
    except:
        pass
    return False


def get_blocked_stats():
    qlist = read_quarantine_list()
    current_time = int(time.time())
    days = {1: 0, 7: 0, 30: 0, 90: 0, 9999: 0}
    for domain, timestamp in qlist.items():
        try:
            age = (current_time - int(timestamp)) // 86400
            if age < 1:
                days[1] += 1
            if age < 7:
                days[7] += 1
            if age < 30:
                days[30] += 1
            if age < 90:
                days[90] += 1
            days[9999] += 1
        except:
            pass
    return {"1d": days[1], "7d": days[7], "30d": days[30], "90d": days[90], "total": days[9999]}


def add_to_general(domain):
    try:
        domain = domain.lower().strip()
        domain = domain.replace("https://", "").replace("http://", "").split('/')[0]
        current = read_general_list()
        if domain in current:
            return False, "Already in list"
        current.add(domain)
        LIST_PATH.write_text('\n'.join(sorted(current)) + '\n', encoding=ENCODING)
        logging.info(f"[AUTO-ADD] Added {domain} to general list")
        return True, domain
    except Exception as e:
        logging.error(f"[AUTO-ADD] Error: {e}")
        return False, str(e)


def is_in_general(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    return domain in read_general_list()


def check_domain_accessible(domain):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((domain, 443))
        sock.close()
        return True
    except:
        try:
            socket.gethostbyname(domain)
            return True
        except:
            return False


def test_failed_domain(domain):
    global _failed_domains, _QUARANTINE_CHECK_TIMES
    current_time = time.time()
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    
    if is_in_general(domain) or is_whitelisted(domain):
        return None
    
    if is_in_quarantine(domain):
        last_check = _QUARANTINE_CHECK_TIMES.get(domain, 0)
        if current_time - last_check < _QUARANTINE_CHECK_TIMEOUT:
            return None
        
        if check_domain_accessible(domain):
            move_from_quarantine_to_general(domain)
            _QUARANTINE_CHECK_TIMES[domain] = current_time
            return {"action": "to_general", "domain": domain}
        else:
            _QUARANTINE_CHECK_TIMES[domain] = current_time
            return None
    
    _QUARANTINE_CHECK_TIMES[domain] = current_time
    
    if not check_domain_accessible(domain):
        _failed_domains.add(domain)
        if len(_failed_domains) > _failed_domains_max:
            overflow = len(_failed_domains) - _failed_domains_max
            for _ in range(overflow):
                if _failed_domains:
                    _failed_domains.pop()
        if add_to_quarantine(domain):
            return {"action": "to_quarantine", "domain": domain}
    else:
        _failed_domains.discard(domain)
    return None


def cleanup_old_quarantine(days=30):
    current_time = int(time.time())
    days_in_seconds = days * 86400
    try:
        qlist = read_quarantine_list()
        to_remove = []
        to_keep = {}
        for domain, timestamp in qlist.items():
            try:
                ts = int(timestamp)
                if current_time - ts >= days_in_seconds:
                    to_remove.append(domain)
                else:
                    to_keep[domain] = timestamp
            except:
                to_keep[domain] = timestamp
        QUARANTINE_LIST_PATH.write_text('\n'.join([f"{d} {t}" for d, t in sorted(to_keep.items())]) + '\n', encoding=ENCODING)
        logging.info(f"[QUARANTINE] Cleaned {len(to_remove)} old domains")
        return to_remove
    except Exception as e:
        logging.error(f"[QUARANTINE] Cleanup error: {e}")
        return []


def recheck_quarantine_domain(domain):
    domain = domain.lower().strip().replace("https://", "").replace("http://", "").split('/')[0]
    current = read_quarantine_list()
    if domain in current:
        if check_domain_accessible(domain):
            move_from_quarantine_to_general(domain)
            return True
    return False


def _get_dns_cache_all_browsers():
    """Get DNS cache from all browsers (Chrome, Edge, Firefox, Yandex)."""
    domains = set()
    
    # 1. Windows DNS cache (Chrome, Edge)
    try:
        proc = subprocess.run('ipconfig /displaydns', capture_output=True, text=True, shell=True)
        for line in proc.stdout.split('\n'):
            if 'Record Name' in line:
                name = line.split(':')[1].strip().lower()
                if '.' in name and not name.startswith('.'):
                    domains.add(name)
    except:
        pass
    
    # 2. Firefox DNS cache
    ff_profiles = []
    ff_base = Path(os.environ.get('APPDATA', '')) / 'Mozilla' / 'Firefox' / 'Profiles'
    if ff_base.exists():
        for profile in ff_base.iterdir():
            if profile.is_dir() and ('.default-release' in profile.name or '.default' in profile.name):
                ff_profiles.append(profile)
    
    for profile in ff_profiles:
        cache_db = profile / 'cache2.sqlite'
        if cache_db.exists():
            try:
                conn = sqlite3.connect(str(cache_db))
                cursor = conn.cursor()
                cursor.execute("SELECT hostname FROM cache_entry WHERE hostname LIKE '%.%'")
                for row in cursor.fetchall():
                    hostname = row[0].lower()
                    if hostname and '.' in hostname:
                        domains.add(hostname)
                conn.close()
            except:
                pass
        
        host_db = profile / 'cache2' / 'entries'
        if host_db.exists() and host_db.is_dir():
            try:
                for f in host_db.glob('*'):
                    if f.is_file():
                        name = f.name.lower()
                        if '.' in name:
                            domains.add(name)
            except:
                pass
    
    # 3. Yandex Browser
    yandex_base = Path(os.environ.get('LOCALAPPDATA', '')) / 'Yandex' / 'YandexBrowser' / 'User Data' / 'Default'
    if yandex_base.exists():
        # Network cache
        yandex_cache = yandex_base / 'Cache' / 'Cache' / '0'
        if yandex_cache.exists():
            try:
                for f in yandex_cache.glob('*'):
                    if f.is_file() and f.stat().st_size > 0:
                        pass
            except:
                pass
    
    return list(domains)


def start_auto_monitor(callback=None):
    global _monitor_thread, _monitor_running, _AUTO_ADD_INTERVAL
    
    if _monitor_running:
        return
    
    app_state = state.load_state()
    _AUTO_ADD_INTERVAL = app_state.get("auto_add_interval", 60)
    
    _monitor_running = True
    
    def monitor():
        global _AUTO_ADD_INTERVAL
        while _monitor_running:
            current_interval = _AUTO_ADD_INTERVAL
            time.sleep(current_interval)
            if not is_auto_add_enabled():
                continue
            
            current_dns = _get_dns_cache_all_browsers()
            
            results = []
            max_check = 10
            checked = 0
            
            for domain in current_dns:
                if checked >= max_check:
                    break
                if domain not in _failed_domains:
                    result = test_failed_domain(domain)
                    if result:
                        results.append(result)
                    checked += 1
            
            if results and callback:
                callback(results)
    
    _monitor_thread = threading.Thread(target=monitor, daemon=True)
    _monitor_thread.start()
    logging.info(f"[AUTO-MONITOR] Started (interval: {_AUTO_ADD_INTERVAL}s)")


def stop_auto_monitor():
    global _monitor_running
    _monitor_running = False
    logging.info("[AUTO-MONITOR] Stopped")


def set_auto_add_enabled(enabled):
    global AUTO_ADD_ENABLED
    AUTO_ADD_ENABLED = enabled
    state.save_state(auto_add_enabled=enabled)
    logging.info(f"[AUTO-MONITOR] Enabled: {enabled}")


def set_monitor_interval(seconds):
    global _AUTO_ADD_INTERVAL
    try:
        seconds = int(seconds)
        if seconds < 10:
            seconds = 10
        _AUTO_ADD_INTERVAL = seconds
        state.save_state(auto_add_interval=seconds)
        logging.info(f"[AUTO-MONITOR] Interval set to {seconds}s")
        return True
    except (ValueError, TypeError):
        return False


def get_monitor_interval():
    return _AUTO_ADD_INTERVAL


def set_socks5_enabled(enabled):
    global MTPROTO_ENABLED
    MTPROTO_ENABLED = enabled
    state.save_state(socks5_enabled=enabled)
    logging.info(f"[MTPROTO] Enabled: {enabled}")


def get_socks5_enabled():
    return MTPROTO_ENABLED


def get_auto_add_enabled():
    return AUTO_ADD_ENABLED


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


def start_socks5_proxy(port=1080, host='127.0.0.1', secret=None):
    global _proxies
    
    key = (host, port)
    
    with _proxy_lock:
        if key in _proxies and _proxies[key]['thread'] and _proxies[key]['thread'].is_alive():
            if _check_proxy_traffic(port):
                logging.info(f"[MTPROTO] Proxy {host}:{port} already running")
                return True
            else:
                logging.info(f"[MTPROTO] Proxy {host}:{port} thread dead but key exists, cleaning up")
                try:
                    del _proxies[key]
                except:
                    pass

    logging.debug(f"[MTPROTO] Proxy {host}:{port} starting...")

    run_error = None
    
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
                return False, reason
            else:
                reason = f"Port {port} already in use: {e}"
                logging.error(f"[MTPROTO] {reason}")
                return False, reason
    
    import asyncio
    stop_event = asyncio.Event()
    thread_error = [None]
    
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
                run_error = str(e)
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
    
    time.sleep(0.5)
    
    if thread_error[0]:
        reason = f"Startup error: {thread_error[0]}"
        logging.error(f"[MTPROTO] Proxy failed to start - {reason}")
        return False, reason
    
    with _proxy_lock:
        _proxies[key] = {
            'thread': thread,
            'stop_event': stop_event,
            'port': port,
            'host': host,
            'running': True
        }
    
    if _check_proxy_traffic(port):
        set_socks5_enabled(True)
        logging.info(f"[MTPROTO] Proxy start: {host}:{port}")
        return True, None
    else:
        reason = "Port not listening or no traffic received"
        logging.error(f"[MTPROTO] Proxy failed to start - {reason}")
        return False, reason


def stop_socks5_proxy(port, host='127.0.0.1'):
    global _proxies
    
    logging.info(f"[DEBUG] stop_socks5_proxy called: {host}:{port}")
    
    key = (host, port)
    
    with _proxy_lock:
        proxy = _proxies.get(key)
        
        logging.info(f"[DEBUG] stop_socks5_proxy: proxy={proxy}")
        
        if proxy:
            try:
                stop_evt = proxy.get('stop_event')
                logging.info(f"[DEBUG] stop_socks5_proxy: stop_event={stop_evt}")
                if stop_evt:
                    stop_evt.set()
                    logging.info(f"[DEBUG] stop_event.set() called")
                thread = proxy.get('thread')
                if thread:
                    logging.info(f"[DEBUG] join thread, alive={thread.is_alive()}")
                    thread.join(timeout=3)
                    logging.info(f"[DEBUG] thread joined")
            except Exception as e:
                logging.error(f"[MTPROTO] Stop error: {e}")
            
            try:
                del _proxies[key]
            except:
                pass
            
            logging.info(f"[MTPROTO] Proxy {host}:{port} stopped")
        
        set_socks5_enabled(False)
        return True


def is_proxy_running(port=1080, host='127.0.0.1'):
    with _proxy_lock:
        key = (host, port)
        proxy = _proxies.get(key)
        
        if not proxy:
            return _check_proxy_traffic(port)
        
        thread = proxy.get('thread')
        if not thread or not thread.is_alive():
            if proxy.get('running'):
                logging.warning(f"[MTPROTO] Proxy {host}:{port} marked as running but thread dead")
            return _check_proxy_traffic(port)
        
        return _check_proxy_traffic(port)


def _force_kill_port(port):
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port:
                if conn.status == 'LISTENING' and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        proc.terminate()
                        proc.wait(timeout=3)
                        logging.info(f"[MTPROTO] Killed PID {conn.pid}")
                        return True
                    except:
                        pass
    except Exception as e:
        logging.warning(f"[MTPROTO] Force kill error: {e}")
    return False


def get_active_proxies():
    return []


def start_all_proxies():
    pass


def stop_all_proxies():
    with _proxy_lock:
        for key in list(_proxies.keys()):
            try:
                _proxies[key]['stop_event'].set()
                _proxies[key]['running'] = False
            except Exception as e:
                logging.error(f"[MTPROTO] Error stopping {key}: {e}")
        _proxies.clear()
    set_socks5_enabled(False)


def _stop_all_proxies():
    stop_all_proxies()


def _check_proxy_traffic(port):
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
        logging.warning(f"[MTPROTO] _check_proxy_traffic error: {e}")
        return False


def is_any_proxy_running():
    with _proxy_lock:
        return any(p.get('thread') and p['thread'].is_alive() for p in _proxies.values())


def init(callback=None):
    if is_auto_add_enabled():
        start_auto_monitor(callback=callback)


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
            '/v', 'DisabledComponents', '/t', 'REG_DWORD', '/d', '4294967295', '/f'
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