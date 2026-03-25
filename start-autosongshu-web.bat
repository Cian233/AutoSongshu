@echo off
setlocal
powershell.exe -ExecutionPolicy Bypass -File "%~dp0scripts\start-autosongshu.ps1" -LaunchCdpBrowser %*
