"""
觀察玩家打怪模式 — 每 0.3 秒記錄滑鼠位置+游標+截圖
持續 120 秒，按 End 提前結束
"""
import ctypes, ctypes.wintypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)
import time, sys, json, os
sys.stdout.reconfigure(encoding='utf-8')
import win32gui, keyboard
from PIL import Image
from mss import mss

SAVE_DIR = os.path.expanduser("~/Desktop/game_captures/observe")
os.makedirs(SAVE_DIR, exist_ok=True)

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize",ctypes.c_uint),("flags",ctypes.c_uint),
                ("hCursor",ctypes.wintypes.HANDLE),("ptScreenPos",ctypes.wintypes.POINT)]

def get_info():
    ci = CURSORINFO(); ci.cbSize = ctypes.sizeof(CURSORINFO)
    ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci))
    lb = ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000 != 0
    return ci.hCursor, ci.ptScreenPos.x, ci.ptScreenPos.y, lb

r=[]
def cb(h,_):
    if win32gui.IsWindowVisible(h) and 'Lineage Classic' in win32gui.GetWindowText(h):r.append(h)
    return True
win32gui.EnumWindows(cb,None)
if not r: print("no game"); exit()
hwnd=r[0]
cr=win32gui.GetClientRect(hwnd);pt=ctypes.wintypes.POINT(0,0)
ctypes.windll.user32.ClientToScreen(hwnd,ctypes.byref(pt))
cx,cy,cw,ch=pt.x,pt.y,cr[2],cr[3]

sct = mss()

print("="*50)
print("  觀察模式 — 請正常打怪 120 秒")
print("  按 End 提前結束")
print(f"  視窗: {cw}x{ch} @ ({cx},{cy})")
print("="*50)
print()

records = []
start = time.time()
frame_idx = 0

while time.time() - start < 120:
    if keyboard.is_pressed('end'): break

    t = time.time() - start
    handle, mx, my, click = get_info()

    # 每 3 秒存截圖
    if frame_idx % 10 == 0:
        try:
            region = {'left':cx,'top':cy,'width':cw,'height':ch}
            shot = sct.grab(region)
            img = Image.frombytes('RGB',shot.size,shot.bgra,'raw','BGRX')
            img.save(os.path.join(SAVE_DIR, f"f_{frame_idx:04d}.png"))
        except: pass

    rec = {
        'time': round(t, 2),
        'frame': frame_idx,
        'mx': mx, 'my': my,
        'rx': mx - cx, 'ry': my - cy,
        'handle': handle,
        'click': click,
    }
    records.append(rec)

    # 顯示
    print(f"\r  [{t:5.1f}s] ({mx},{my}) h={handle} {'CLICK' if click else '     '} f#{frame_idx}", end="", flush=True)

    frame_idx += 1
    time.sleep(0.3)

# 儲存
log_path = os.path.join(SAVE_DIR, "observe_log.json")
with open(log_path, 'w') as f:
    json.dump(records, f, indent=2)

# 分析
handles = {}
clicks = 0
for rec in records:
    h = rec['handle']
    handles[h] = handles.get(h, 0) + 1
    if rec['click']: clicks += 1

print(f"\n\n記錄完成！{frame_idx} 幀")
print(f"游標統計:")
most = max(handles, key=handles.get)
for h, c in sorted(handles.items(), key=lambda x:-x[1]):
    label = "手指(空地)" if h == most else "其他(怪物/NPC?)"
    print(f"  {h}: {c} 次 → {label}")
print(f"點擊: {clicks} 次")

# 分析攻擊模式
print(f"\n攻擊模式分析:")
non_finger = [rec for rec in records if rec['handle'] != most]
if non_finger:
    print(f"  非手指游標出現 {len(non_finger)} 次")
    # 找連續的非手指序列（一次攻擊）
    attacks = []
    current = []
    for rec in records:
        if rec['handle'] != most:
            current.append(rec)
        else:
            if current:
                attacks.append(current)
                current = []
    if current: attacks.append(current)

    print(f"  攻擊序列: {len(attacks)} 次")
    for i, atk in enumerate(attacks[:10]):
        t0, t1 = atk[0]['time'], atk[-1]['time']
        x0, y0 = atk[0]['mx'], atk[0]['my']
        # 攻擊後滑鼠去哪
        last_frame = atk[-1]['frame']
        after = [r for r in records if r['frame'] > last_frame and r['handle'] == most]
        after_str = ""
        if after:
            dy = after[0]['my'] - y0
            after_str = f" → 之後 y{'+' if dy>0 else ''}{dy}px"
        print(f"  攻擊{i+1}: t={t0:.1f}-{t1:.1f}s ({x0},{y0}) 持續{t1-t0:.1f}s{after_str}")
