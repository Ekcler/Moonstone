"""State management functions."""
import json
import logging
import os
import threading

try:
    from .config import STATE_FILE
except ImportError:
    from src.config import STATE_FILE


def generate_secret():
    """Generate random 32 hex chars (16 bytes)."""
    return os.urandom(16).hex()


DEFAULT_STATE = {
    "last_bat": None,
    "stopped": True,
    "auto_add_enabled": False,
    "socks5_enabled": False,
    "proxies": [
        {"port": 1081, "host": "127.0.0.1", "enabled": True},
        {"port": 1082, "host": "127.0.0.1", "enabled": True},
        {"port": 1083, "host": "127.0.0.1", "enabled": True}
    ],
    "auto_switch_enabled": False,
    "auto_switch_timeout": 5,
    "balancer_enabled": False,
    "balancer_listen": 1080,
    "balancer_backends": [1081, 1082, 1083],
    "proxy_secret": None,
    "mtproto_enabled": False,
    "mtproto_port": 1080,
    "mtproto_host": "127.0.0.1",
    "mtproto_secret": None
}

DEFAULT_PROXIES = DEFAULT_STATE["proxies"]

_lock = threading.Lock()


def get_default_state():
    """Get default state with generated secrets."""
    return {
        **DEFAULT_STATE,
        "proxy_secret": generate_secret(),
        "mtproto_secret": generate_secret()
    }


def save_state(**patch):
    """Save application state to file. Uses patch-based update."""
    with _lock:
        try:
            existing = load_state_unsafe()
            existing.update(patch)
            
            data = {
                "last_bat": existing.get("last_bat"),
                "stopped": existing.get("stopped", True),
                "auto_add_enabled": existing.get("auto_add_enabled", False),
                "socks5_enabled": existing.get("socks5_enabled", False),
                "proxies": existing.get("proxies"),
                "auto_switch_enabled": existing.get("auto_switch_enabled", False),
                "auto_switch_timeout": existing.get("auto_switch_timeout", 5),
                "balancer_enabled": existing.get("balancer_enabled", False),
                "balancer_listen": existing.get("balancer_listen", 1080),
                "balancer_backends": existing.get("balancer_backends", [1081, 1082, 1083]),
                "proxy_secret": existing.get("proxy_secret") or generate_secret(),
                "mtproto_enabled": existing.get("mtproto_enabled", False),
                "mtproto_port": existing.get("mtproto_port", 1080),
                "mtproto_host": existing.get("mtproto_host", "127.0.0.1"),
                "mtproto_secret": existing.get("mtproto_secret") or generate_secret()
            }
            
            tmp_file = STATE_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            tmp_file.replace(STATE_FILE)
            logging.debug("State saved")
        except Exception as e:
            logging.error(f"Failed to save state: {e}")


def load_state():
    """Load application state from file (thread-safe)."""
    with _lock:
        return load_state_unsafe()


def load_state_unsafe():
    """Load state without lock (internal use)."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return {
                "last_bat": data.get("last_bat"),
                "stopped": data.get("stopped", True),
                "auto_add_enabled": data.get("auto_add_enabled", False),
                "socks5_enabled": data.get("socks5_enabled", False),
                "proxies": data.get("proxies", DEFAULT_PROXIES),
                "auto_switch_enabled": data.get("auto_switch_enabled", False),
                "auto_switch_timeout": data.get("auto_switch_timeout", 5),
                "balancer_enabled": data.get("balancer_enabled", False),
                "balancer_listen": data.get("balancer_listen", 1080),
                "balancer_backends": data.get("balancer_backends", [1081, 1082, 1083]),
                "proxy_secret": data.get("proxy_secret") or generate_secret(),
                "mtproto_enabled": data.get("mtproto_enabled", False),
                "mtproto_port": data.get("mtproto_port", 1080),
                "mtproto_host": data.get("mtproto_host", "127.0.0.1"),
                "mtproto_secret": data.get("mtproto_secret") or generate_secret()
            }
    except Exception as e:
        logging.warning(f"Failed to load state, using defaults: {e}")
    
    return get_default_state()