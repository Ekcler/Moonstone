import threading
import time
import logging
import subprocess
import json
import psutil
from pathlib import Path

try:
    from .config import BASE_DIR
except ImportError:
    from src.config import BASE_DIR

RL_UDP_PORTS = set(range(7000, 9001)) | set(range(5000, 5501)) | set(range(19294, 19345)) | set(range(50000, 50101))
BANNED_FILE = BASE_DIR / "rl_watchdog.json"
BLOCK_THRESHOLD = 5
CHECK_DELAY = 5
SCAN_INTERVAL = 3


class RLWatchdog:
    def __init__(self):
        self._running = False
        self._thread = None
        self._pending = {}
        self._failed = {}
        self._banned = set()
        self._load_banned()

    def _subnet_of(self, ip):
        parts = ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

    def _is_banned(self, ip):
        return self._subnet_of(ip) in self._banned

    def _rule_name(self, subnet):
        return f"RL-Blacklist-{subnet.replace('/', '_')}"

    def _load_banned(self):
        try:
            if BANNED_FILE.exists():
                with open(BANNED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._banned = set(data.get("banned", []))
                if self._banned:
                    logging.info(f"[RL] Loaded {len(self._banned)} banned subnets: {sorted(self._banned)}")
        except Exception as e:
            logging.warning(f"[RL] Failed to load {BANNED_FILE}: {e}")
            self._banned = set()

    def _save_banned(self):
        try:
            data = {"banned": sorted(self._banned)}
            with open(BANNED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"[RL] Failed to save {BANNED_FILE}: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name='RL-Watchdog')
        self._thread.start()
        logging.info("[RL] Watchdog started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logging.info("[RL] Watchdog stopped")

    def _run(self):
        while self._running:
            try:
                self._scan()
            except Exception as e:
                logging.error(f"[RL] Scan error: {e}")
            time.sleep(SCAN_INTERVAL)

    def _scan(self):
        now = time.time()
        for conn in psutil.net_connections(kind='udp4'):
            if not conn.raddr:
                continue
            ip, port = conn.raddr
            if port in RL_UDP_PORTS and not self._is_banned(ip) and ip not in self._pending:
                self._pending[ip] = now
                threading.Thread(target=self._check_ip, args=(ip,), daemon=True).start()

    def _check_ip(self, ip):
        if self._is_banned(ip):
            return

        time.sleep(CHECK_DELAY)

        if not self._running:
            return

        if self._is_banned(ip):
            return

        after_count = sum(
            1 for c in psutil.net_connections(kind='udp4')
            if c.raddr and c.raddr[0] == ip
        )

        self._pending.pop(ip, None)

        if after_count > 0:
            self._failed.pop(ip, None)
        else:
            self._failed[ip] = self._failed.get(ip, 0) + 1
            count = self._failed[ip]
            logging.warning(f"[RL] Server {ip} dead (connections={after_count}, fail #{count})")
            if count >= BLOCK_THRESHOLD:
                self._block_ip(ip)

    def _block_ip(self, ip):
        subnet = self._subnet_of(ip)
        if subnet in self._banned:
            return
        rule_name = self._rule_name(subnet)
        try:
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name={rule_name}',
                 f'remoteip={subnet}',
                 'dir=out', 'action=block', 'protocol=any'],
                capture_output=True, check=True, timeout=10
            )
            self._banned.add(subnet)
            self._save_banned()
            logging.warning(f"[RL] Blocked subnet: {subnet} (from {ip})")
        except subprocess.TimeoutExpired:
            logging.error(f"[RL] Timeout blocking {subnet}")
        except subprocess.CalledProcessError as e:
            logging.error(f"[RL] Failed to block {subnet}: {e.stderr.decode() if e.stderr else e}")

    def unblock_ip(self, ip):
        subnet = self._subnet_of(ip)
        return self.unblock_subnet(subnet)

    def unblock_subnet(self, subnet):
        if subnet not in self._banned:
            logging.info(f"[RL] Subnet {subnet} not banned")
            return False
        rule_name = self._rule_name(subnet)
        try:
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                 f'name={rule_name}'],
                capture_output=True, check=True, timeout=10
            )
            self._banned.discard(subnet)
            self._save_banned()
            logging.info(f"[RL] Unblocked subnet: {subnet}")
            return True
        except subprocess.TimeoutExpired:
            logging.error(f"[RL] Timeout unblocking {subnet}")
        except subprocess.CalledProcessError:
            pass
        return False

    def get_banned(self):
        return sorted(self._banned)

    def is_running(self):
        return self._running and self._thread and self._thread.is_alive()


rl_watchdog = RLWatchdog()
