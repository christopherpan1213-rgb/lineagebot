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
echo [1/2] 檢查更新...

powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $wc=New-Object Net.WebClient; $base='https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main'; $files=@('lineage_data.py','start.bat'); foreach($f in $files){try{$wc.DownloadFile(\"$base/$f\",\"%BOT_DIR%$f.tmp\"); if((Get-Item \"%BOT_DIR%$f.tmp\").Length -gt 50){Copy-Item \"%BOT_DIR%$f.tmp\" \"%BOT_DIR%$f\" -Force; Remove-Item \"%BOT_DIR%$f.tmp\" -Force; Write-Host \"  $f OK\"}else{Remove-Item \"%BOT_DIR%$f.tmp\" -Force}}catch{Write-Host \"  $f 跳過\"}}"

:: 下載最新 exe（從 GitHub Releases）
echo   檢查 exe 更新...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try{$r=Invoke-RestMethod 'https://api.github.com/repos/christopherpan1213-rgb/lineagebot/releases/latest' -TimeoutSec 10; $asset=$r.assets|Where-Object{$_.name -eq 'LineageBot.exe'}; if($asset){$dl=$asset.browser_download_url; $remote=$r.tag_name; $needUpdate=$true; if(Test-Path '%BOT_DIR%version.txt'){$local=Get-Content '%BOT_DIR%version.txt' -Raw; if($local.Trim() -eq $remote){$needUpdate=$false; Write-Host \"  LineageBot.exe 已是最新 ($remote)\"}}; if($needUpdate){Write-Host \"  下載 LineageBot.exe ($remote)...\"; (New-Object Net.WebClient).DownloadFile($dl,'%BOT_DIR%LineageBot.exe'); $remote|Set-Content '%BOT_DIR%version.txt'; Write-Host '  LineageBot.exe 更新完成'}}}catch{Write-Host '  exe更新跳過:' $_.Exception.Message}"

echo.

:: ── 2. 啟動 ──
echo [2/2] 啟動 Bot...
echo ========================================
echo.

if exist "%BOT_DIR%LineageBot.exe" (
    start "" "%BOT_DIR%LineageBot.exe"
) else (
    echo   找不到 LineageBot.exe
    echo   嘗試用 Python 啟動...
    python lineage_bot.py
)
pause
