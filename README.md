# Sakura Flow 🌸

An optimized desktop tray application for managing [zapret](https://github.com) on Windows.

![Sakura Flow Interface](images/interface.png)

## Features
- **DPI Bypass**: Creates a Windows service from zapret `.bat` profiles for persistent DPI bypass
- **SOCKS5 Proxy**: Built-in Telegram WebSocket bridge proxy (127.0.0.1:1080) with DC auto-detection and TCP fallback
- **Network Tools**: Ping, Tracert, and live traffic monitor (KB/s)
- **DNS Optimizer**: Smart DNS tester (Cloudflare, Google, Yandex, Quad9) with one-click apply to Windows
- **Blocklist Editor**: Edit bypass domains directly from the app
- **Auto-add domains**: Monitors DNS cache and automatically adds unreachable domains to the blocklist
- **Autostart**: Task Scheduler integration for launch on login
- **Sleep/Wake handler**: Automatically restarts the service after the computer wakes from sleep
- **Portable Mode**: The compiled `.exe` correctly locates all resources

## Requirements
- Python 3.x (tested with 3.13)
- Administrator privileges (required for service management)
- Windows 10/11

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run as administrator:
```bash
python -m src.main
```

> **Note:** The application requires administrator privileges to manage Windows services. It will automatically request elevation if not already running as admin.

## Building

```bash
pyinstaller --noconfirm --onedir --windowed 
--name "SakuraFlow" 
--icon "icons/moonstone.ico" 
--manifest "manifest.xml" 
--add-data "icons;icons" 
--add-data "zapret;zapret" 
--add-data "src/tg_ws_proxy.py;." 
src/main.py
```

Or use the included build script:
```bash
bash build.sh
```

## Credits & Special Thanks
- **Flowseal** — for the incredible tg-ws-proxy engine that powers our Telegram connectivity
- **NixNi** — for the inspiration and core logic behind the Sakura Flow interface and networking tools
