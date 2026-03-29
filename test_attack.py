"""
最簡測試：掃描找怪 → 嘗試 3 種攻擊方式
"""
import ctypes, ctypes.wintypes, time, random, math
ctypes.windll.shcore.SetProcessDpiAwareness(2)
import win32gui

CURSOR_SWORD = 54726367

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize",ctypes.c_uint),("flags",ctypes.c_uint),
                ("hCursor",ctypes.wintypes.HANDLE),("ptScreenPos",ctypes.wintypes.POINT)]

def get_cursor():
    ci=CURSORINFO();ci.cbSize=ctypes.sizeof(CURSORINFO)
    ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci));return ci.hCursor

hwnd = None
for h in range(0, 99999):
    try:
        r = []
        def cb(h, _):
            if win32gui.IsWindowVisible(h) and 'Lineage Classic' in win32gui.GetWindowText(h): r.append(h)
            return True
        win32gui.EnumWindows(cb, None)
        if r: hwnd = r[0]
        break
    except: pass

if not hwnd:
    print("找不到遊戲"); exit()

cr = win32gui.GetClientRect(hwnd)
pt = ctypes.wintypes.POINT(0,0)
ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
cx, cy, cw, ch = pt.x, pt.y, cr[2], cr[3]
sh = int(ch * 0.75)

print(f"視窗: {cw}x{ch} @ ({cx},{cy})")

# ── 掃描找怪 ──
print("\n掃描中...")
ctypes.windll.user32.SetForegroundWindow(hwnd)
time.sleep(0.3)

found = None
step = 50
for py in range(cy + 50, cy + sh - 50, step):
    for px in range(cx + 50, cx + cw - 50, step):
        ctypes.windll.user32.SetCursorPos(px, py)
        time.sleep(0.04)
        if get_cursor() == CURSOR_SWORD:
            found = (px, py)
            print(f"找到怪物！({px},{py})")
            break
    if found: break

if not found:
    print("找不到怪物"); exit()

mx, my = found

# ── 測試 3 種攻擊方式 ──
import mouse as mouse_lib
try:
    import interception
    interception.auto_capture_devices(mouse=True)
    has_int = True
except:
    has_int = False

methods = [
    "方式A: SetCursorPos移動 + mouse_lib.click",
    "方式B: SetCursorPos移動 + mouse_lib按住拖曳",
    "方式C: SetCursorPos移動 + interception click" if has_int else "方式C: 跳過(無interception)",
]

for idx, name in enumerate(methods):
    if '跳過' in name: continue

    # 重新找怪（可能死了或移走了）
    print(f"\n重新找怪...")
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    found = None
    for py in range(cy + 50, cy + sh - 50, step):
        for px in range(cx + 50, cx + cw - 50, step):
            ctypes.windll.user32.SetCursorPos(px, py)
            time.sleep(0.04)
            if get_cursor() == CURSOR_SWORD:
                found = (px, py)
                break
        if found: break
    if not found:
        print("找不到怪物，跳過"); continue
    mx, my = found
    print(f"怪物在 ({mx},{my})")

    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")

    # 確保在怪物位置
    ctypes.windll.user32.SetCursorPos(mx, my)
    time.sleep(0.2)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)

    half_y = my + (cy + sh - my) // 2  # 往下拖一半

    if idx == 0:
        # 方式A: mouse_lib 直接 click
        print("  click 1...")
        mouse_lib.click('left')
        time.sleep(0.3)
        print("  click 2...")
        mouse_lib.click('left')
        time.sleep(0.3)
        print("  click 3...")
        mouse_lib.click('left')

    elif idx == 1:
        # 方式B: mouse_lib 按住拖曳
        print("  按下...")
        mouse_lib.press('left')
        time.sleep(0.1)
        print("  拖曳往下...")
        for i in range(1, 8):
            iy = my + (half_y - my) * i // 7
            ctypes.windll.user32.SetCursorPos(mx, iy)
            time.sleep(0.03)
        time.sleep(0.1)
        print("  放開...")
        mouse_lib.release('left')

    elif idx == 2:
        # 方式C: interception
        print("  interception click 1...")
        interception.click()
        time.sleep(0.3)
        print("  interception click 2...")
        interception.click()
        time.sleep(0.3)
        print("  interception click 3...")
        interception.click()

    print("  等 5 秒觀察...")
    time.sleep(5)
    print("  角色有攻擊嗎？")

print("\n\n測試完成！哪種方式有效？")
print("  A = mouse_lib.click")
print("  B = mouse_lib 按住拖曳")
print("  C = interception click")
print("  0 = 都沒用")
