# Sakura Flow 🌸

An optimized desktop tray application for managing [zapret](https://github.com) on Windows.

![Sakura Flow Interface](images/interface.png)

## Key Enhancements:
- **Redesigned UI**: Modern "Sakura" dark-pink theme with a **dedicated Telegram Proxy button** for instant SOCKS5 (port 1080) configuration.
- **Network Tools**: Built-in Ping, Tracert and Live Traffic Monitor (KB/s).
- **DNS Optimizer**: Smart DNS tester with one-click apply to Windows system settings.
- **Blocklist Editor**: Manage your bypass domains directly from the app interface.
- **Portable Mode**: The compiled `.exe` correctly locates `zapret`, `icons` folders, and the proxy engine.

## Quick Start
```bash
python -m src.main
```
### Building
``` bash
pyinstaller --noconfirm --onedir --windowed --uac-admin `
--name "SakuraFlow" `
--icon "icons/moonstone.ico" `
--add-data "icons;icons" `
--add-data "zapret;zapret" `
--add-data "src/tg_ws_proxy.py;." `
src/main.py
```
#### Credits & Special Thanks
*Flowseal* — for the incredible tg-ws-proxy engine that powers our Telegram connectivity.
*NixNi* — for the inspiration and core logic behind the Sakura Flow interface and networking tools.