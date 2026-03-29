"""
純 Interception 驅動測試 — 移動+點擊全走驅動層
5 秒後自動找怪物並攻擊
"""
import ctypes, ctypes.wintypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)
import time, sys, random, math
sys.stdout.reconfigure(encoding='utf-8')
import win32gui
import interception

CURSOR_SWORD = 54726367

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize",ctypes.c_uint),("flags",ctypes.c_uint),
                ("hCursor",ctypes.wintypes.HANDLE),("ptScreenPos",ctypes.wintypes.POINT)]

def get_cursor():
    ci = CURSORINFO(); ci.cbSize = ctypes.sizeof(CURSORINFO)
    ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci))
    return ci.hCursor

def find_game():
    r = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and 'Lineage Classic' in win32gui.GetWindowText(h):
            r.append(h)
        return True
    win32gui.EnumWindows(cb, None)
    return r[0] if r else None

hwnd = find_game()
if not hwnd:
    print("找不到遊戲"); sys.exit()

cr = win32gui.GetClientRect(hwnd)
pt = ctypes.wintypes.POINT(0,0)
ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
cx, cy, cw, ch = pt.x, pt.y, cr[2], cr[3]
sh = int(ch * 0.75)

print(f"視窗: {cw}x{ch} @ ({cx},{cy})")
print(f"Interception 驅動: 已載入")
print()

# 初始化 interception
interception.auto_capture_devices(mouse=True)

# 掃描找怪物 — 全部用 interception.move_to
print("掃描中（純 interception 移動）...")
ctypes.windll.user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

found = None
step = 70
for py in range(cy + int(sh*0.1), cy + sh - 30, step):
    for px in range(cx + int(cw*0.1), cx + cw - int(cw*0.1), step):
        interception.move_to(px, py)  # 驅動層移動
        time.sleep(0.06)
        if get_cursor() == CURSOR_SWORD:
            found = (px, py)
            print(f"找到怪物！({px},{py})")
            break
    if found:
        break

if not found:
    print("找不到怪物")
    sys.exit()

mx, my = found

# 攻擊 — 全部用 interception
print(f"\n攻擊怪物 ({mx},{my})...")
print("  1. interception.move_to 移到怪物")
interception.move_to(mx, my)
time.sleep(0.2)

print("  2. interception.mouse_down 按下")
interception.mouse_down('left')
time.sleep(0.15)

print("  3. interception.move_to 拖曳")
angle = random.uniform(0, 2*math.pi)
dist = random.randint(30, 60)
dx = mx + int(dist * math.cos(angle))
dy = my + int(dist * math.sin(angle))
dx = max(cx+10, min(cx+cw-10, dx))
dy = max(cy+10, min(cy+ch-10, dy))

for i in range(1, 8):
    ix = mx + (dx-mx)*i//7
    iy = my + (dy-my)*i//7
    interception.move_to(ix, iy)
    time.sleep(0.03)

time.sleep(0.2)
print("  4. interception.mouse_up 放開")
interception.mouse_up('left')

print("\n等 5 秒觀察角色是否攻擊...")
time.sleep(5)
print("測試完成！角色有攻擊嗎？")
