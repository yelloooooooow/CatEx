@echo off
setlocal
cd /d "%~dp0"
title CatEx Workbench Launcher

echo ============================================================
echo   CatEx Workbench - local launcher
echo ============================================================
echo.

where node.exe >nul 2>nul
if errorlevel 1 (
    echo Node.js was not found. Install Node.js 24, then try again.
    pause >nul
    exit /b 1
)

node.exe "%~dp0scripts\start_web_poc.mjs" %*
set "CATEX_EXIT=%ERRORLEVEL%"

if not "%CATEX_EXIT%"=="0" (
    echo.
    echo CatEx could not start. Read the error above, then press any key.
    pause >nul
)

endlocal
exit /b %CATEX_EXIT%
