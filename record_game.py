"""
遊戲畫面錄影工具 (DirectX)
按 F1 開始錄影
按 F2 停止錄影並存檔
錄影存到桌面 game_captures 資料夾
"""
import os, time, threading
import dxcam
import keyboard
from PIL import Image
import numpy as np

SAVE_DIR = os.path.expanduser("~/Desktop/game_captures")
os.makedirs(SAVE_DIR, exist_ok=True)

camera = dxcam.create()
recording = False
frames = []
fps = 5  # 低 fps 足夠分析用，省空間

def record_loop():
    global recording, frames
    interval = 1.0 / fps
    while recording:
        frame = camera.grab()
        if frame is not None:
            frames.append(frame.copy())
            print(f"\r錄影中... {len(frames)} 幀 ({len(frames)/fps:.1f}秒)", end="", flush=True)
        time.sleep(interval)

def start_recording():
    global recording, frames
    if recording:
        return
    frames = []
    recording = True
    t = threading.Thread(target=record_loop, daemon=True)
    t.start()
    print("\n[F1] 開始錄影！按 F2 停止")

def stop_recording():
    global recording, frames
    if not recording:
        return
    recording = False
    time.sleep(0.3)

    if not frames:
        print("\n沒有錄到任何畫面")
        return

    print(f"\n\n停止錄影，共 {len(frames)} 幀")

    # 存成圖片序列 + 取幾張關鍵幀
    rec_dir = os.path.join(SAVE_DIR, f"recording_{int(time.time())}")
    os.makedirs(rec_dir, exist_ok=True)

    # 存所有幀
    for i, f in enumerate(frames):
        img = Image.fromarray(f)
        img.save(os.path.join(rec_dir, f"frame_{i:04d}.png"))

    # 另外存 5 張均勻取樣的關鍵幀到主目錄（方便快速查看）
    step = max(1, len(frames) // 5)
    for idx, i in enumerate(range(0, len(frames), step)):
        if idx >= 5:
            break
        img = Image.fromarray(frames[i])
        img.save(os.path.join(SAVE_DIR, f"keyframe_{idx+1}.png"))

    print(f"已存到: {rec_dir}")
    print(f"關鍵幀已存到: {SAVE_DIR}/keyframe_1~5.png")
    print(f"\n可以按 F1 再錄一段，或 F3 結束程式")

print("=" * 50)
print("遊戲畫面錄影工具 (DirectX)")
print("=" * 50)
print(f"錄影存放: {SAVE_DIR}")
print(f"錄影 FPS: {fps}")
print()
print("F1 = 開始錄影")
print("F2 = 停止錄影並存檔")
print("F3 = 結束程式")
print()
print("切到遊戲畫面後按 F1 開始...")

keyboard.add_hotkey('F1', start_recording)
keyboard.add_hotkey('F2', stop_recording)
keyboard.wait('F3')
print("\n結束。")
del camera
