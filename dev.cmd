@echo off
REM Uta Learn Next - one-click launcher.
REM All the real work (and all Chinese text) lives in start.ps1, because cmd.exe
REM mangles UTF-8 multi-byte characters when parsing a .cmd file.
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [X] PowerShell not found. Windows 7+ ships it; please check your PATH.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
  echo.
  echo   Launcher exited with an error. See the messages above.
  pause
)
