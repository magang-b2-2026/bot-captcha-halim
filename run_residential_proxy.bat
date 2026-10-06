@echo off
:: ==============================================================================
:: run_residential_proxy.bat — Komdigi Bot Residential SOCKS5 Proxy Watchdog
:: ==============================================================================
setlocal
set "PROJECT_DIR=C:\Coding\Komdigi"
set "LOG_DIR=%PROJECT_DIR%\outputs\logs"
set "RESTART_DELAY=5"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] Residential Proxy watchdog started >> "%LOG_DIR%\residential_proxy_watchdog.log"

:LOOP
echo [%date% %time%] Starting Residential SOCKS5 Proxy on 0.0.0.0:1080... >> "%LOG_DIR%\residential_proxy_watchdog.log"
echo Starting Residential SOCKS5 Proxy on 0.0.0.0:1080...

cd /d "%PROJECT_DIR%"
uv run python start_residential_proxy.py --host 0.0.0.0 --port 1080

echo [%date% %time%] Proxy exited (code %ERRORLEVEL%). Restarting in %RESTART_DELAY%s... >> "%LOG_DIR%\residential_proxy_watchdog.log"
echo Proxy stopped/exited. Restarting in %RESTART_DELAY% seconds...
timeout /t %RESTART_DELAY% /nobreak > nul
goto LOOP
