@echo off
title FocusGuard UI Dashboard & Face Auth
echo ========================================================
echo        FOCUSGUARD DASHBOARD & BIOMETRIC AUTH
echo ========================================================
echo.

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [*] Launching FocusGuard UI with Python 3.13...
    py -3.13 ui\server.py
    goto end
)

echo [*] Launching FocusGuard UI with default python...
python ui\server.py

:end
pause
