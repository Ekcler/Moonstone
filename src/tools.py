import subprocess
import psutil
import socket
import threading
import time
import logging
import asyncio
import signal
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


def is_auto_add_enabled():
    """Read current auto_add_enabled from state (not cached global)."""
    return state.load_state().get("auto_add_enabled", False)


def is_socks5_enabled():
    """Read current socks5_enabled from state (not cached global)."""
    return state.load_state().get("socks5_enabled", False)


def is_auto_switch_enabled():
    """Read current auto_switch_enabled from state."""
    return state.load_state().get("auto_switch_enabled", False)

_proxies = {}
_proxy_lock = threading.Lock()
_start_lock = threading.Lock()
_stop_events = {}  # Global store for stop events by (host, port)

_auto_switch_enabled = False
_auto_switch_running = False
_auto_switch_timeout = 5
_auto_switch_thread = None
_auto_switch_stop = threading.Event()
_current_proxy_index = 0
_last_data_time = {}

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
    global _failed_domains
    if is_in_general(domain):
        return None
    if not check_domain_accessible(domain):
        _failed_domains.add(domain)
        if len(_failed_domains) > _failed_domains_max:
            overflow = len(_failed_domains) - _failed_domains_max
            for _ in range(overflow):
                if _failed_domains:
                    _failed_domains.pop()
        success, result = add_to_general(domain)
        if success:
            return domain
    else:
        _failed_domains.discard(domain)
    return None


def start_auto_monitor(callback=None):
    global _monitor_thread, _monitor_running
    
    if _monitor_running:
        return
    
    _monitor_running = True
    
    def monitor():
        while _monitor_running:
            time.sleep(30)
            if not is_auto_add_enabled():
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


def get_socks5_enabled():
    """Get current SOCKS5 enabled state from runtime, not cached global."""
    return SOCKS5_ENABLED


def get_auto_add_enabled():
    """Get current auto-add enabled state from runtime."""
    return AUTO_ADD_ENABLED


def set_proxies_config(proxies):
    state.save_state(proxies=proxies)
    logging.info(f"[PROXIES] Config saved: {proxies}")


