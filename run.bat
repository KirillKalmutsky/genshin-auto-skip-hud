@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"
title Genshin Dialogue Auto-Skip

set "UV_EXE="
set "PY_EXE="

color 0B
echo ============================================
echo   Genshin Dialogue Auto-Skip - launcher
echo ============================================
echo.
color 0F

:: ============================================
:: 1. Administrator privileges (self-elevating)
:: ============================================
net session >nul 2>&1
if errorlevel 1 (
    color 0E
    echo [..] Administrator rights are required ^(the game itself runs elevated,
    echo      so key presses are ignored otherwise^). Asking Windows...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    if errorlevel 1 (
        color 0C
        echo.
        echo [ERROR] Elevation was cancelled or failed.
        echo         Right-click run.bat and choose "Run as administrator".
        echo.
        pause
    )
    popd
    endlocal
    exit /b 0
)
color 0A
echo [OK] Running with Administrator privileges
color 0F

:: ============================================
:: 2. Locate uv
:: ============================================
:: NOTE: uv is usually a *per-user* install (%USERPROFILE%\.local\bin), which is
:: only on the PATH of the user who installed it. When UAC elevates with a
:: different administrator account, that PATH entry is gone - which is why a
:: plain "where uv" fails here. So we probe the well-known locations too, and
:: finally every user profile (we are admin at this point, so we can read them).
echo.
echo [..] Looking for uv...
call :find_uv
if not defined UV_EXE (
    color 0E
    echo [..] uv not found - installing it...
    echo.
    call :install_uv
    call :find_uv
)
if not defined UV_EXE goto :no_uv

for /f "usebackq delims=" %%v in (`"!UV_EXE!" --version 2^>^&1`) do set "UV_VERSION=%%v"
color 0A
echo [OK] !UV_VERSION!
echo      !UV_EXE!
color 0F

:: ============================================
:: 3. Dependencies
:: ============================================
:: uv downloads and manages its own Python interpreter, so a system-wide
:: Python installation is NOT required here.
echo.
echo [..] Syncing dependencies into .venv ...
"!UV_EXE!" sync --frozen
if errorlevel 1 (
    color 0E
    echo [..] uv.lock is out of date - re-resolving dependencies...
    "!UV_EXE!" sync
    if errorlevel 1 goto :deps_failed
)
color 0A
echo [OK] Dependencies ready
color 0F

:: ============================================
:: 4. Run the script
:: ============================================
:run_script
color 0B
echo.
echo ============================================
echo   Running Genshin Dialogue Auto-Skip...
echo ============================================
echo.
color 0F

:: Runs from source. For a standalone tray app instead, build.bat makes an .exe.
"!UV_EXE!" run --no-sync -m genshin_autoskip
set "SCRIPT_EXIT_CODE=!errorlevel!"

echo.
if "!SCRIPT_EXIT_CODE!"=="0" (
    color 0A
    echo ============================================
    echo   [SUCCESS] Script completed successfully!
    echo ============================================
    goto :end
)

color 0C
echo ============================================
echo   [ERROR] Script exited with code !SCRIPT_EXIT_CODE!
echo ============================================
echo.
color 0E
set "RETRY="
set /p RETRY="Would you like to retry? (Y/N): "
if /i "!RETRY!"=="Y"   goto :run_script
if /i "!RETRY!"=="YES" goto :run_script
goto :end

:: ============================================
:: Failure paths
:: ============================================
:no_uv
color 0C
echo.
echo [ERROR] Could not find or install uv.
echo.
echo Install it manually in a normal ^(non-elevated^) terminal:
echo   powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
echo or, if you already have Python:
echo   py -m pip install --user uv
echo.
echo Then run this file again.
echo.
goto :end

:deps_failed
color 0C
echo.
echo [ERROR] Failed to install the dependencies.
echo         Check your network connection and try again.
echo.
goto :end

:end
color 0F
popd
endlocal
pause
exit /b 0

:: ============================================
:: Subroutines
:: ============================================

:find_uv
set "UV_EXE="
:: a) whatever is on the current PATH
for /f "delims=" %%p in ('where uv 2^>nul') do if not defined UV_EXE set "UV_EXE=%%~fp"
if defined UV_EXE exit /b 0
:: b) well-known install locations for the current user / the machine
for %%p in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%LOCALAPPDATA%\Programs\uv\uv.exe"
    "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
    "%APPDATA%\Python\Scripts\uv.exe"
    "%ProgramData%\chocolatey\bin\uv.exe"
    "%ProgramFiles%\uv\uv.exe"
) do if not defined UV_EXE if exist "%%~p" set "UV_EXE=%%~fp"
if defined UV_EXE exit /b 0
:: c) Scripts\ of any per-user Python install
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined UV_EXE if exist "%%~d\Scripts\uv.exe" set "UV_EXE=%%~d\Scripts\uv.exe"
)
if defined UV_EXE exit /b 0
:: d) elevated under a different account -> look in every user profile
for /d %%u in ("%SystemDrive%\Users\*") do (
    if not defined UV_EXE if exist "%%~u\.local\bin\uv.exe" set "UV_EXE=%%~u\.local\bin\uv.exe"
    if not defined UV_EXE if exist "%%~u\AppData\Roaming\Python\Scripts\uv.exe" set "UV_EXE=%%~u\AppData\Roaming\Python\Scripts\uv.exe"
)
exit /b 0

:install_uv
echo     Trying the official installer ^(https://astral.sh/uv^)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; irm https://astral.sh/uv/install.ps1 | iex"
if not errorlevel 1 exit /b 0
echo.
echo     Installer failed - falling back to pip...
call :find_python
if not defined PY_EXE (
    echo     No usable Python found either.
    exit /b 1
)
"!PY_EXE!" -m pip install --user uv
exit /b 0

:find_python
set "PY_EXE="
:: the py launcher is the most reliable entry point on Windows
for /f "delims=" %%p in ('where py 2^>nul') do if not defined PY_EXE set "PY_EXE=%%~fp"
if defined PY_EXE exit /b 0
:: plain "python" often resolves to the Microsoft Store alias stub, which is not
:: a real interpreter - skip anything under WindowsApps\
for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined PY_EXE (
        echo %%p | find /i "\WindowsApps\" >nul || set "PY_EXE=%%~fp"
    )
)
exit /b 0
