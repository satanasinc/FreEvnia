# Builds dist\FreEvnia-windows-x64.zip (run on Windows with Python 3.12): FreEvnia.exe (window) + freevnia.exe (CLI).
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root
python -m pip install --upgrade pip
python -m pip install pyinstaller pyusb libusb-package PySide6-Essentials .
Remove-Item -Recurse -Force build, dist\FreEvnia, dist\FreEvnia-windows -ErrorAction SilentlyContinue
# the window: libusb-1.0.dll comes from libusb-package
python -m PyInstaller --noconfirm --windowed --name FreEvnia --collect-all libusb_package packaging\windows\gui_entry.py
# the command line: one small file, no Qt
python -m PyInstaller --noconfirm --onefile --console --name freevnia --collect-all libusb_package `
    --exclude-module PySide6 packaging\windows\cli_entry.py
$out = "dist\FreEvnia-windows"
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item -Recurse dist\FreEvnia $out\FreEvnia
Copy-Item dist\freevnia.exe $out\freevnia.exe
Copy-Item LICENSE, README.md $out
@"
FreEvnia for Windows (unofficial)
=================================
FreEvnia\FreEvnia.exe  - the window (PBP / PIP / swap / Ambiglow / settings)
freevnia.exe           - command line (run it in a terminal: freevnia.exe --help)

The monitor's USB upstream cable must go to THIS computer (the one on the left/main picture).
Close the official Evnia Precision Center first: only one program can use the monitor at a time.
Windows SmartScreen may warn about an unknown publisher (the files are not signed): More info > Run anyway.
https://github.com/satanasinc/FreEvnia
"@ | Set-Content -Encoding utf8 $out\LEEME.txt
Compress-Archive -Force -Path $out\* -DestinationPath dist\FreEvnia-windows-x64.zip
Get-ChildItem dist\*.zip