def set_auto_switch_config(enabled, timeout=None):
    global _auto_switch_enabled, _auto_switch_timeout
    if timeout is not None:
        _auto_switch_timeout = timeout
    _auto_switch_enabled = enabled
    state.save_state(auto_switch_enabled=enabled, auto_switch_timeout=timeout or _auto_switch_timeout)
    logging.info(f"[AUTO-SWITCH] Config: enabled={enabled}, timeout={_auto_switch_timeout}s")


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
    
    with _start_lock:
        key = (host, port)
        
        with _proxy_lock:
            if key in _proxies and _proxies[key]['thread'] and _proxies[key]['thread'].is_alive():
                if _check_proxy_traffic(port):
                    logging.info(f"[SOCKS5] Proxy {host}:{port} already running")
                    return True
                else:
                    logging.info(f"[SOCKS5] Proxy {host}:{port} thread dead but key exists, cleaning up")
                    try:
                        del _proxies[key]
                    except:
                        pass

        logging.debug(f"[SOCKS5] Proxy {host}:{port} starting...")

        try:
            from src.proxy.config import proxy_config
            from src import tg_ws_proxy
            logging.info(f"[SOCKS5] Import via 'from src' worked")
        except ImportError:
            from proxy.config import proxy_config
            import tg_ws_proxy
            logging.info(f"[SOCKS5] Import via 'import' worked")

        dc_opt = {
            1: '149.154.175.50', 2: '149.154.167.220',
            3: '149.154.175.100', 4: '149.154.167.220',
            5: '91.108.56.100'
        }

        app_state = state.load_state()
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
                    logging.error(f"[SOCKS5] Port {port} already used by: {proc_info}")
                else:
                    logging.error(f"[SOCKS5] Port {port} already in use: {e}")
                return False
        
        import asyncio
        stop_event = asyncio.Event()
        
        def _run():
            loop = None
            try:
                logging.info(f"[SOCKS5] _run before config, port={port}, host={host}")
                proxy_config.port = port
                proxy_config.host = host
                proxy_config.secret = secret
                proxy_config.dc_redirects = dc_opt
                proxy_config.fake_tls_domain = ''
                proxy_config.fallback_cfproxy = True
                logging.info(f"[SOCKS5] proxy_config set: {proxy_config.port}:{proxy_config.host}")
                
                logging.info(f"[SOCKS5] Creating event loop...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logging.info(f"[SOCKS5] Event loop set, calling run...")
                
                try:
                    loop.run_until_complete(tg_ws_proxy._run(stop_event))
                    logging.info("[SOCKS5] run_until_complete returned")
                except Exception as e:
                    logging.error(f"[SOCKS5] run_until_complete error: {e}", exc_info=True)
                    raise
                finally:
                    logging.info(f"[SOCKS5] Closing loop")
                    loop.close()
            except Exception as e:
                logging.error(f"[SOCKS5] Proxy error: {e}", exc_info=True)
                import traceback
                logging.error(f"[SOCKS5] Traceback: {traceback.format_exc()}")
            finally:
                logging.info(f"[SOCKS5] _run finally")
                with _proxy_lock:
                    if key in _proxies:
                        _proxies[key]['running'] = False
                        _proxies[key]['thread'] = None
                if loop and not loop.is_closed():
                    try:
                        loop.close()
                    except:
                        pass
        
        thread = threading.Thread(target=_run, daemon=True, name=f'SOCKS5-{port}')
        thread.start()
        logging.info(f"[SOCKS5] Thread started, waiting for server...")
        
        time.sleep(0.5)  # Wait for server to start
        
        with _proxy_lock:
            _proxies[key] = {
                'thread': thread,
                'stop_event': stop_event,
                'port': port,
                'host': host,
                'running': True
            }
            _stop_events[key] = stop_event  # Also save globally
        
        if _check_proxy_traffic(port):
            set_socks5_enabled(True)
            logging.info(f"[SOCKS5] Proxy started on {host}:{port}")
            return True
        else:
            logging.error(f"[SOCKS5] Proxy failed to start - port not listening")
            return False


def stop_socks5_proxy(port, host='127.0.0.1'):
    global _proxies
    
    logging.info(f"[DEBUG] stop_socks5_proxy called: {host}:{port}")
    
    key = (host, port)
    
    # Check running state BEFORE stopping
    all_running_before = False
    with _proxy_lock:
        all_running_before = any(
            p.get('thread') and p['thread'].is_alive() and _check_proxy_traffic(p.get('port', 0))
            for p in _proxies.values()
            if (p.get('host'), p.get('port')) != key
        )
    
    with _start_lock:
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
                    logging.error(f"[SOCKS5] Stop error: {e}")
                
                try:
                    del _proxies[key]
                except:
                    pass
                
                try:
                    del _stop_events[key]
                except:
                    pass
                
                logging.info(f"[SOCKS5] Proxy {host}:{port} stopped")
            else:
                # Try global stop events
                stop_evt = _stop_events.get(key)
                if stop_evt:
                    logging.info(f"[DEBUG] Using global stop_event")
                    stop_evt.set()
                    try:
                        del _stop_events[key]
                    except:
                        pass
                else:
                    logging.info(f"[DEBUG] No proxy record, checking port for orphan")
        
        # Check if ANY proxy is still running after this stop
        all_running_after = False
        with _proxy_lock:
            if _proxies:
                all_running_after = any(
                    p.get('thread') and p['thread'].is_alive() and _check_proxy_traffic(p.get('port', 0))
                    for p in _proxies.values()
                )
        
        # Only set socks5_enabled to False if no proxies are running at all
        if not all_running_after:
            set_socks5_enabled(False)
        
        return True


def is_proxy_running(port=1080, host='127.0.0.1'):
    with _proxy_lock:
        key = (host, port)
        proxy = _proxies.get(key)
        
        if not proxy:
            # No record in our dict - check if port is in use
            return _check_proxy_traffic(port)
        
        thread = proxy.get('thread')
        if not thread or not thread.is_alive():
            if proxy.get('running'):
                logging.warning(f"[SOCKS5] Proxy {host}:{port} marked as running but thread dead")
            return _check_proxy_traffic(port)
        
        return _check_proxy_traffic(port)


def _force_kill_port(port):
    """Force kill process using port."""
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port:
                if conn.status == 'LISTENING' and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        proc.terminate()
                        proc.wait(timeout=3)
                        logging.info(f"[SOCKS5] Killed PID {conn.pid}")
                        return True
                    except:
                        pass
    except Exception as e:
        logging.warning(f"[SOCKS5] Force kill error: {e}")
    return False


def get_active_proxies():
    """Return list of enabled proxies from config."""
    saved_state = state.load_state()
    proxies = saved_state.get("proxies", state.DEFAULT_PROXIES)
    return [p for p in proxies if p.get("enabled", True)]


def start_all_proxies():
    """Start all enabled proxies."""
    for proxy in get_active_proxies():
        start_socks5_proxy(port=proxy['port'], host=proxy['host'])


def stop_all_proxies():
    """Stop all running proxies."""
    with _proxy_lock:
        for key in list(_proxies.keys()):
            try:
                _proxies[key]['stop_event'].set()
                _proxies[key]['running'] = False
            except Exception as e:
                logging.error(f"[SOCKS5] Ошибка остановки {key}: {e}")
        _proxies.clear()
    set_socks5_enabled(False)


def _stop_all_proxies():
    """Stop all proxies (legacy compatibility)."""
    stop_all_proxies()


def _check_proxy_traffic(port):
    """Check if proxy has active connections or is listening."""
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
        logging.warning(f"[SOCKS5] _check_proxy_traffic error: {e}")
        return False


def start_auto_switch(callback=None):
    """Start auto-switch monitoring worker."""
    global _auto_switch_running, _auto_switch_thread, _current_proxy_index, _last_data_time
    
    if _auto_switch_running:
        return
    
    if not is_auto_switch_enabled():
        logging.warning("[AUTO-SWITCH] Not enabled in state, skipping start")
        return
    
    _auto_switch_running = True
    _current_proxy_index = 0
    _last_data_time = {}
    
    for p in get_active_proxies():
        _last_data_time[(p['host'], p['port'])] = time.time()
    
    def monitor():
        global _current_proxy_index, _last_data_time
        
        while _auto_switch_running:
            time.sleep(1)
            
            if not is_auto_switch_enabled():
                continue
            
            proxies = get_active_proxies()
            if len(proxies) < 2:
                continue
            
            current_proxy = proxies[_current_proxy_index]
            key = (current_proxy['host'], current_proxy['port'])
            
            has_traffic = _check_proxy_traffic(current_proxy['port'])
            
            if has_traffic:
                _last_data_time[key] = time.time()
                continue
            
            last_time = _last_data_time.get(key)
            if last_time is None:
                _last_data_time[key] = time.time()
                continue
            
            elapsed = time.time() - last_time
            
            if elapsed > _auto_switch_timeout:
                old_proxy = current_proxy
                _current_proxy_index = (_current_proxy_index + 1) % len(proxies)
                next_proxy = proxies[_current_proxy_index]
                
                logging.info(f"[AUTO-SWITCH] Timeout ({elapsed:.1f}s) on {old_proxy['host']}:{old_proxy['port']}, switching to {next_proxy['host']}:{next_proxy['port']}...")
                
                if is_proxy_running(port=old_proxy['port'], host=old_proxy['host']):
                    stop_socks5_proxy(port=old_proxy['port'], host=old_proxy['host'])
                    time.sleep(1)
                
                start_socks5_proxy(port=next_proxy['port'], host=next_proxy['host'])
                time.sleep(0.5)
                
                _last_data_time[(next_proxy['host'], next_proxy['port'])] = time.time()
                
                if callback:
                    callback(_current_proxy_index, next_proxy)
    
    _auto_switch_thread = threading.Thread(target=monitor, daemon=True)
    _auto_switch_thread.start()
    logging.info("[AUTO-SWITCH] Started")


def stop_auto_switch():
    """Stop auto-switch monitoring."""
    global _auto_switch_running
    _auto_switch_running = False
    logging.info("[AUTO-SWITCH] Stopped")


def get_auto_switch_status():
    """Get current auto-switch status."""
    return _auto_switch_running, _auto_switch_timeout


def is_any_proxy_running():
    """Check if any proxy is running."""
    with _proxy_lock:
        return any(p.get('thread') and p['thread'].is_alive() for p in _proxies.values())


def init():
    """Initialize background services. Call explicitly after app start."""
    if is_auto_add_enabled():
        start_auto_monitor()


class ProxyBalancer:
    """TCP Round-Robin Balancer - forwards connections to backends."""
    
    def __init__(self, listen_port=1080, backends=None):
        self.listen_port = listen_port
        self.backends = backends or [1081, 1082, 1083]
        self.current_backend = 0
        self._running = False
        self._server = None
        self._loop = None
        self._thread = None
    
    def _get_next_backend(self):
        """Round-Robin: returns next backend port."""
        if not self.backends:
            return 1081
        port = self.backends[self.current_backend % len(self.backends)]
        self.current_backend += 1
        return port
    
    async def _handle_client(self, reader, writer):
        """Handle incoming client connection - forward to backend."""
        backend_port = self._get_next_backend()
        
        try:
            backend_reader, backend_writer = await asyncio.open_connection(
                '127.0.0.1', backend_port
            )
            
            async def forward(src, dst):
                try:
                    while True:
                        data = await src.read(4096)
                        if not data:
                            break
                        dst.write(data)
                        await dst.drain()
                except:
                    pass
                finally:
                    try:
                        dst.close()
                    except:
                        pass
            
            try:
                await asyncio.gather(
                    forward(reader, backend_writer),
                    forward(backend_reader, writer),
                )
            except Exception:
                pass
        except Exception as e:
            logging.debug(f"[BALANCER] Backend {backend_port} error: {e}")
        finally:
            try:
                writer.close()
            except:
                pass
    
    async def _run_server(self):
        """Run the balancer server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            '127.0.0.1',
            self.listen_port
        )
        logging.info(f"[BALANCER] Started on 127.0.0.1:{self.listen_port} -> backends {self.backends}")
        
        async with self._server:
            await self._server.serve_forever()
    
    def start(self):
        """Start balancer in a new thread."""
        if self._running:
            return
        
        self._running = True
        
        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run_server())
            except Exception as e:
                logging.error(f"[BALANCER] Error: {e}")
            finally:
                self._loop.close()
                self._loop = None
        
        self._thread = threading.Thread(target=run, daemon=True, name="BalancerThread")
        self._thread.start()
        logging.info(f"[BALANCER] Thread started on port {self.listen_port}")
    
    def stop(self):
        """Stop the balancer."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except:
                pass
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except:
                pass
        logging.info(f"[BALANCER] Stopped")
    
    def update_backends(self, backends):
        """Update backend ports list."""
        self.backends = backends
        self.current_backend = 0
        logging.info(f"[BALANCER] Backends updated: {backends}")


_balancer = None


def is_port_in_use(port, host='127.0.0.1'):
    """Check if a port is already in use."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def start_balancer(listen_port=1080, backends=None):
    """Start the proxy balancer."""
    global _balancer
    
    if is_port_in_use(listen_port):
        logging.warning(f"[BALANCER] Port {listen_port} already in use, stopping existing proxy...")
        stop_socks5_proxy(port=listen_port, host='127.0.0.1')
        
        for _ in range(10):
            if not is_port_in_use(listen_port):
                break
            time.sleep(0.3)
        else:
            logging.error(f"[BALANCER] Failed to free port {listen_port}")
            return None
    
    if _balancer is not None and _balancer._running:
        logging.info("[BALANCER] Already running")
        return _balancer
    
    _balancer = ProxyBalancer(listen_port, backends)
    _balancer.start()
    state.save_state(balancer_enabled=True)
    return _balancer


def stop_balancer():
    """Stop the proxy balancer."""
    global _balancer
    if _balancer:
        _balancer.stop()
        _balancer = None
    state.save_state(balancer_enabled=False)
    logging.info("[BALANCER] Stopped")


def update_balancer_backends(backends):
    """Update balancer backend ports."""
    if _balancer:
        _balancer.update_backends(backends)
