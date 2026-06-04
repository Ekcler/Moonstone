#!/bin/bash

# Build executable with PyInstaller on Windows
pyinstaller --onedir --noconfirm --noconsole --name SakuraFlow --manifest manifest.xml --add-data "icons;icons" --add-data "zapret;zapret" --add-data "src/service.py;src" --add-data "src;proxy" --add-data "src/tg_ws_proxy.py;." --icon=icons/moonstone.ico --version-file=version.py src/main.py