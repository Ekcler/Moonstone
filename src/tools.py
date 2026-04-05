import subprocess
import psutil
import socket
import threading
import time
import logging
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
EXCLUDE_LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-exclude.txt"

_saved_state = state.load_state()
AUTO_ADD_ENABLED = _saved_state.get("auto_add_enabled", False)
SOCKS5_ENABLED = _saved_state.get("socks5_enabled", False)

_failed_domains = set()
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
        from src.service import service_exists
        if not service_exists():
            return 0.0, 0.0
        
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
        domains = set(line.strip().lower() for line in content.strip().split('\n') if line.strip())
        return domains
    except:
        return set()


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
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((domain, 443))
        return True
    except:
        try:
            socket.gethostbyname(domain)
            return True
        except:
            return False


def test_failed_domain(domain):
    if is_in_general(domain):
        return None
    if not check_domain_accessible(domain):
        success, result = add_to_general(domain)
        if success:
            return domain
    return None


def start_auto_monitor(callback=None):
    global _monitor_thread, _monitor_running
    
    if _monitor_running:
        return
    
    _monitor_running = True
    
    def monitor():
        while _monitor_running:
            time.sleep(30)
            if not AUTO_ADD_ENABLED:
                continue
            
            current_dns = []
            try:
                proc = subprocess.run('ipconfig /displaydns', capture_output=True, text=True, shell=True)
                lines = proc.stdout.split('\n')
                for line in lines:
                    if 'Record Name' in line:
                        name = line.split(':')[1].strip().lower()
                        if '.' in name and not name.startswith('.'):
                            current_dns.append(name)
            except:
                pass
            
            for domain in current_dns:
                if domain not in _failed_domains:
                    result = test_failed_domain(domain)
                    if result and callback:
                        callback(result)
    
    _monitor_thread = threading.Thread(target=monitor, daemon=True)
    _monitor_thread.start()
    logging.info("[AUTO-MONITOR] Started")


def stop_auto_monitor():
    global _monitor_running
    _monitor_running = False
    logging.info("[AUTO-MONITOR] Stopped")


def set_auto_add_enabled(enabled):
    global AUTO_ADD_ENABLED
    AUTO_ADD_ENABLED = enabled
    state.save_state(auto_add_enabled=enabled)
    logging.info(f"[AUTO-MONITOR] Enabled: {enabled}")


def set_socks5_enabled(enabled):
    global SOCKS5_ENABLED
    SOCKS5_ENABLED = enabled
    state.save_state(socks5_enabled=enabled)
    logging.info(f"[SOCKS5] Enabled: {enabled}")


if AUTO_ADD_ENABLED:
    def _delayed_start():
        time.sleep(2)
        start_auto_monitor()
    threading.Thread(target=_delayed_start, daemon=True).start()
