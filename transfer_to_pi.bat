@echo off
title Transfer Files to Raspberry Pi 5
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0transfer_to_pi.ps1"
pause
