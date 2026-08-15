@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"
title Genshin Auto-Skip - build

:: Building needs no privileges of its own, but this project usually sits under
:: Program Files, where writing .venv does - and a virtual environment created
:: by an elevated run cannot be updated by a normal one.
net session >nul 2>&1
if errorlevel 1 (
    echo [..] Elevating to write the virtual environment...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    popd
    endlocal
    exit /b 0
)

set "UV_EXE="
for /f "delims=" %%p in ('where uv 2^>nul') do if not defined UV_EXE set "UV_EXE=%%~fp"
for %%p in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%APPDATA%\Python\Scripts\uv.exe"
    "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
) do if not defined UV_EXE if exist "%%~p" set "UV_EXE=%%~fp"
for /d %%u in ("%SystemDrive%\Users\*") do (
    if not defined UV_EXE if exist "%%~u\.local\bin\uv.exe" set "UV_EXE=%%~u\.local\bin\uv.exe"
)
if not defined UV_EXE (
    echo [ERROR] uv not found. Install it with:
    echo     powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    pause
    popd & endlocal & exit /b 1
)

echo [..] Syncing dependencies including the dev group...
"!UV_EXE!" sync --group dev
if errorlevel 1 (
    echo [..] Sync failed - rebuilding the virtual environment from scratch...
    rmdir /s /q .venv 2>nul
    "!UV_EXE!" sync --group dev
    if errorlevel 1 (
        echo [ERROR] Dependency sync failed.
        pause
        popd & endlocal & exit /b 1
    )
)

echo.
"!UV_EXE!" run --no-sync --group dev python src\build.py %*
set "CODE=!errorlevel!"

echo.
if "!CODE!"=="0" (
    echo ============================================
    echo   Done - GenshinAutoSkip.exe is in this folder
    echo ============================================
) else (
    echo [ERROR] Build failed with code !CODE!
)
popd
endlocal
pause
