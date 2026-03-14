# Sakura Flow 🌸

An optimized desktop tray application for managing [zapret](https://github.com) on Windows.

![Sakura Flow Interface](images/interface.png)

## Key Enhancements:
- **Redesigned UI**: Modern "Sakura" dark-pink theme for the system tray menu.
- **Improved UX**: The menu now opens with both **Left-Click (LMB)** and Right-Click (RMB).
- **Network Tools**: Built-in Ping, Tracert and Live Traffic Monitor (KB/s).
- **DNS Optimizer**: Smart DNS tester with one-click apply to Windows settings.
- **Blocklist Editor**: Manage your domains directly from the app.
- 
- **Portable Mode**: The compiled `.exe` correctly locates `zapret` and `icons` folders.

## Quick Start

### Running in Debug Mode
```bash
python -m src.main
```
### Building
```bash
pyinstaller --noconfirm --onefile --windowed --uac-admin --icon "icons/moonstone.ico" --name "SakuraFlow" src/main.py
```
