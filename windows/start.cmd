@echo off
rem ORRERY for Windows: start the host and open it in the browser.
rem Double-click this file, or run it with extra host options (e.g. --port 8800).
rem Set ORRERY_PYTHON to a python.exe (quoted or not) to choose the Python.
setlocal
title ORRERY for Windows
rem No cd: relative arguments keep meaning the caller's folder, and UNC paths work.
set "HERE=%~dp0"

rem Each candidate must run and be 3.11 or later; it answers with its real
rem python.exe, so a Store alias, an old Python or a .bat shim is skipped or resolved.
set "PY="
if defined ORRERY_PYTHON (
    call :try "%ORRERY_PYTHON:"=%"
) else (
    call :try python
)
if not defined ORRERY_PYTHON if not defined PY call :try py -3
if not defined PY (
    if defined ORRERY_PYTHON (
        echo ORRERY_PYTHON does not point to a Python 3.11 or later that runs.
    ) else (
        echo Python 3.11 or later was not found ^(tried python and py -3^).
        echo Install it from https://www.python.org/ or set ORRERY_PYTHON to its python.exe.
    )
    goto :fail
)

rem web.AppKey needs aiohttp 3.9 or later.
"%PY%" -c "import winpty, pyte; from aiohttp import web; web.AppKey" >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing the host's packages ^(aiohttp, pywinpty, pyte^)...
    "%PY%" -m pip install -r "%HERE%requirements.txt" || goto :fail
)

"%PY%" "%HERE%host\server.py" --open %*
if %errorlevel% neq 0 goto :fail
exit /b 0

:try
for /f "usebackq delims=" %%P in (`call %* -c "import sys; sys.version_info >= (3, 11) and print(sys.executable)" 2^>nul`) do set "PY=%%P"
exit /b 0

:fail
echo.
pause
exit /b 1
