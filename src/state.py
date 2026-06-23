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
    "first_run": True,
    "ipv6_enabled": True,
    "mtproto_enabled": False,
    "mtproto_port": 1443,
    "mtproto_host": "127.0.0.1",
    "mtproto_secret": None,
    "game_filter_mode": None,
    "ipset_mode": None
}

_lock = threading.Lock()


def _validate_secret(s):
    return s if s else generate_secret()


def _build_state(source):
    return {
        "last_bat": source.get("last_bat"),
        "stopped": source.get("stopped", True),
        "first_run": source.get("first_run", False),
        "ipv6_enabled": source.get("ipv6_enabled", True),
        "mtproto_enabled": source.get("mtproto_enabled", False),
        "mtproto_port": source.get("mtproto_port", 1443),
        "mtproto_host": source.get("mtproto_host", "127.0.0.1"),
        "mtproto_secret": _validate_secret(source.get("mtproto_secret")),
        "game_filter_mode": source.get("game_filter_mode"),
        "ipset_mode": source.get("ipset_mode")
    }


def get_default_state():
    return _build_state(DEFAULT_STATE)


def save_state(**patch):
    with _lock:
        try:
            existing = load_state_unsafe()
            existing.update(patch)
            data = _build_state(existing)
            
            tmp_file = STATE_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            tmp_file.replace(STATE_FILE)
            logging.debug("State saved")
        except Exception as e:
            logging.error(f"Failed to save state: {e}")


def load_state():
    with _lock:
        return load_state_unsafe()


def load_state_unsafe():
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return _build_state(json.load(f))
    except Exception as e:
        logging.warning(f"Failed to load state, using defaults: {e}")
    
    return get_default_state()