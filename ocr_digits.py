"""簡易數字辨識器 — 只辨識 HP/MP 條上的 0-9 和 /
不需要 Tesseract，用結構特徵辨識像素字型。
"""

import cv2
import numpy as np
import subprocess
import os
import re


def ocr_hp_mp(image_bgr):
    """從 HP/MP 條圖片讀取數字，回傳 (current, max) 或 None

    Args:
        image_bgr: BGR 格式的 HP/MP 條截圖（OpenCV 格式）

    Returns:
        (current, max) tuple，例如 (90, 123)，失敗回傳 None
    """
    # 放大 + 二值化
    h, w = image_bgr.shape[:2]
    scale = max(4, 40 // max(h, 1))
    big = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

    # 用 Windows OCR（最可靠）
    result = _windows_ocr(thresh)
    if result:
        return result

    # Fallback: 用像素比例法
    return None


def _windows_ocr(thresh_img):
    """用 Windows 內建 OCR 讀取"""
    try:
        # 存暫存圖
        tmp = os.path.join(os.environ.get('TEMP', '.'), '_hp_ocr.png')
        cv2.imwrite(tmp, thresh_img)

        ps_script = f'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]

function Await($WinRtTask, $ResultType) {{
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})
    if ($asTaskGeneric -is [array]) {{ $asTaskGeneric = $asTaskGeneric[0] }}
    $netTask = $asTaskGeneric.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync("{tmp.replace(chr(47), chr(92))}")) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
Write-Host $result.Text
'''
        result = subprocess.run(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
            capture_output=True, text=True, timeout=5
        )
        text = result.stdout.strip()
        return _parse_hp_text(text)
    except:
        return None
    finally:
        try: os.remove(tmp)
        except: pass


def _parse_hp_text(text):
    """從 OCR 文字中提取 HP 數值
    可能的格式: "HP: 90/123", "HP:90/123", "90/123", "HP 90 123" 等
    """
    if not text:
        return None

    # 清理常見 OCR 錯誤
    text = text.replace('O', '0').replace('o', '0')
    text = text.replace('l', '1').replace('I', '1')
    text = text.replace(' ', '')

    # 找 數字/數字 的模式
    match = re.search(r'(\d+)[/\\|](\d+)', text)
    if match:
        current = int(match.group(1))
        maximum = int(match.group(2))
        if 0 < maximum <= 9999 and 0 <= current <= maximum:
            return (current, maximum)

    return None


def read_hp_from_bar(cx, cy, cw, ch, grab_func):
    """從遊戲視窗讀取 HP 值

    Args:
        cx, cy, cw, ch: 遊戲客戶區座標
        grab_func: 截圖函式 grab_region(left, top, width, height)

    Returns:
        float: HP 比例 (0.0-1.0)，失敗回傳 -1
    """
    # HP 條在底部 UI，大約 Y=88%-96%, X=10%-50%
    bar_y = int(ch * 0.88)
    bar_h = int(ch * 0.08)
    bar_x = int(cw * 0.10)
    bar_w = int(cw * 0.40)

    try:
        frame = grab_func(cx + bar_x, cy + bar_y, bar_w, bar_h)
        if frame is None or frame.size == 0:
            return -1
        result = ocr_hp_mp(frame)
        if result:
            current, maximum = result
            return current / maximum
        return -1
    except:
        return -1


def read_mp_from_bar(cx, cy, cw, ch, grab_func):
    """從遊戲視窗讀取 MP 值"""
    bar_y = int(ch * 0.88)
    bar_h = int(ch * 0.08)
    bar_x = int(cw * 0.52)
    bar_w = int(cw * 0.40)

    try:
        frame = grab_func(cx + bar_x, cy + bar_y, bar_w, bar_h)
        if frame is None or frame.size == 0:
            return -1
        result = ocr_hp_mp(frame)
        if result:
            current, maximum = result
            return current / maximum
        return -1
    except:
        return -1


# 測試
if __name__ == "__main__":
    img = cv2.imread("C:/Users/User/Desktop/hp_roi.png")
    if img is not None:
        result = ocr_hp_mp(img)
        print(f"OCR result: {result}")
        if result:
            current, maximum = result
            print(f"HP: {current}/{maximum} = {current/maximum*100:.1f}%")
    else:
        print("Image not found")
