import subprocess
import psutil
from pathlib import Path
from ping3 import ping

try:
    from .config import BASE_DIR, ENCODING
except ImportError:
    from src.config import BASE_DIR, ENCODING

_last_io = None
LIST_PATH = BASE_DIR / "zapret" / "lists" / "list-general.txt"

def get_ping(host):
    """Проверка задержки."""
    try:
        p = ping(host, unit='ms')
        return round(p, 2) if p else "Timeout"
    except: return "Error"

def run_tracert(host):
    """Трассировка маршрута."""
    subprocess.Popen(['cmd', '/c', f'tracert {host} & pause'], creationflags=subprocess.CREATE_NEW_CONSOLE)

def get_traffic_stats():
    """Считает скорость сети (КБ/с)."""
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
        return max(0.0, round(up, 1)), max(0.0, round(down, 1))
    except: return 0.0, 0.0

# --- РАБОТА СО СПИСКОМ ---
def read_blocklist():
    """Читает list-general.txt."""
    try:
        if not LIST_PATH.exists(): return ""
        return LIST_PATH.read_text(encoding=ENCODING)
    except: return ""

def save_blocklist(text):
    """Сохраняет list-general.txt."""
    try:
        LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIST_PATH.write_text(text.strip(), encoding=ENCODING)
        return True
    except: return False

# --- DNS LOGIC ---
def find_best_dns():
    dns_list = {"Cloudflare": "1.1.1.1", "Google": "8.8.8.8", "Yandex": "77.88.8.8", "Quad9": "9.9.9.9"}
    results = {}
    for name, ip in dns_list.items():
        p = get_ping(ip)
        if isinstance(p, (float, int)): results[name] = (ip, p)
    if not results: return None, "All DNS timed out"
    best_name = min(results, key=lambda k: results[k][1])
    return results[best_name][0], f"{best_name} [{results[best_name][0]}] ({results[best_name][1]}ms)"

def get_active_interface():
    try:
        for name, stats in psutil.net_if_stats().items():
            if stats.isup and not name.startswith("Loopback"):
                addrs = psutil.net_if_addrs().get(name, [])
                if any(a.family == 2 and not a.address.startswith("127.") for a in addrs): return name
    except: pass
    return None

def set_system_dns(dns_ip):
    iface = get_active_interface()
    if not iface: return False, "Interface not found"
    try:
        subprocess.run(f'netsh interface ip set dns name="{iface}" source=static address={dns_ip}', shell=True, capture_output=True)
        return True, iface
    except Exception as e: return False, str(e)

def reset_system_dns():
    iface = get_active_interface()
    if not iface: return False, "Interface not found"
    try:
        subprocess.run(f'netsh interface ip set dns name="{iface}" source=dhcp', shell=True, capture_output=True)
        return True, iface
    except Exception as e: return False, str(e)
