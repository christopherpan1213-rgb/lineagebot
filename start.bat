@echo off
chcp 65001 >nul 2>&1
title 天堂Bot 啟動器
echo ========================================
echo   天堂經典版 Bot 啟動器
echo ========================================
echo.

set BOT_DIR=%~dp0
cd /d "%BOT_DIR%"

:: ── 1. 下載最新版 ──
echo [1/3] 下載最新版程式...
curl -sL -o lineage_bot.py.tmp "https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/lineage_bot.py" 2>nul
if exist lineage_bot.py.tmp (
    for %%A in (lineage_bot.py.tmp) do if %%~zA GTR 1000 (
        move /y lineage_bot.py.tmp lineage_bot.py >nul
        echo   lineage_bot.py 已更新
    ) else (
        del lineage_bot.py.tmp
        echo   下載失敗，使用本地版本
    )
) else (
    echo   無法連線，使用本地版本
)

curl -sL -o lineage_data.py.tmp "https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/lineage_data.py" 2>nul
if exist lineage_data.py.tmp (
    for %%A in (lineage_data.py.tmp) do if %%~zA GTR 100 (
        move /y lineage_data.py.tmp lineage_data.py >nul
        echo   lineage_data.py 已更新
    ) else (
        del lineage_data.py.tmp
    )
)
echo.

:: ── 2. 檢查 Python ──
echo [2/3] 檢查環境...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [錯誤] 找不到 Python！
    echo.
    echo   請安裝 Python 3.10+：
    echo   https://www.python.org/downloads/
    echo.
    echo   安裝時務必勾選 "Add Python to PATH" !!!
    echo.
    echo   安裝完後重新執行 start.bat
    echo.
    pause
    exit /b
)
echo   Python OK

:: 檢查套件
python -c "import keyboard" >nul 2>&1
if errorlevel 1 (
    echo   安裝必要套件（第一次需要幾分鐘）...
    pip install keyboard mouse opencv-python numpy pillow mss interception-python dxcam 2>nul
    echo   套件安裝完成
)
echo   套件 OK
echo.

:: ── 3. 啟動 ──
echo [3/3] 啟動 Bot...
echo ========================================
echo.
python lineage_bot.py
if errorlevel 1 (
    echo.
    echo   [錯誤] 程式執行失敗
    echo   如果是套件問題，請手動執行：
    echo   pip install keyboard mouse opencv-python numpy pillow mss interception-python dxcam
)
pause
