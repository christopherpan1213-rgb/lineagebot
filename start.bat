@echo off
chcp 65001 >nul 2>&1
title 天堂Bot 啟動器
echo ========================================
echo   天堂經典版 Bot 啟動器
echo ========================================
echo.

:: 取得 start.bat 所在目錄
set "BOT_DIR=%~dp0"
cd /d "%BOT_DIR%"

:: ── 1. 檢查更新 ──
echo [1/2] 檢查更新...

:: 下載最新 exe（從 GitHub Releases）
powershell -Command ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; ^
  try { ^
    $r = Invoke-RestMethod 'https://api.github.com/repos/christopherpan1213-rgb/lineagebot/releases/latest' -TimeoutSec 15; ^
    $asset = $r.assets | Where-Object { $_.name -eq 'LineageBot.exe' }; ^
    if ($asset) { ^
      $remote = $r.tag_name; ^
      $needUpdate = $true; ^
      $vFile = Join-Path '%BOT_DIR%' 'version.txt'; ^
      if (Test-Path $vFile) { ^
        $local = (Get-Content $vFile -Raw).Trim(); ^
        if ($local -eq $remote) { ^
          $needUpdate = $false; ^
          Write-Host '  已是最新版本:' $remote ^
        } ^
      }; ^
      if ($needUpdate) { ^
        Write-Host '  發現新版本:' $remote; ^
        $exePath = Join-Path '%BOT_DIR%' 'LineageBot.exe'; ^
        $tmpPath = Join-Path '%BOT_DIR%' 'LineageBot.exe.tmp'; ^
        Write-Host '  下載中...'; ^
        (New-Object Net.WebClient).DownloadFile($asset.browser_download_url, $tmpPath); ^
        if ((Test-Path $tmpPath) -and (Get-Item $tmpPath).Length -gt 1000000) { ^
          if (Test-Path $exePath) { Remove-Item $exePath -Force }; ^
          Move-Item $tmpPath $exePath -Force; ^
          $remote | Set-Content (Join-Path '%BOT_DIR%' 'version.txt'); ^
          Write-Host '  更新完成!' ^
        } else { ^
          Write-Host '  下載失敗（檔案太小）'; ^
          if (Test-Path $tmpPath) { Remove-Item $tmpPath -Force } ^
        } ^
      } ^
    } ^
  } catch { ^
    Write-Host '  更新檢查失敗:' $_.Exception.Message ^
  }"

echo.

:: ── 2. 啟動 ──
echo [2/2] 啟動 Bot...
echo ========================================
echo.

set "EXE_PATH=%BOT_DIR%LineageBot.exe"
if exist "%EXE_PATH%" (
    echo   啟動 %EXE_PATH%
    start "" "%EXE_PATH%"
) else (
    echo   找不到 LineageBot.exe！
    echo   請確認檔案在: %BOT_DIR%
    echo.
    echo   嘗試用 Python 啟動...
    python "%BOT_DIR%lineage_bot.py"
)

timeout /t 3 >nul
