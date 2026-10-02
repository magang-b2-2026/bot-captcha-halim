@echo off
:: komdigi-bot Windows Service Watchdog
:: Jalankan sekali, akan auto-restart jika crash.
:: Setup: taruh file ini di C:\Coding\Komdigi\run_service.bat
:: Lalu daftarkan di Windows Task Scheduler sebagai trigger "At startup"

setlocal
set "PROJECT_DIR=C:\Coding\Komdigi"
set "LOG_DIR=%PROJECT_DIR%\outputs\logs"
set "RESTART_DELAY=5"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] komdigi-bot watchdog started >> "%LOG_DIR%\watchdog.log"

:LOOP
echo [%date% %time%] Starting komdigi-bot service... >> "%LOG_DIR%\watchdog.log"
echo Starting komdigi-bot service...

cd /d "%PROJECT_DIR%"
uv run python start_service.py --host 0.0.0.0 --port 8080

echo [%date% %time%] Service exited (code %ERRORLEVEL%). Restarting in %RESTART_DELAY%s... >> "%LOG_DIR%\watchdog.log"
echo Service crashed/exited. Restarting in %RESTART_DELAY% seconds...
timeout /t %RESTART_DELAY% /nobreak > nul
goto LOOP
