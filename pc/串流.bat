@echo off
cd /d "%~dp0"
python chuni_stream.py --usb %*
if errorlevel 1 pause
