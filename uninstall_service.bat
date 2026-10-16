@echo off
title Komdigi Bot - Uninstall Residential SOCKS5 Service
echo ============================================================
echo  Mencabut Komdigi Residential Proxy Windows Service
echo ============================================================
echo.

:: Check for administrative rights
net session >nul 2>&1
if %errorLevel% == 0 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_residential_service.ps1"
) else (
    echo [!] Meminta konfirmasi hak Administrator (UAC)...
    powershell.exe -Command "Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \""%~dp0scripts\uninstall_residential_service.ps1\""' -Verb RunAs -Wait"
)

echo.
echo Selesai. Tekan tombol apa saja untuk keluar...
pause >nul
