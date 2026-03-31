@echo off
chcp 65001 >nul 2>&1
title 天堂Bot 啟動器
echo ========================================
echo   天堂經典版 Bot 啟動器
echo ========================================
echo.

set BOT_DIR=%~dp0
cd /d "%BOT_DIR%"
set BASE=https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main
set DL=powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try{(New-Object Net.WebClient).DownloadFile('%BASE%/

:: ── 1. 更新所有檔案（含 start.bat 自己）──
echo [1/3] 下載最新版...

powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $wc=New-Object Net.WebClient; $base='https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main'; $files=@('lineage_bot.py','lineage_data.py','start.bat','update.py'); foreach($f in $files){try{$wc.DownloadFile(\"$base/$f\",\"%BOT_DIR%$f.tmp\"); if((Get-Item \"%BOT_DIR%$f.tmp\").Length -gt 50){Copy-Item \"%BOT_DIR%$f.tmp\" \"%BOT_DIR%$f\" -Force; Remove-Item \"%BOT_DIR%$f.tmp\" -Force; Write-Host \"  $f OK\"}else{Remove-Item \"%BOT_DIR%$f.tmp\" -Force; Write-Host \"  $f 跳過\"}}catch{Write-Host \"  $f 失敗: $($_.Exception.Message)\"}}"

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
