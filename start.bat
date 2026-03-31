@echo off
chcp 65001 >nul 2>&1
title 天堂Bot 啟動器
echo ========================================
echo   天堂經典版 Bot 啟動器
echo ========================================
echo.

set BOT_DIR=%~dp0
cd /d "%BOT_DIR%"

:: ── 1. 用 PowerShell 下載最新版 ──
echo [1/3] 下載最新版程式...

powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try{(New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/lineage_bot.py','%BOT_DIR%lineage_bot.py');Write-Host '  lineage_bot.py OK'}catch{Write-Host '  lineage_bot.py 失敗:' $_.Exception.Message}"

powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try{(New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/lineage_data.py','%BOT_DIR%lineage_data.py');Write-Host '  lineage_data.py OK'}catch{Write-Host '  lineage_data.py 失敗:' $_.Exception.Message}"

echo.

:: ── 2. 檢查 Python ──
echo [2/3] 檢查環境...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [錯誤] 找不到 Python！
    echo   請安裝 Python 3.10+：
    echo   https://www.python.org/downloads/
    echo   安裝時務必勾選 "Add Python to PATH"
    echo   安裝完後重新執行 start.bat
    pause
    exit /b
)
echo   Python OK

python -c "import keyboard" >nul 2>&1
if errorlevel 1 (
    echo   安裝必要套件（第一次需要幾分鐘）...
    pip install keyboard mouse opencv-python numpy pillow mss interception-python dxcam 2>nul
)
echo   套件 OK
echo.

:: ── 3. 啟動 ──
echo [3/3] 啟動 Bot...
echo ========================================
echo.
python lineage_bot.py
pause
