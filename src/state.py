"""State management functions."""
import json
import logging

try:
    from .config import STATE_FILE
except ImportError:
    from src.config import STATE_FILE


def save_state(last_bat=None, stopped=None, auto_add_enabled=None, socks5_enabled=None):
    """Save application state to file."""
    try:
        existing = load_state()
        data = {
            "last_bat": last_bat if last_bat is not None else existing.get("last_bat"),
            "stopped": stopped if stopped is not None else existing.get("stopped", True),
            "auto_add_enabled": auto_add_enabled if auto_add_enabled is not None else existing.get("auto_add_enabled", False),
            "socks5_enabled": socks5_enabled if socks5_enabled is not None else existing.get("socks5_enabled", False)
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        logging.info(f"Сохранено состояние: {data}")
    except Exception as e:
        logging.error(f"Ошибка при сохранении состояния: {e}")


def load_state():
    """Load application state from file."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logging.info(f"Загружено состояние: {data}")
            return {
                "last_bat": data.get("last_bat"),
                "stopped": data.get("stopped", True),
                "auto_add_enabled": data.get("auto_add_enabled", False),
                "socks5_enabled": data.get("socks5_enabled", False)
            }
    except Exception as e:
        logging.error(f"Ошибка при загрузке состояния: {e}")
    return {"last_bat": None, "stopped": True, "auto_add_enabled": False, "socks5_enabled": False}
