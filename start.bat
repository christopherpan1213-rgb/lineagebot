@echo off
chcp 65001 >nul 2>&1
title 天堂Bot 啟動器 v17.7
echo ========================================
echo   天堂經典版 Bot 啟動器
echo ========================================
echo.

set "BOT_DIR=%~dp0"
cd /d "%BOT_DIR%"

:: ── 0. 先更新 start.bat 自己 ──
echo [0/2] 檢查啟動器更新...
powershell -Command ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; ^
  try { ^
    $url = 'https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/start.bat'; ^
    $tmp = Join-Path '%BOT_DIR%' 'start.bat.new'; ^
    (New-Object Net.WebClient).DownloadFile($url, $tmp); ^
    if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 100) { ^
      $old = Get-Content (Join-Path '%BOT_DIR%' 'start.bat') -Raw -ErrorAction SilentlyContinue; ^
      $new = Get-Content $tmp -Raw; ^
      if ($old -ne $new) { ^
        Write-Host '  啟動器有更新，下次啟動生效'; ^
        Copy-Item $tmp (Join-Path '%BOT_DIR%' 'start.bat') -Force ^
      } else { ^
        Write-Host '  啟動器已是最新' ^
      }; ^
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue ^
    } ^
  } catch { Write-Host '  啟動器更新跳過' }"

:: ── 1. 更新 exe ──
echo [1/2] 檢查程式更新...
powershell -Command ^
  "[Net.ServicePointManager]::SecurityProtool=[Net.SecurityProtocolType]::Tls12; ^
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
        Write-Host '  下載中（約270MB，請稍候）...'; ^
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

:: ── 2. 建立資料夾 ──
if not exist "%BOT_DIR%config" mkdir "%BOT_DIR%config"

:: ── 3. 啟動（崩潰自動重啟） ──
echo [2/2] 啟動 Bot（崩潰會自動重啟）...
echo ========================================
echo.

set "EXE_PATH=%BOT_DIR%LineageBot.exe"

:loop
if exist "%EXE_PATH%" (
    echo   [%time%] 啟動 LineageBot.exe
    "%EXE_PATH%"
    echo   [%time%] 程式已關閉，10秒後自動重啟...
    echo   （按 Ctrl+C 取消重啟）
    timeout /t 10
    goto loop
) else (
    echo   找不到 LineageBot.exe！
    pause
)
