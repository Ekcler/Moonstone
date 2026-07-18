#!/bin/bash

# Build executable with PyInstaller on Windows
pyinstaller --onedir --noconfirm --noconsole --name SakuraFlow --manifest manifest.xml --add-data "icons;icons" --add-data "zapret;zapret" --add-data "src;src" --icon=icons/moonstone.ico --version-file=version.py src/main.py