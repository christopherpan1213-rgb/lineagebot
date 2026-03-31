"""
天堂經典版 Bot v10 — 核心引擎重構版
全 Interception 驅動 + OpenCV 怪物偵測 + DXcam 高速截圖 + 狀態機架構
"""
BOT_VERSION = "10.6"
GITHUB_REPO = "christopherpan1213-rgb/lineagebot"
UPDATE_BRANCH = "main"
import ctypes, ctypes.wintypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import time, sys, os, math, random, threading, json, winsound
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass
import numpy as np
from PIL import Image
import cv2
import keyboard
import mouse as mouse_lib
import win32gui
import tkinter as tk
from tkinter import ttk, filedialog

# 截圖引擎：優先 DXcam，fallback MSS
try:
    import dxcam
    _dxcam = dxcam.create(output_color="BGR")
    HAS_DXCAM = True
except:
    from mss import mss
    HAS_DXCAM = False

# 輸入引擎：優先 Interception
try:
    import interception; interception.auto_capture_devices(mouse=True); HAS_INTERCEPTION = True
except: HAS_INTERCEPTION = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'bot_config.json')
SS_DIR = os.path.join(SCRIPT_DIR, 'bot_screenshots')
os.makedirs(SS_DIR, exist_ok=True)

try:
    sys.path.insert(0, SCRIPT_DIR)
    from lineage_data import MONSTER_NAMES, MONSTERS, LEVELING_GUIDE, VILLAGES, DUNGEONS, POTIONS, TELEPORTERS
except:
    MONSTER_NAMES = set(); MONSTERS = []; LEVELING_GUIDE = []; VILLAGES = {}; DUNGEONS = {}; POTIONS = {}; TELEPORTERS = {}

# ═══════════════════════════════ WinAPI ═══════════════════════════════

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize",ctypes.c_uint),("flags",ctypes.c_uint),("hCursor",ctypes.wintypes.HANDLE),("ptScreenPos",ctypes.wintypes.POINT)]
INPUT_KEYBOARD=1; KEYEVENTF_SCANCODE=0x0008; KEYEVENTF_KEYUP=0x0002
VK={f'F{i}':0x6F+i for i in range(1,13)}
class KEYBDINPUT(ctypes.Structure):
    _fields_=[("wVk",ctypes.c_ushort),("wScan",ctypes.c_ushort),("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
class INPUT_UNION(ctypes.Union):
    _fields_=[("ki",KEYBDINPUT)]
class INPUT(ctypes.Structure):
    _fields_=[("type",ctypes.c_ulong),("_input",INPUT_UNION)]

def get_cursor():
    ci=CURSORINFO();ci.cbSize=ctypes.sizeof(CURSORINFO)
    ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci));return ci.hCursor

# ═══════════════════════════════ 截圖引擎 ═══════════════════════════════

def grab_region(left, top, width, height):
    """高速截圖（DXcam 優先，fallback MSS）回傳 BGR numpy array"""
    # 裁剪到螢幕範圍內
    scr_w = ctypes.windll.user32.GetSystemMetrics(0)
    scr_h = ctypes.windll.user32.GetSystemMetrics(1)
    left = max(0, left)
    top = max(0, top)
    width = min(width, scr_w - left)
    height = min(height, scr_h - top)
    if width <= 0 or height <= 0:
        return np.zeros((10, 10, 3), dtype=np.uint8)

    if HAS_DXCAM:
        try:
            frame = _dxcam.grab(region=(left, top, left+width, top+height))
            if frame is not None:
                return frame
        except:
            pass
    # fallback MSS
    from mss import mss as _mss
    sct = _mss()
    shot = sct.grab({'left':left,'top':top,'width':width,'height':height})
    return np.array(Image.frombytes('RGB',shot.size,shot.bgra,'raw','BGRX'))[:,:,::-1]

def grab_scene(cx, cy, cw, ch):
    """截取遊戲場景區域（排除底部 UI）"""
    sh = int(ch * 0.75)
    return grab_region(cx, cy, cw, sh), sh

# ═══════════════════════════════ 輸入引擎（全 Interception）═══════════════════════════════

INPUT_MODE = 'auto'  # auto / interception / setcursorpos / mouse_lib

def _detect_input_mode(hwnd):
    """自動偵測哪種輸入方式遊戲接受"""
    global INPUT_MODE
    if INPUT_MODE != 'auto':
        return

    cx, cy, cw, ch = get_rect(hwnd)
    test_x, test_y = cx + cw // 2, cy + int(ch * 0.3)

    # 測試 interception
    if HAS_INTERCEPTION:
        try:
            interception.move_to(test_x, test_y)
            time.sleep(0.1)
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            if abs(pt.x - test_x) < 5 and abs(pt.y - test_y) < 5:
                INPUT_MODE = 'interception'
                return
        except: pass

    # 測試 SetCursorPos
    ctypes.windll.user32.SetCursorPos(test_x + 50, test_y + 50)
    time.sleep(0.1)
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    if abs(pt.x - (test_x + 50)) < 5 and abs(pt.y - (test_y + 50)) < 5:
        INPUT_MODE = 'setcursorpos'
        return

    INPUT_MODE = 'mouse_lib'

def move_mouse(x, y):
    jx, jy = x + random.randint(-1,1), y + random.randint(-1,1)
    if INPUT_MODE == 'interception' and HAS_INTERCEPTION:
        try: interception.move_to(jx, jy); return
        except: pass
    ctypes.windll.user32.SetCursorPos(jx, jy)

def move_exact(x, y):
    if INPUT_MODE == 'interception' and HAS_INTERCEPTION:
        try: interception.move_to(x, y); return
        except: pass
    ctypes.windll.user32.SetCursorPos(x, y)

def press_key_raw(key):
    """按一般按鍵（非 F 鍵）"""
    keyboard.press(key)
    time.sleep(0.05)
    keyboard.release(key)

def game_click(x=None, y=None):
    """統一點擊：移動 → 等待 → 按下 → 等待 → 放開"""
    if x is not None:
        move_exact(x, y)
        time.sleep(0.08)  # 關鍵：讓遊戲處理移動事件
    if HAS_INTERCEPTION:
        try:
            interception.mouse_down('left')
            time.sleep(random.uniform(0.04, 0.08))
            interception.mouse_up('left')
            time.sleep(0.05)
            return
        except: pass
    mouse_lib.click('left')

def game_down():
    if HAS_INTERCEPTION:
        try: interception.mouse_down('left'); time.sleep(0.05); return
        except: pass
    mouse_lib.press('left')

def game_up():
    if HAS_INTERCEPTION:
        try: interception.mouse_up('left'); time.sleep(0.05); return
        except: pass
    mouse_lib.release('left')

def press_key(key):
    vk=VK.get(key.upper())
    if not vk: return
    sc=ctypes.windll.user32.MapVirtualKeyW(vk,0); inp=INPUT();inp.type=INPUT_KEYBOARD
    inp._input.ki.wScan=sc;inp._input.ki.dwFlags=KEYEVENTF_SCANCODE
    inp._input.ki.dwExtraInfo=ctypes.pointer(ctypes.c_ulong(0))
    ctypes.windll.user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(inp))
    time.sleep(0.05+random.uniform(0,0.02))
    inp._input.ki.dwFlags=KEYEVENTF_SCANCODE|KEYEVENTF_KEYUP
    ctypes.windll.user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(inp))

def alert(t):
    fs={'pk':(1500,300),'dc':(800,500),'death':(400,800),'hp':(1000,200),'stuck':(600,300)}
    f,d=fs.get(t,(1000,200)); threading.Thread(target=lambda:winsound.Beep(f,d),daemon=True).start()

CURSOR_FINGER = None  # 啟動時自動偵測（出現最多次的 = 手指）
# 已知的手指 handle（會變，但記錄歷史值做 fallback）
KNOWN_FINGERS = {200549, 267784417, 183307458, 1119414}
FKEYS=[f'F{i}' for i in range(1,13)]
CLASSES=['騎士','法師','妖精','王族','黑暗妖精','龍騎士','幻術師']
CLASS_PRESETS={
    '騎士':{'mode':'近戰','hp_thr':60,'mp_thr':20,'heal':True,'heal_thr':50},
    '法師':{'mode':'遠程','hp_thr':70,'mp_thr':40,'heal':True,'heal_thr':60},
    '妖精':{'mode':'遠程','hp_thr':60,'mp_thr':30,'heal':True,'heal_thr':50},
    '王族':{'mode':'近戰','hp_thr':60,'mp_thr':30,'heal':False,'heal_thr':50},
    '黑暗妖精':{'mode':'近戰','hp_thr':50,'mp_thr':20,'heal':False,'heal_thr':40},
    '龍騎士':{'mode':'近戰','hp_thr':55,'mp_thr':25,'heal':False,'heal_thr':45},
    '幻術師':{'mode':'召喚','hp_thr':65,'mp_thr':40,'heal':True,'heal_thr':55},
}

# ═══════════════════════════════ 遊戲視窗 ═══════════════════════════════

def find_game():
    r=[]
    def cb(h,_):
        if win32gui.IsWindowVisible(h) and 'Lineage Classic' in win32gui.GetWindowText(h): r.append((h,win32gui.GetWindowText(h)))
        return True
    win32gui.EnumWindows(cb,None); return r[0] if r else None

def get_rect(h):
    cr=win32gui.GetClientRect(h);pt=ctypes.wintypes.POINT(0,0);ctypes.windll.user32.ClientToScreen(h,ctypes.byref(pt))
    return pt.x,pt.y,cr[2],cr[3]

# ═══════════════════════════════ HP/MP ═══════════════════════════════

class BarReader:
    """HP/MP 條讀取 — 用相對比例定位，不需要校準"""
    def __init__(self):
        self.ok = True
    def _read(self, cx, cy, cw, ch, y_pct, xs_pct, xe_pct):
        try:
            by = int(ch * y_pct)
            bxs = int(cw * xs_pct)
            bw = int(cw * (xe_pct - xs_pct))
            if bw < 10: return -1
            strip = grab_region(cx + bxs, cy + by - 1, bw, 3)
            bright = strip.max(axis=2).mean(axis=0)
            filled = bright > 120
            if not filled.any(): return 0.0
            return min(1.0, (np.max(np.where(filled)) + 1) / len(bright))
        except: return -1
    def hp(self, sct, cx, cy, cw, ch):
        return self._read(cx, cy, cw, ch, 0.792, 0.30, 0.45)
    def mp(self, sct, cx, cy, cw, ch):
        return self._read(cx, cy, cw, ch, 0.792, 0.55, 0.70)
    def calibrate(self, sct, cx, cy, cw, ch):
        return True

bars = BarReader()

# ═══════════════════════════════ 怪物偵測 ═══════════════════════════════

def detect_monster_names(cx, cy, cw, ch):
    """
    用 OpenCV 偵測怪物名字（白字無背景框）
    過濾玩家名字（白字有深色背景框）
    回傳螢幕絕對座標列表 [(x, y), ...]
    """
    frame, sh = grab_scene(cx, cy, cw, ch)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Step 1: 高閾值二值化找白色文字 (>=252)
    _, white_mask = cv2.threshold(gray, 248, 255, cv2.THRESH_BINARY)

    # 排除角色中心和邊緣
    ccx, ccy = cw // 2, sh // 2
    cv2.circle(white_mask, (ccx, ccy), 80, 0, -1)
    white_mask[:15, :] = 0
    white_mask[:, :25] = 0
    white_mask[:, -25:] = 0

    # Step 2: 形態學操作 — 將文字字元連接成名字區塊
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 5))
    closed = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)

    # Step 3: 找輪廓
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        # 過濾尺寸 — 名字通常寬 30-250px，高 5-25px
        if w < 25 or w > 300 or h < 4 or h > 30:
            continue

        # Step 4: 背景分析 — 區分怪物(無背景框) vs 玩家(有深色背景框)
        pad = 5
        bg_y1 = max(0, y - pad)
        bg_y2 = min(sh, y + h + pad)
        bg_x1 = max(0, x - pad)
        bg_x2 = min(cw, x + w + pad)

        bg_region = gray[bg_y1:bg_y2, bg_x1:bg_x2].copy()
        text_mask = white_mask[bg_y1:bg_y2, bg_x1:bg_x2]
        bg_pixels = bg_region[text_mask == 0]  # 只看非文字像素

        if len(bg_pixels) < 10:
            continue

        avg_bg = float(np.mean(bg_pixels))
        std_bg = float(np.std(bg_pixels))

        # 玩家名字：深色均勻背景 (avg < 80, std < 30)
        # 怪物名字：遊戲場景背景，顏色多變 (std > 30 或 avg > 80)
        if avg_bg < 80 and std_bg < 30:
            continue  # 這是玩家名字，跳過

        # 通過過濾 = 可能是怪物名字
        abs_x = cx + x + w // 2
        abs_y = cy + y + h // 2
        candidates.append((abs_x, abs_y, w * h))  # 面積做排序

    # 按面積大到小排序，去重
    candidates.sort(key=lambda c: -c[2])
    filtered = []
    for x, y, a in candidates:
        if not any(abs(x-fx) < 60 and abs(y-fy) < 60 for fx, fy, _ in filtered):
            filtered.append((x, y, a))

    return [(x, y) for x, y, _ in filtered[:10]]


def scan_and_attack(cx, cy, cw, ch, hwnd, log=None, exclude=None, mode='近戰'):
    """掃描+攻擊一體化
    近戰：標準範圍、標準速度
    遠程：2倍範圍、更快掃描速度
    """
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.03)

    sh = int(ch * 0.75)
    margin = int(cw * 0.04)
    center_x = cx + cw // 2
    center_y = cy + sh // 2

    # 步距依視窗大小縮放（以 860px 寬為基準）
    scale = min(cw, sh) / 860

    if mode in ('遠程', '定點'):
        step = max(30, int(75 * scale))
        max_radius = min(cw, sh) * 2 // 3
        scan_delay = 0.01   # 10ms — 太快遊戲來不及更新游標
    else:
        step = max(25, int(65 * scale))
        max_radius = min(cw, sh) // 3
        scan_delay = 0.015  # 15ms

    start_angle = random.uniform(0, 2 * math.pi)
    count = 0

    # 全圈螺旋掃描（360°）
    for radius in range(step, max_radius, step):
        n_points = max(6, int(2 * math.pi * radius / step))
        for i in range(n_points):
            angle = start_angle + 2 * math.pi * i / n_points
            px = int(center_x + radius * math.cos(angle))
            py = int(center_y + radius * math.sin(angle))

            if not (cx + margin < px < cx + cw - margin and cy + margin < py < cy + sh - margin):
                continue
            if exclude and abs(px - exclude[0]) < 80 and abs(py - exclude[1]) < 80:
                continue

            move_exact(px, py)
            time.sleep(scan_delay)
            count += 1

            if get_cursor() != CURSOR_FINGER:
                # 找到怪物！
                if log:
                    log(f"掃{count}點→打！({px},{py})")

                # 按下+拖曳攻擊
                time.sleep(0.05)  # 讓遊戲確認游標在怪物上
                game_down()
                time.sleep(0.08)  # 等遊戲註冊按下事件

                # 所有模式統一拖曳距離（150-300px），天堂需要拖夠遠才觸發攻擊
                drag_dist = random.randint(150, 300)
                drag_x = px + random.randint(-15, 15)
                drag_y = min(cy + sh - 20, py + drag_dist)

                steps = 5
                for s in range(1, steps + 1):
                    move_exact(
                        px + (drag_x - px) * s // steps,
                        py + (drag_y - py) * s // steps)
                    time.sleep(0.02)

                time.sleep(0.05)
                game_up()

                return (px, py)

    if log and count > 0:
        log(f"掃{count}點 無怪")
    return None


def detect_monster_hp_bar(cx, cy, cw, ch, monster_x, monster_y):
    """偵測怪物頭上的紅色 HP 條是否存在
    怪物被攻擊時頭上會出現紅色 HP 條
    回傳 True = HP 條還在（怪物還活著）
    """
    # 怪物 HP 條通常在怪物名字附近（上方）
    # 截取怪物上方小區域
    rel_x = monster_x - cx
    rel_y = monster_y - cy
    roi_x = max(0, rel_x - 40)
    roi_y = max(0, rel_y - 60)
    roi_w = 80
    roi_h = 30

    try:
        frame = grab_region(cx + roi_x, cy + roi_y, roi_w, roi_h)
        # 怪物 HP 條 = 紅色小條 (R>150, G<80, B<80)
        r, g, b = frame[:,:,2], frame[:,:,1], frame[:,:,0]  # BGR
        red_mask = (r > 150) & (g < 80) & (b < 80)
        red_ratio = red_mask.sum() / (roi_w * roi_h)
        return red_ratio > 0.02  # 超過 2% 紅色像素 = HP 條還在
    except:
        return True  # 錯誤時假設還活著


class PreScanner:
    """背景預掃描：戰鬥中不掃描（掃描會搶滑鼠），只在死亡後快速掃"""
    def __init__(self):
        self.next_target = None

    def start(self, *args, **kwargs):
        # 戰鬥中不做預掃描，因為掃描要移動滑鼠會干擾戰鬥
        self.next_target = None

    def stop(self):
        pass

    def get(self):
        return self.next_target

pre_scanner = PreScanner()

def attack(mx, my, cx, cy, cw, ch):
    """全 interception 攻擊：移到怪物→按下→往下拖一半→放開
    SetCursorPos 被遊戲擋住，必須全部用 interception
    """
    sh = int(ch * 0.75)
    bottom_y = cy + sh
    half_y = my + (bottom_y - my) // 2
    drag_x = mx + random.randint(-30, 30)
    drag_y = half_y + random.randint(-20, 20)

    # 1. 移到怪物位置（interception）
    move_exact(mx, my)
    time.sleep(0.1)

    # 2. 按下左鍵
    game_down()
    time.sleep(0.08)

    # 3. 往下拖一半距離（interception）
    steps = random.randint(4, 6)
    for i in range(1, steps + 1):
        ix = mx + (drag_x - mx) * i // steps
        iy = my + (drag_y - my) * i // steps
        move_exact(ix, iy)
        time.sleep(random.uniform(0.015, 0.025))

    time.sleep(0.05)

    # 4. 放開
    game_up()

def scan_loot(cx, cy, cw, ch, hwnd):
    sh = int(ch * 0.75)
    ccx, ccy = cx + cw // 2, cy + sh // 2
    for r in range(40, 150, 40):
        for i in range(8):
            a = 2 * math.pi * i / 8
            px, py = ccx + int(r * math.cos(a)), ccy + int(r * math.sin(a))
            move_exact(px, py)  # interception
            time.sleep(0.06)
            h = get_cursor()
            if h != CURSOR_FINGER:
                game_click()  # interception click at current pos
                time.sleep(0.3)
                return True
    return False

def roam(cx, cy, cw, ch, hwnd, dist):
    sh = int(ch * 0.75)
    a = random.uniform(0, 2 * math.pi)
    d = random.randint(100, dist)
    tx = max(cx+50, min(cx+cw-50, cx+cw//2+int(d*math.cos(a))))
    ty = max(cy+30, min(cy+sh-30, cy+sh//2+int(d*math.sin(a))))
    move_exact(tx, ty)  # interception
    time.sleep(0.08)
    if get_cursor() != CURSOR_FINGER:
        return (tx, ty)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    game_click(tx, ty)  # 帶座標點擊確保位置正確
    time.sleep(1.5 + random.uniform(0, 0.3))
    return None

# ═══════════════════════════════ 技能系統 ═══════════════════════════════

class SkillSystem:
    def __init__(self): self.skills=[];self.last={}
    def setup(self,sl): self.skills=[(k,cd) for k,cd in sl if k!='無'];self.last={k:0 for k,_ in self.skills}
    def use_next(self):
        now=time.time()
        for k,cd in self.skills:
            if now-self.last.get(k,0)>=cd: press_key(k);self.last[k]=now;return k
        return None

skills=SkillSystem()

# ═══════════════════════════════ 路徑 ═══════════════════════════════

class PathRec:
    def __init__(self):self.pts=[];self.rec=False
    def start(self):self.pts=[];self.rec=True
    def add(self,cx,cy,cw,ch):
        if not self.rec:return
        p=ctypes.wintypes.POINT();ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        self.pts.append(((p.x-cx)/cw,(p.y-cy)/ch,time.time()))
    def stop(self):self.rec=False;return len(self.pts)
    def play(self,cx,cy,cw,ch,hwnd):
        if not self.pts:return
        ctypes.windll.user32.SetForegroundWindow(hwnd);time.sleep(0.2)
        for i,(rx,ry,t) in enumerate(self.pts):
            move_exact(cx+int(rx*cw),cy+int(ry*ch));game_click()
            if i<len(self.pts)-1:time.sleep(max(0.3,min(2,self.pts[i+1][2]-t)))
    def save(self,fp):
        with open(fp,'w') as f:json.dump([{'x':p[0],'y':p[1],'t':p[2]} for p in self.pts],f)
    def load(self,fp):
        with open(fp) as f:d=json.load(f)
        self.pts=[(i['x'],i['y'],i['t']) for i in d]

path=PathRec()

# ═══════════════════════════════ 設定儲存 ═══════════════════════════════

def save_cfg(gui):
    c={}
    for a in dir(gui):
        if a.startswith('var_'):
            v=getattr(gui,a)
            if isinstance(v,(tk.BooleanVar,tk.StringVar,tk.IntVar,tk.DoubleVar)):c[a]=v.get()
            elif isinstance(v,list) and v and isinstance(v[0],(tk.StringVar,tk.DoubleVar)):
                c[a]=[x.get() for x in v]
    # 怪物黑名單
    c['monster_blacklist']=gui.monster_blacklist
    with open(CONFIG_FILE,'w') as f:json.dump(c,f,indent=2,ensure_ascii=False)

def load_cfg(gui):
    if not os.path.exists(CONFIG_FILE):return
    try:
        with open(CONFIG_FILE) as f:c=json.load(f)
        for a,v in c.items():
            if a=='monster_blacklist':gui.monster_blacklist=v;continue
            if hasattr(gui,a):
                obj=getattr(gui,a)
                if isinstance(obj,list) and isinstance(v,list):
                    for i,val in enumerate(v):
                        if i<len(obj):obj[i].set(val)
                elif isinstance(obj,(tk.BooleanVar,tk.StringVar,tk.IntVar,tk.DoubleVar)):
                    try:obj.set(v)
                    except:pass
    except:pass

# ═══════════════════════════════ 回城補給方案 ═══════════════════════════════

SUPPLY_PRESETS = {
    '紅水100個': {'item': '紅色藥水', 'count': 100, 'key': 'F5'},
    '橙水50個': {'item': '橙色藥水', 'count': 50, 'key': 'F5'},
    '藍水50個': {'item': '藍色藥水', 'count': 50, 'key': 'F6'},
    '綠水10個': {'item': '綠色藥水', 'count': 10, 'key': 'F8'},
    '回城卷5個': {'item': '傳送回家的卷軸', 'count': 5, 'key': 'F12'},
}

# ═══════════════════════════════ GUI ═══════════════════════════════

BG1='#0f0f1a'; BG2='#16213e'; BG3='#1a1a2e'; FG='#c0c0c0'; ACC='#e94560'; ACC2='#0f3460'
FONT=('Microsoft JhengHei',9); FONTS=('Microsoft JhengHei',8); FONTM=('Consolas',8)

class BotApp:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title("天堂經典版 Bot v8")
        self.root.geometry("680x620")
        self.root.configure(bg=BG1)
        self.root.attributes('-topmost',True)
        self.root.protocol("WM_DELETE_WINDOW",self._close)

        self.running=False; self.thread=None; self.t0=None
        self.kills=self.pots=self.mpots=self.heals=self.buffs=self.loots=0
        self.monster_blacklist=[]

        # ── 變數 ──
        self.var_class=tk.StringVar(value='騎士')
        self.var_mode=tk.StringVar(value='近戰')
        self.var_map=tk.StringVar(value='墮落的祝福之地')

        self.var_attack=tk.BooleanVar(value=True)
        self.var_roam=tk.BooleanVar(value=True)
        self.var_loot=tk.BooleanVar(value=False)
        self.var_hp_en=tk.BooleanVar(value=True)
        self.var_mp_en=tk.BooleanVar(value=False)
        self.var_heal_en=tk.BooleanVar(value=True)
        self.var_buff_en=tk.BooleanVar(value=True)
        self.var_recall_en=tk.BooleanVar(value=False)
        self.var_antipk=tk.BooleanVar(value=False)
        self.var_dc_detect=tk.BooleanVar(value=True)
        self.var_humanize=tk.BooleanVar(value=True)
        self.var_sslog=tk.BooleanVar(value=False)
        self.var_path_en=tk.BooleanVar(value=False)

        self.var_hp_key=tk.StringVar(value='F5')
        self.var_hp_thr=tk.IntVar(value=60)
        self.var_mp_key=tk.StringVar(value='F6')
        self.var_mp_thr=tk.IntVar(value=30)
        self.var_heal_key=tk.StringVar(value='F7')
        self.var_heal_thr=tk.IntVar(value=50)
        self.var_heal_n=tk.IntVar(value=3)
        self.var_buff_key=tk.StringVar(value='F6')
        self.var_buff_sec=tk.IntVar(value=300)
        self.var_recall_key=tk.StringVar(value='F12')
        self.var_recall_thr=tk.IntVar(value=15)
        self.var_roam_dist=tk.IntVar(value=200)
        self.var_stuck=tk.IntVar(value=20)
        self.var_pk_act=tk.StringVar(value='回城')
        self.var_hotkey=tk.StringVar(value='left windows')

        # 遠程
        self.var_rng_key=tk.StringVar(value='F1')
        self.var_rng_dist=tk.IntVar(value=150)
        self.var_rng_kite=tk.BooleanVar(value=True)
        # 召喚
        self.var_sum_key=tk.StringVar(value='F1')
        self.var_sum_atk=tk.StringVar(value='F2')
        self.var_sum_sec=tk.IntVar(value=1800)
        # 隊伍
        self.var_pt_role=tk.StringVar(value='輸出')
        self.var_pt_heal=tk.StringVar(value='F7')
        self.var_pt_buff=tk.StringVar(value='F8')

        # 技能 (7格)
        self.var_sk=[tk.StringVar(value='無') for _ in range(7)]
        self.var_cd=[tk.DoubleVar(value=3.0) for _ in range(7)]

        # 定時按鍵 (4組)
        self.var_timer_en=[tk.BooleanVar(value=False) for _ in range(4)]
        self.var_timer_key=[tk.StringVar(value='無') for _ in range(4)]
        self.var_timer_sec=[tk.DoubleVar(value=10.0) for _ in range(4)]
        self.var_timer_cnt=[tk.IntVar(value=1) for _ in range(4)]

        # 回城補給方案 (3套)
        self.var_supply=[tk.StringVar(value='紅水100個') for _ in range(3)]

        self._build()
        load_cfg(self)
        self._bind_hotkey()

    def _bind_hotkey(self):
        try:keyboard.remove_all_hotkeys()
        except:pass
        key = self.var_hotkey.get()
        # Windows 鍵在 keyboard 庫中的名稱
        if key == 'left windows':
            keyboard.on_press_key(0x5B, lambda e: self.root.after(0, self._toggle), suppress=False)
        elif key == 'right windows':
            keyboard.on_press_key(0x5C, lambda e: self.root.after(0, self._toggle), suppress=False)
        else:
            keyboard.add_hotkey(key, lambda: self.root.after(0, self._toggle))

    def _close(self):
        save_cfg(self);self.running=False;self.root.destroy()

    def _build(self):
        # ═══ 左側導航 ═══
        nav=tk.Frame(self.root,bg=BG1,width=130)
        nav.pack(side='left',fill='y')
        nav.pack_propagate(False)

        tk.Label(nav,text="天堂Bot v8",bg=BG1,fg=ACC,font=('Microsoft JhengHei',12,'bold')).pack(pady=(10,15))

        self.pages={}
        self.nav_btns={}
        page_names=['狀態','戰鬥','生存','技能','安全','模式','路徑','百科']
        self.content=tk.Frame(self.root,bg=BG2)
        self.content.pack(side='right',fill='both',expand=True)

        for name in page_names:
            btn=tk.Button(nav,text=name,font=FONTS,bg=BG1,fg=FG,activebackground=ACC2,
                          activeforeground='white',relief='flat',anchor='w',padx=15,
                          command=lambda n=name:self._show_page(n))
            btn.pack(fill='x',pady=1)
            self.nav_btns[name]=btn
            page=tk.Frame(self.content,bg=BG2)
            self.pages[name]=page

        # 啟動按鈕在導航底部
        tk.Frame(nav,bg=BG1).pack(fill='both',expand=True)
        self.start_btn=tk.Button(nav,text="▶ 啟動",font=('Microsoft JhengHei',10,'bold'),
                                 bg='#27ae60',fg='white',relief='flat',command=self._toggle)
        self.start_btn.pack(fill='x',padx=8,pady=(0,10),ipady=4)

        self._build_status()
        self._build_combat()
        self._build_survival()
        self._build_skills()
        self._build_safety()
        self._build_mode()
        self._build_path()
        self._build_wiki()
        self._show_page('狀態')

    def _show_page(self,name):
        for n,p in self.pages.items():p.pack_forget()
        self.pages[name].pack(fill='both',expand=True)
        for n,b in self.nav_btns.items():
            b.config(bg=ACC2 if n==name else BG1,fg='white' if n==name else FG)

    def _lbl(self,p,t,**kw):return tk.Label(p,text=t,bg=BG2,fg=FG,font=FONTS,**kw)
    def _chk(self,p,t,v):return tk.Checkbutton(p,text=t,variable=v,bg=BG2,fg=FG,selectcolor=BG1,activebackground=BG2,font=FONTS)
    def _combo(self,p,v,vals,w=4):c=ttk.Combobox(p,textvariable=v,values=vals,width=w,state='readonly',font=FONTM);return c
    def _spin(self,p,v,fr,to,w=4,inc=1):return tk.Spinbox(p,textvariable=v,from_=fr,to=to,increment=inc,width=w,font=FONTM,bg=BG3,fg=FG)
    def _frame(self,p):f=tk.Frame(p,bg=BG2);return f
    def _section(self,p,t):
        f=tk.LabelFrame(p,text=t,bg=BG2,fg=ACC,font=('Microsoft JhengHei',9,'bold'),padx=6,pady=4)
        return f

    # ═══ 狀態頁 ═══
    def _build_status(self):
        p=self.pages['狀態']

        # 職業+地圖選擇
        f=self._frame(p);f.pack(fill='x',padx=10,pady=(10,5))
        self._lbl(f,"職業:").pack(side='left')
        c=self._combo(f,self.var_class,CLASSES,w=8);c.pack(side='left',padx=2)
        c.bind('<<ComboboxSelected>>',lambda e:self._on_class_change())
        self._lbl(f,"地圖:").pack(side='left',padx=(10,0))
        maps=list(VILLAGES.keys())+list(DUNGEONS.keys())
        if not maps:maps=['墮落的祝福之地','說話之島','象牙塔','遺忘之島']
        self._combo(f,self.var_map,maps,w=14).pack(side='left',padx=2)

        # HP/MP 條
        bar_f=self._frame(p);bar_f.pack(fill='x',padx=10,pady=5)
        for lbl,clr in [("HP",ACC),("MP","#3498db")]:
            tk.Label(bar_f,text=lbl,bg=BG2,fg=clr,font=('Consolas',10,'bold')).pack(side='left')
            cv=tk.Canvas(bar_f,width=120,height=16,bg='#222',highlightthickness=0);cv.pack(side='left',padx=3)
            tl=tk.Label(bar_f,text="100%",bg=BG2,fg='#eee',font=('Consolas',9));tl.pack(side='left',padx=(0,10))
            if lbl=="HP":self.hp_cv,self.hp_tl=cv,tl
            else:self.mp_cv,self.mp_tl=cv,tl

        # 統計
        self.stat_lbl=tk.Label(p,text="殺:0 紅:0 藍:0 治:0 B:0 撿:0",bg=BG2,fg='#888',font=FONTM)
        self.stat_lbl.pack(pady=2)
        self.time_lbl=tk.Label(p,text="00:00:00 | 0.0 殺/時",bg=BG2,fg='#555',font=FONTM)
        self.time_lbl.pack()
        self.status_lbl=tk.Label(p,text="已停止",bg=BG2,fg='#aaa',font=('Microsoft JhengHei',11,'bold'))
        self.status_lbl.pack(pady=5)

        # 系統資訊
        info=f"點擊:{'interception' if HAS_INTERCEPTION else 'mouse_lib'} | 怪物庫:{len(MONSTER_NAMES)}隻"
        tk.Label(p,text=info,bg=BG2,fg='#27ae60' if HAS_INTERCEPTION else '#f5a623',font=('Consolas',7)).pack()

        # 日誌
        sf=self._section(p,"日誌");sf.pack(fill='both',padx=10,pady=(5,10),expand=True)
        self.log_w=tk.Text(sf,height=8,bg='#0d1117',fg='#58a6ff',font=('Consolas',8),state='disabled',wrap='word')
        self.log_w.pack(fill='both',expand=True)

    # ═══ 戰鬥頁 ═══
    def _build_combat(self):
        p=self.pages['戰鬥']
        sf=self._section(p,"自動打怪");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"啟用",self.var_attack).pack(side='left')
        self._chk(r,"漫遊",self.var_roam).pack(side='left',padx=8)
        self._chk(r,"撿物",self.var_loot).pack(side='left',padx=8)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._lbl(r,"漫遊距離:").pack(side='left')
        self._spin(r,self.var_roam_dist,50,500,w=4,inc=50).pack(side='left')
        self._lbl(r,"px").pack(side='left')
        self._lbl(r,"  卡怪超時:").pack(side='left')
        self._spin(r,self.var_stuck,10,60,w=3).pack(side='left')
        self._lbl(r,"秒").pack(side='left')

        # 怪物黑名單
        sf2=self._section(p,"怪物黑名單（不攻擊）");sf2.pack(fill='x',padx=10,pady=5)
        self.bl_text=tk.Label(sf2,text="目前: 無",bg=BG2,fg=FG,font=FONTS,wraplength=400,justify='left')
        self.bl_text.pack(fill='x',pady=2)
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self.bl_entry=tk.Entry(r,font=FONTM,width=20,bg=BG3,fg=FG)
        self.bl_entry.pack(side='left')
        tk.Button(r,text="加入",font=FONTS,bg=ACC2,fg='white',command=self._add_bl).pack(side='left',padx=3)
        tk.Button(r,text="清除全部",font=FONTS,bg='#555',fg='white',command=self._clear_bl).pack(side='left',padx=3)

    def _add_bl(self):
        n=self.bl_entry.get().strip()
        if n and n not in self.monster_blacklist:
            self.monster_blacklist.append(n)
            self.bl_text.config(text=f"目前: {', '.join(self.monster_blacklist)}")
            self.bl_entry.delete(0,'end')

    def _clear_bl(self):
        self.monster_blacklist=[]
        self.bl_text.config(text="目前: 無")

    # ═══ 生存頁 ═══
    def _build_survival(self):
        p=self.pages['生存']
        def mkrow(label,en,key,thr,extra=None):
            sf=self._section(p,label);sf.pack(fill='x',padx=10,pady=3)
            r=self._frame(sf);r.pack(fill='x',pady=2)
            self._chk(r,"啟用",en).pack(side='left')
            self._lbl(r,"鍵:").pack(side='left',padx=(8,1))
            self._combo(r,key,FKEYS,w=3).pack(side='left')
            self._lbl(r,"<").pack(side='left',padx=(8,0))
            self._spin(r,thr,5,90,w=3,inc=5).pack(side='left')
            self._lbl(r,"%").pack(side='left')
            if extra:extra(r)

        mkrow("紅水(HP)",self.var_hp_en,self.var_hp_key,self.var_hp_thr)
        mkrow("藍水(MP)",self.var_mp_en,self.var_mp_key,self.var_mp_thr)
        def heal_ex(r):
            self._lbl(r," x").pack(side='left')
            self._spin(r,self.var_heal_n,1,5,w=2).pack(side='left')
        mkrow("治癒術",self.var_heal_en,self.var_heal_key,self.var_heal_thr,heal_ex)

        sf=self._section(p,"Buff / 緊急回城");sf.pack(fill='x',padx=10,pady=3)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"Buff",self.var_buff_en).pack(side='left')
        self._lbl(r,"鍵:").pack(side='left',padx=(4,1))
        self._combo(r,self.var_buff_key,FKEYS,w=3).pack(side='left')
        self._lbl(r,"每").pack(side='left',padx=(4,0))
        self._spin(r,self.var_buff_sec,60,3600,w=5,inc=60).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"緊急回城",self.var_recall_en).pack(side='left')
        self._lbl(r,"鍵:").pack(side='left',padx=(4,1))
        self._combo(r,self.var_recall_key,FKEYS,w=3).pack(side='left')
        self._lbl(r,"HP<").pack(side='left',padx=(4,0))
        self._spin(r,self.var_recall_thr,5,30,w=3,inc=5).pack(side='left')
        self._lbl(r,"%").pack(side='left')

        # 回城補給方案
        sf=self._section(p,"回城補給方案 (3套)");sf.pack(fill='x',padx=10,pady=3)
        presets=list(SUPPLY_PRESETS.keys())
        for i in range(3):
            r=self._frame(sf);r.pack(fill='x',pady=1)
            self._lbl(r,f"方案{i+1}:").pack(side='left')
            self._combo(r,self.var_supply[i],presets,w=12).pack(side='left',padx=2)

    # ═══ 技能頁 ═══
    def _build_skills(self):
        p=self.pages['技能']
        sf=self._section(p,"技能輪替（最多7個依序施放）");sf.pack(fill='x',padx=10,pady=5)
        tk.Label(sf,text="怪物死亡後從技能1重新開始循環",bg=BG2,fg='#888',font=FONTS).pack(anchor='w')
        for i in range(7):
            r=self._frame(sf);r.pack(fill='x',pady=2)
            self._lbl(r,f"技能{i+1}:").pack(side='left')
            self._combo(r,self.var_sk[i],['無']+FKEYS,w=3).pack(side='left',padx=2)
            self._lbl(r,"冷卻:").pack(side='left',padx=(8,1))
            self._spin(r,self.var_cd[i],0.5,30,w=4,inc=0.5).pack(side='left')
            self._lbl(r,"秒").pack(side='left')

        # 定時按鍵
        sf2=self._section(p,"定時按鍵（掛機時自動按）");sf2.pack(fill='x',padx=10,pady=5)
        for i in range(4):
            r=self._frame(sf2);r.pack(fill='x',pady=2)
            self._chk(r,f"#{i+1}",self.var_timer_en[i]).pack(side='left')
            self._lbl(r,"按鍵:").pack(side='left',padx=(4,1))
            self._combo(r,self.var_timer_key[i],['無']+FKEYS+['1','2','3','4','5','6','7','8','9','0'],w=3).pack(side='left',padx=2)
            self._lbl(r,"每").pack(side='left',padx=(6,1))
            self._spin(r,self.var_timer_sec[i],1,3600,w=5,inc=1).pack(side='left')
            self._lbl(r,"秒").pack(side='left')
            self._lbl(r,"按").pack(side='left',padx=(6,1))
            self._spin(r,self.var_timer_cnt[i],1,10,w=2).pack(side='left')
            self._lbl(r,"下").pack(side='left')

    # ═══ 安全頁 ═══
    def _build_safety(self):
        p=self.pages['安全']
        sf=self._section(p,"防護設定");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"反PK偵測",self.var_antipk).pack(side='left')
        self._lbl(r,"動作:").pack(side='left',padx=(8,1))
        self._combo(r,self.var_pk_act,['回城','逃跑','警示'],w=5).pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"斷線偵測 + 警示音",self.var_dc_detect).pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"擬人化操作（隨機延遲+微抖動）",self.var_humanize).pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"事件截圖日誌",self.var_sslog).pack(side='left')

        sf2=self._section(p,"快捷鍵 / 設定");sf2.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self._lbl(r,"開始/停止鍵:").pack(side='left')
        hks=['left windows','right windows','page up','page down','home','insert','pause','scroll lock']
        c=self._combo(r,self.var_hotkey,hks,w=12);c.pack(side='left')
        c.bind('<<ComboboxSelected>>',lambda e:self._bind_hotkey())
        r=self._frame(sf2);r.pack(fill='x',pady=5)
        tk.Button(r,text="匯出設定",font=FONTS,bg=ACC2,fg='white',command=self._export_cfg).pack(side='left',padx=3)
        tk.Button(r,text="匯入設定",font=FONTS,bg=ACC2,fg='white',command=self._import_cfg).pack(side='left',padx=3)
        tk.Button(r,text="檢查更新",font=FONTS,bg='#e67e22',fg='white',command=self._check_update).pack(side='left',padx=3)

        # 版本顯示
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self._lbl(r,f"目前版本: v{BOT_VERSION}").pack(side='left')
        self.update_lbl=tk.Label(r,text="",bg=BG2,fg='#2ecc71',font=FONTS)
        self.update_lbl.pack(side='left',padx=8)

    def _export_cfg(self):
        fp=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if fp:save_cfg(self);import shutil;shutil.copy(CONFIG_FILE,fp);self.log("設定已匯出")
    def _import_cfg(self):
        fp=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if fp:import shutil;shutil.copy(fp,CONFIG_FILE);load_cfg(self);self.log("設定已匯入")

    def _check_update(self):
        """從 GitHub 檢查並下載更新"""
        self.update_lbl.config(text="檢查中...", fg='#f39c12')
        self.root.update()
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        import urllib.request
        base_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{UPDATE_BRANCH}"
        files_to_update = ['lineage_bot.py', 'lineage_data.py']
        app_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            # 1. 先檢查遠端版本
            ver_url = f"{base_url}/lineage_bot.py"
            req = urllib.request.Request(ver_url, headers={'User-Agent': 'LineageBot'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                remote_code = resp.read().decode('utf-8')

            # 解析遠端版本號
            remote_ver = BOT_VERSION
            for line in remote_code.split('\n'):
                if line.strip().startswith('BOT_VERSION'):
                    remote_ver = line.split('=')[1].strip().strip('"').strip("'")
                    break

            if remote_ver == BOT_VERSION:
                self.root.after(0, lambda: self.update_lbl.config(
                    text=f"已是最新版 v{BOT_VERSION}", fg='#2ecc71'))
                self.root.after(0, lambda: self.log("已是最新版本"))
                return

            # 2. 有新版本，下載所有檔案
            updated = []
            for fname in files_to_update:
                try:
                    url = f"{base_url}/{fname}"
                    req = urllib.request.Request(url, headers={'User-Agent': 'LineageBot'})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        content = resp.read()
                    fpath = os.path.join(app_dir, fname)
                    # 備份舊檔
                    if os.path.exists(fpath):
                        bak = fpath + '.bak'
                        if os.path.exists(bak):
                            os.remove(bak)
                        os.rename(fpath, bak)
                    with open(fpath, 'wb') as f:
                        f.write(content)
                    updated.append(fname)
                except Exception as e:
                    self.root.after(0, lambda e=e, f=fname: self.log(f"更新 {f} 失敗: {e}"))

            if updated:
                msg = f"已更新 v{remote_ver}（{', '.join(updated)}）\n請重啟程式生效"
                self.root.after(0, lambda: self.update_lbl.config(
                    text=f"v{BOT_VERSION} -> v{remote_ver} 請重啟", fg='#e74c3c'))
                self.root.after(0, lambda: self.log(msg))
                self.root.after(0, lambda: __import__('tkinter').messagebox.showinfo("更新完成", msg))
            else:
                self.root.after(0, lambda: self.update_lbl.config(
                    text="更新失敗", fg='#e74c3c'))

        except Exception as e:
            self.root.after(0, lambda: self.update_lbl.config(
                text="檢查失敗", fg='#e74c3c'))
            self.root.after(0, lambda e=e: self.log(f"更新檢查失敗: {e}"))

    # ═══ 模式頁 ═══
    def _build_mode(self):
        p=self.pages['模式']
        sf=self._section(p,"掛機模式");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=3)
        for m in ['近戰','遠程','定點','召喚','隊伍']:
            tk.Radiobutton(r,text=m,variable=self.var_mode,value=m,bg=BG2,fg=FG,
                           selectcolor=ACC2,activebackground=BG2,font=FONTS,
                           command=self._on_mode).pack(side='left',padx=6)

        self.mode_frames={}
        # 近戰
        f=self._section(p,"近戰設定");self.mode_frames['近戰']=f
        tk.Label(f,text="使用「技能」頁面的技能輪替設定\n走到怪物旁邊自動攻擊",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)
        # 遠程
        f=self._section(p,"遠程設定");self.mode_frames['遠程']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"攻擊鍵:").pack(side='left')
        self._combo(r,self.var_rng_key,FKEYS,w=3).pack(side='left')
        self._lbl(r,"保持距離:").pack(side='left',padx=(8,0))
        self._spin(r,self.var_rng_dist,50,400,inc=25).pack(side='left')
        self._lbl(r,"px").pack(side='left')
        self._chk(r,"風箏走位",self.var_rng_kite).pack(side='left',padx=8)
        # 定點
        f=self._section(p,"定點設定");self.mode_frames['定點']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"攻擊鍵:").pack(side='left')
        self._combo(r,self.var_rng_key,FKEYS,w=3).pack(side='left')
        tk.Label(f,text="原地不動，只掃描射箭+喝水\n不移動、不撿物、不漫遊",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)
        # 召喚
        f=self._section(p,"召喚設定");self.mode_frames['召喚']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"召喚鍵:").pack(side='left')
        self._combo(r,self.var_sum_key,FKEYS,w=3).pack(side='left')
        self._lbl(r,"攻擊鍵:").pack(side='left',padx=(8,0))
        self._combo(r,self.var_sum_atk,FKEYS,w=3).pack(side='left')
        self._lbl(r,"重召喚:").pack(side='left',padx=(8,0))
        self._spin(r,self.var_sum_sec,300,3600,w=5,inc=60).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        # 隊伍
        f=self._section(p,"隊伍設定");self.mode_frames['隊伍']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"職責:").pack(side='left')
        self._combo(r,self.var_pt_role,['坦克','補師','輸出','輔助'],w=5).pack(side='left')
        self._lbl(r,"治療鍵:").pack(side='left',padx=(8,0))
        self._combo(r,self.var_pt_heal,FKEYS,w=3).pack(side='left')
        self._lbl(r,"Buff鍵:").pack(side='left',padx=(8,0))
        self._combo(r,self.var_pt_buff,FKEYS,w=3).pack(side='left')

        self._on_mode()

    def _on_mode(self):
        m=self.var_mode.get()
        for n,f in self.mode_frames.items():
            f.pack(fill='x',padx=10,pady=5) if n==m else f.pack_forget()

    def _on_class_change(self):
        c=self.var_class.get()
        if c in CLASS_PRESETS:
            p=CLASS_PRESETS[c]
            self.var_mode.set(p['mode'])
            self.var_hp_thr.set(p['hp_thr'])
            self.var_mp_thr.set(p['mp_thr'])
            self.var_heal_en.set(p['heal'])
            self.var_heal_thr.set(p['heal_thr'])
            self._on_mode()
            self.log(f"職業切換: {c} → 模式:{p['mode']}")

    # ═══ 路徑頁 ═══
    def _build_path(self):
        p=self.pages['路徑']
        sf=self._section(p,"路徑錄製與重播");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=3)
        self._chk(r,"自動重播路徑",self.var_path_en).pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=3)
        for t,cmd,c in[("錄製",self._rec,'#27ae60'),("停止",self._stop_rec,ACC),("儲存",self._save_path,ACC2),("載入",self._load_path,ACC2)]:
            tk.Button(r,text=t,font=FONTS,bg=c,fg='white',command=cmd).pack(side='left',padx=2)
        self.path_lbl=tk.Label(sf,text="未錄製",bg=BG2,fg=FG,font=FONTM)
        self.path_lbl.pack(pady=3)

        # 推薦練功路線
        sf2=self._section(p,"推薦練功路線");sf2.pack(fill='both',padx=10,pady=5,expand=True)
        cols=('等級','地點','怪物','提示')
        tree=ttk.Treeview(sf2,columns=cols,show='headings',height=8)
        for c in cols:tree.heading(c,text=c);tree.column(c,width=80 if c=='等級' else 150)
        for g in LEVELING_GUIDE:
            tree.insert('','end',values=(g.get('level',''),g.get('location',''),
                        ','.join(g.get('monsters',[])),g.get('tip','')))
        tree.pack(fill='both',expand=True)

    def _rec(self):
        g=find_game()
        if not g:self.log("找不到視窗");return
        path.start();self.path_lbl.config(text="錄製中...",fg=ACC);self.log("路徑錄製開始")
        def lp():
            while path.rec:
                g2=find_game()
                if g2:path.add(*get_rect(g2[0]))
                time.sleep(0.5)
        threading.Thread(target=lp,daemon=True).start()
    def _stop_rec(self):n=path.stop();self.path_lbl.config(text=f"已錄製 {n} 點",fg='#27ae60');self.log(f"錄製完成: {n} 點")
    def _save_path(self):
        if not path.pts:return
        fp=filedialog.asksaveasfilename(defaultextension='.json');
        if fp:path.save(fp);self.log("路徑已儲存")
    def _load_path(self):
        fp=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if fp:path.load(fp);self.path_lbl.config(text=f"已載入 {len(path.pts)} 點",fg='#27ae60')

    # ═══ 百科頁 ═══
    def _build_wiki(self):
        p=self.pages['百科']
        sf=self._section(p,"遊戲百科查詢");sf.pack(fill='both',padx=10,pady=5,expand=True)

        # 搜尋
        r=self._frame(sf);r.pack(fill='x',pady=3)
        self._lbl(r,"搜尋:").pack(side='left')
        self.wiki_entry=tk.Entry(r,font=FONTM,width=20,bg=BG3,fg=FG)
        self.wiki_entry.pack(side='left',padx=3)
        tk.Button(r,text="查詢怪物",font=FONTS,bg=ACC2,fg='white',command=self._search_monster).pack(side='left',padx=2)
        tk.Button(r,text="查詢藥水",font=FONTS,bg=ACC2,fg='white',command=self._search_potion).pack(side='left',padx=2)

        self.wiki_result=tk.Text(sf,height=15,bg='#0d1117',fg='#58a6ff',font=('Consolas',9),state='disabled',wrap='word')
        self.wiki_result.pack(fill='both',expand=True,pady=3)

    def _search_monster(self):
        q=self.wiki_entry.get().strip()
        results=[m for m in MONSTERS if q in m.get('name','') or q in m.get('location','')]
        self.wiki_result.config(state='normal');self.wiki_result.delete('1.0','end')
        if not results:
            self.wiki_result.insert('end',f"找不到「{q}」相關的怪物\n")
        else:
            self.wiki_result.insert('end',f"找到 {len(results)} 筆結果：\n\n")
            for m in results[:20]:
                ag="主動" if m.get('aggro') else "被動"
                self.wiki_result.insert('end',
                    f"【{m['name']}】Lv.{m['level']} HP:{m['hp']} EXP:{m['exp']} ({ag})\n"
                    f"  地點: {m['location']}\n\n")
        self.wiki_result.config(state='disabled')

    def _search_potion(self):
        q=self.wiki_entry.get().strip()
        results={k:v for k,v in POTIONS.items() if q in k}
        self.wiki_result.config(state='normal');self.wiki_result.delete('1.0','end')
        if not results:
            self.wiki_result.insert('end',f"找不到「{q}」相關的藥水\n")
        else:
            for name,info in results.items():
                rec=info.get('recovery','')
                price=info.get('price','N/A')
                note=info.get('note','')
                self.wiki_result.insert('end',f"【{name}】恢復:{rec} 價格:{price} {note}\n")
        self.wiki_result.config(state='disabled')

    # ═══ 通用 ═══
    def log(self,msg):
        ts=time.strftime("%H:%M:%S")
        def _u():
            self.log_w.config(state='normal');self.log_w.insert('end',f"[{ts}] {msg}\n")
            self.log_w.see('end');self.log_w.config(state='disabled')
        self.root.after(0,_u)

    def _bar(self,cv,tl,pct,w=120):
        def _u():
            p=max(0,min(1,pct));cv.delete('all')
            cv.create_rectangle(0,0,w,16,fill='#222',outline='')
            c=ACC if p<0.3 else('#f5a623' if p<0.6 else'#27ae60')
            cv.create_rectangle(0,0,int(w*p),16,fill=c,outline='')
            tl.config(text=f"{p*100:.0f}%")
        self.root.after(0,_u)

    def _stats(self):
        def _u():
            self.stat_lbl.config(text=f"殺:{self.kills} 紅:{self.pots} 藍:{self.mpots} 治:{self.heals} B:{self.buffs} 撿:{self.loots}")
            if self.t0:
                e=time.time()-self.t0;h,m,s=int(e//3600),int(e%3600//60),int(e%60)
                kph=self.kills/(e/3600) if e>60 else 0
                self.time_lbl.config(text=f"{h:02d}:{m:02d}:{s:02d} | {kph:.1f} 殺/時")
        self.root.after(0,_u)

    def _status(self,t,c='#aaa'):
        def _u():
            self.status_lbl.config(text=t,fg=c)
            self.start_btn.config(text="■ 停止" if self.running else "▶ 啟動",
                                  bg=ACC if self.running else '#27ae60')
        self.root.after(0,_u)

    def _toggle(self):
        if self.running:
            self.running=False;self._status("已停止");self.log("Bot 暫停");save_cfg(self)
        else:
            self.running=True;self.t0=time.time();self._status("運行中",'#27ae60');self.log("Bot 啟動")
            skills.setup([(self.var_sk[i].get(),self.var_cd[i].get()) for i in range(7)])
            if not self.thread or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()
            self._tick()

    def _tick(self):
        if self.running:self._stats();self.root.after(1000,self._tick)

    # ═══ Bot 主循環 ═══
    def _get_minimap_pos(self, cx, cy, cw, ch):
        """從小地圖上找到紅色 V 箭頭的位置（相對比例）"""
        try:
            mw = int(cw * 0.15)
            mh = int(ch * 0.15)
            frame = grab_region(cx, cy, mw, mh)
            # BGR → 找紅色 V（可能是深紅或亮紅）
            r, g, b = frame[:,:,2], frame[:,:,1], frame[:,:,0]
            # 寬鬆紅色條件
            red_mask = (r.astype(int) > 150) & (g.astype(int) < 120) & (b.astype(int) < 120)
            if red_mask.sum() < 3:
                # 嘗試更寬鬆
                red_mask = (r.astype(int) - g.astype(int) > 80) & (r.astype(int) > 120)
            if red_mask.sum() < 3:
                return None
            ys, xs = np.where(red_mask)
            return (float(xs.mean()) / mw, float(ys.mean()) / mh)
        except:
            return None

    def _check_drift(self, cx, cy, cw, ch):
        """檢查角色是否偏離定點太遠，回傳偏移距離（0-1 比例）"""
        if not hasattr(self, 'minimap_anchor') or self.minimap_anchor is None:
            return 0
        current = self._get_minimap_pos(cx, cy, cw, ch)
        if current is None:
            return 0
        dx = current[0] - self.minimap_anchor[0]
        dy = current[1] - self.minimap_anchor[1]
        return math.sqrt(dx*dx + dy*dy)

    def _walk_back_to_anchor(self, cx, cy, cw, ch, hwnd):
        """走回小地圖定點位置，每步重新偵測方向"""
        if not hasattr(self, 'minimap_anchor') or self.minimap_anchor is None:
            return False
        sh_scene = int(ch * 0.75)
        center_x = cx + cw // 2
        center_y = cy + sh_scene // 2
        for step in range(8):  # 最多走 8 步
            cur = self._get_minimap_pos(cx, cy, cw, ch)
            if cur is None:
                return False
            dx = self.minimap_anchor[0] - cur[0]
            dy = self.minimap_anchor[1] - cur[1]
            drift = math.sqrt(dx*dx + dy*dy)
            if drift < 0.03:
                self.log(f"已回到定點（{step}步）")
                return True  # 到了
            # 將小地圖差異換算為畫面上的點擊方向（小步走）
            scale = min(200, max(80, int(drift * cw * 2)))
            dd = max(0.001, drift)
            back_x = center_x + int(dx / dd * scale)
            back_y = center_y + int(dy / dd * scale)
            back_x = max(cx + 50, min(cx + cw - 50, back_x))
            back_y = max(cy + 50, min(cy + sh_scene - 50, back_y))
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
            game_click(back_x, back_y)
            time.sleep(1.5)
        return False

    def _check_survival(self, hwnd, cx, cy, cw, ch, timers):
        """生存系統：HP/MP/治療/喝水/Buff — 每次循環都呼叫"""
        now = time.time()
        hp = mp = 1.0
        try:
            hp = bars.hp(None, cx, cy, cw, ch)
            self._bar(self.hp_cv, self.hp_tl, hp)
            mp = bars.mp(None, cx, cy, cw, ch)
            if mp >= 0:
                self._bar(self.mp_cv, self.mp_tl, mp)
        except:
            pass
        # debug：每 10 秒顯示 HP/MP 讀值，方便排查
        if not hasattr(self, '_last_hp_debug'):
            self._last_hp_debug = 0
        if now - self._last_hp_debug > 10:
            self.log(f"[HP={hp:.2f} MP={mp:.2f} 窗={cw}x{ch}]")
            self._last_hp_debug = now

        # Buff（不需要 HP 值，定時觸發）
        if self.var_buff_en.get() and now - timers['buff'] > self.var_buff_sec.get():
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
            key = self.var_buff_key.get().lower()
            keyboard.press(key)
            time.sleep(0.05)
            keyboard.release(key)
            time.sleep(0.3)
            timers['buff'] = now
            self.buffs += 1
            self.log(f"喝綠水({key})")

        # 死亡（僅在 HP 成功讀取時判定）
        if hp >= 0 and hp <= 0.01:
            self.log("角色死亡！")
            alert('death')
            self.running = False
            self._status("死亡！", ACC)
            return hp, mp

        # 緊急回城（最高優先，僅在 HP 成功讀取時觸發）
        if self.var_recall_en.get() and hp >= 0 and hp < self.var_recall_thr.get() / 100:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            press_key(self.var_recall_key.get())
            self.log(f"緊急回城！HP={hp*100:.0f}%")
            alert('hp')
            # 不停止 bot，等待回城後可以重播路徑回來
            time.sleep(5)
            return hp, mp

        # 治癒術（HP 低於閾值 / 讀取失敗每 10 秒 / HP=1.0 疑似讀錯每 15 秒保底）
        heal_trigger = (hp >= 0 and hp < self.var_heal_thr.get() / 100) \
                       or (hp < 0 and now - timers['heal'] > 10) \
                       or (hp >= 0.99 and now - timers['heal'] > 15)
        if self.var_heal_en.get() and heal_trigger and now - timers['heal'] > 2:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            key = self.var_heal_key.get().lower()
            for _ in range(self.var_heal_n.get()):
                keyboard.press(key); time.sleep(0.05); keyboard.release(key)
                time.sleep(0.15)
            timers['heal'] = now
            self.heals += 1

        # 紅水（HP 低於閾值 / HP 讀取失敗每 5 秒 / HP=1.0 疑似讀錯每 8 秒保底）
        hp_trigger = (hp >= 0 and hp < self.var_hp_thr.get() / 100) \
                     or (hp < 0 and now - timers['hp'] > 5) \
                     or (hp >= 0.99 and now - timers['hp'] > 8)
        if self.var_hp_en.get() and hp_trigger and now - timers['hp'] > 1.5:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            key = self.var_hp_key.get().lower()
            keyboard.press(key); time.sleep(0.05); keyboard.release(key)
            timers['hp'] = now
            self.pots += 1

        # 藍水（同樣加保底：MP=1.0 疑似讀錯每 10 秒喝）
        mp_trigger = (mp >= 0 and mp < self.var_mp_thr.get() / 100) \
                     or (mp < 0 and now - timers['mp'] > 8) \
                     or (mp >= 0.99 and now - timers['mp'] > 10)
        if self.var_mp_en.get() and mp_trigger and now - timers['mp'] > 3:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            key = self.var_mp_key.get().lower()
            keyboard.press(key); time.sleep(0.05); keyboard.release(key)
            timers['mp'] = now
            self.mpots += 1

        # Buff
        # 召喚重召喚
        mode = self.var_mode.get()
        if mode == '召喚' and now - timers['summon'] > self.var_sum_sec.get():
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            press_key(self.var_sum_key.get())
            timers['summon'] = now
            self.log("重召喚")

        # 定時按鍵（4 組）
        for i in range(4):
            if not self.var_timer_en[i].get():
                continue
            tkey = self.var_timer_key[i].get()
            if tkey == '無':
                continue
            timer_name = f'timer_{i}'
            if timer_name not in timers:
                timers[timer_name] = 0
            interval = self.var_timer_sec[i].get()
            if now - timers[timer_name] > interval:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.1)
                cnt = self.var_timer_cnt[i].get()
                for _ in range(cnt):
                    press_key(tkey)
                    time.sleep(0.15)
                timers[timer_name] = now
                self.log(f"定時按鍵#{i+1}: {tkey} x{cnt}")

        self._stats()
        return hp, mp

    def _do_attack(self, mx, my, cx, cy, cw, ch, hwnd):
        """執行攻擊（依模式）"""
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        mode = self.var_mode.get()
        if mode == '近戰':
            attack(mx, my, cx, cy, cw, ch)
        elif mode == '遠程':
            attack(mx, my, cx, cy, cw, ch)
            time.sleep(0.2)
            press_key(self.var_rng_key.get())
            # 後退保持距離
            sh = int(ch * 0.75)
            d = self.var_rng_dist.get()
            dx, dy = cx + cw // 2 - mx, cy + sh // 2 - my
            dd = max(1, math.sqrt(dx * dx + dy * dy))
            sx = max(cx + 50, min(cx + cw - 50, mx + int(dx / dd * d)))
            sy = max(cy + 30, min(cy + sh - 30, my + int(dy / dd * d)))
            move_exact(sx, sy)
            game_click(sx, sy)
        elif mode == '定點':
            # 定點：按攻擊鍵 → 移到怪物 → 按住 → 拖曳 → 放開
            press_key(self.var_rng_key.get())
            time.sleep(0.1)
            move_exact(mx, my)
            time.sleep(0.08)
            game_down()
            time.sleep(0.08)
            drag_y = my + random.randint(150, 300)
            drag_x = mx + random.randint(-15, 15)
            for s in range(1, 5):
                move_exact(mx + (drag_x - mx) * s // 4, my + (drag_y - my) * s // 4)
                time.sleep(0.02)
            time.sleep(0.05)
            game_up()
        elif mode == '召喚':
            attack(mx, my, cx, cy, cw, ch)
            press_key(self.var_sum_atk.get())
            sh = int(ch * 0.75)
            move_exact(cx + cw // 2, cy + sh // 2)
            game_click()
        elif mode == '隊伍':
            role = self.var_pt_role.get()
            if role in ('坦克', '輸出'):
                attack(mx, my, cx, cy, cw, ch)
            elif role == '補師':
                press_key(self.var_pt_heal.get())
            elif role == '輔助':
                press_key(self.var_pt_buff.get())
                attack(mx, my, cx, cy, cw, ch)

    def _combat_skill(self):
        """戰鬥中持續施放技能（依模式）"""
        mode = self.var_mode.get()
        if mode == '近戰':
            skills.use_next()
        elif mode in ('遠程', '定點'):
            press_key(self.var_rng_key.get())
        elif mode == '召喚':
            press_key(self.var_sum_atk.get())
        elif mode == '隊伍' and self.var_pt_role.get() == '補師':
            press_key(self.var_pt_heal.get())

    def _loop(self):
        timers = {'hp': 0, 'mp': 0, 'heal': 0, 'buff': 0, 'summon': 0}
        dcc = 0
        no_monster_count = 0   # 連續找不到怪的次數
        drift_x = 0  # 累積漂移量（相對於啟動位置）
        drift_y = 0
        max_drift = 500  # 超過此距離就走回來

        g = find_game()
        if not g:
            self.log("找不到視窗！")
            self.running = False
            self._status("找不到視窗", ACC)
            return
        self.log(f"視窗: {g[1][:30]}...")

        # 自動偵測輸入模式
        _detect_input_mode(g[0])
        self.log(f"輸入模式: {INPUT_MODE}")

        # 自動偵測手指游標 handle
        global CURSOR_FINGER
        if CURSOR_FINGER is None:
            self.log("偵測游標 handle...")
            hwnd_init = g[0]
            cx0, cy0, cw0, ch0 = get_rect(hwnd_init)
            sh0 = int(ch0 * 0.75)
            ctypes.windll.user32.SetForegroundWindow(hwnd_init)
            time.sleep(0.3)
            handles = {}
            for py in range(cy0+60, cy0+sh0-60, 80):
                for px in range(cx0+60, cx0+cw0-60, 80):
                    move_exact(px, py)
                    time.sleep(0.03)
                    h = get_cursor()
                    handles[h] = handles.get(h, 0) + 1
            if handles:
                CURSOR_FINGER = max(handles, key=handles.get)
                self.log(f"手指游標={CURSOR_FINGER} (其他: {[h for h in handles if h != CURSOR_FINGER]})")
            else:
                self.log("游標偵測失敗")
                return

        # ── 啟動動作 ──
        hwnd_start = g[0]
        cx_s, cy_s, cw_s, ch_s = get_rect(hwnd_start)
        ctypes.windll.user32.SetForegroundWindow(hwnd_start)
        time.sleep(0.2)

        # 1. 立刻喝綠水
        if self.var_buff_en.get():
            key = self.var_buff_key.get().lower()
            keyboard.press(key)
            time.sleep(0.05)
            keyboard.release(key)
            timers['buff'] = time.time()
            self.buffs += 1
            self.log(f"啟動喝綠水({key})")
            time.sleep(0.5)

        # 2. 打開小地圖 (Ctrl+M)
        keyboard.press('ctrl')
        time.sleep(0.05)
        press_key_raw('m')
        keyboard.release('ctrl')
        time.sleep(0.5)

        # 3. 記錄小地圖上角色初始位置
        self.minimap_anchor = self._get_minimap_pos(cx_s, cy_s, cw_s, ch_s)
        if self.minimap_anchor:
            self.log(f"小地圖定點: {self.minimap_anchor}")
        else:
            self.log("小地圖定點記錄失敗")

        while True:
            if not self.running:
                time.sleep(0.2)
                continue

            # ── 找遊戲視窗 ──
            g = find_game()
            if not g:
                dcc += 1
                if self.var_dc_detect.get() and dcc >= 3:
                    self.log("斷線！")
                    alert('dc')
                    self.running = False
                    self._status("斷線！", ACC)
                    return
                time.sleep(2)
                continue
            dcc = 0
            hwnd = g[0]
            cx, cy, cw, ch = get_rect(hwnd)

            sh_scene = int(ch * 0.75)

            # ── 生存系統 ──
            hp, mp = self._check_survival(hwnd, cx, cy, cw, ch, timers)
            if not self.running:
                return

            # ── 路徑重播模式 ──
            if self.var_path_en.get() and path.pts:
                self._status("路徑重播", '#f5a623')
                path.play(cx, cy, cw, ch, hwnd)
                continue

            # ── 自動練功循環 ──
            if not self.var_attack.get():
                time.sleep(0.5)
                continue

            mode = self.var_mode.get()
            self._status(f"掃描({mode})", '#f5a623')

            # 掃描+攻擊一體化（碰到怪物瞬間就打）
            mon = scan_and_attack(cx, cy, cw, ch, hwnd, self.log, mode=mode)

            if mon and self.running:
                mx, my = mon
                no_monster_count = 0
                self._status(f"戰鬥({mode})", ACC)

                # 遠程/定點/召喚模式的額外技能
                if mode == '定點':
                    # 定點：先按攻擊鍵 → 再點擊怪物+短拖曳
                    self._do_attack(mx, my, cx, cy, cw, ch, hwnd)
                elif mode == '遠程':
                    press_key(self.var_rng_key.get())
                elif mode == '召喚':
                    press_key(self.var_sum_atk.get())

                time.sleep(0.2)

                # ── 啟動預掃描（戰鬥中同時找下一隻怪） ──
                pre_scanner.start(cx, cy, cw, ch, hwnd, exclude=(mx, my))

                # ── 戰鬥等待（雙重偵測：HP條+游標，30ms級反應） ──
                combat_start = time.time()
                stuck_time = self.var_stuck.get()
                retry_attack = 0
                last_skill = last_surv = 0
                killed = False
                hp_bar_gone_count = 0

                while time.time() - combat_start < stuck_time and self.running:
                    now = time.time()

                    # 生存檢查（每 1.5 秒）
                    if now - last_surv > 1.5:
                        hp, mp = self._check_survival(hwnd, cx, cy, cw, ch, timers)
                        if not self.running:
                            pre_scanner.stop()
                            return
                        last_surv = now

                    # 技能施放（每 1 秒）
                    if now - last_skill > 1.0:
                        self._combat_skill()
                        last_skill = now

                    # 死亡偵測方法1：怪物頭上 HP 條消失
                    if not detect_monster_hp_bar(cx, cy, cw, ch, mx, my):
                        hp_bar_gone_count += 1
                        if hp_bar_gone_count >= 2:
                            killed = True
                            break
                    else:
                        hp_bar_gone_count = 0

                    # 死亡偵測方法2：游標不再是劍（備用）
                    move_exact(mx, my)
                    time.sleep(0.05)
                    if get_cursor() == CURSOR_FINGER:
                        time.sleep(0.1)
                        move_exact(mx, my)
                        time.sleep(0.05)
                        if get_cursor() == CURSOR_FINGER:
                            killed = True
                            break

                    # 重新攻擊（每 4 秒確保命中）
                    if now - combat_start > 4 * (retry_attack + 1):
                        retry_attack += 1
                        self._do_attack(mx, my, cx, cy, cw, ch, hwnd)

                    time.sleep(0.15 + random.uniform(0, 0.05))

                # 停止預掃描，取得結果
                pre_scanner.stop()
                next_mon = pre_scanner.get()

                if killed:
                    self.kills += 1
                    self.log(f"擊殺！(#{self.kills})")
                    self._stats()

                    # 定點模式：每 20 隻走回啟動位置
                    if mode == '定點' and self.kills % 20 == 0 and self.running:
                        self._status("回定點", '#f5a623')
                        self.log(f"定點回歸（已殺 {self.kills} 隻）")
                        self._walk_back_to_anchor(cx, cy, cw, ch, hwnd)

                    # 快速撿物（定點模式不撿）
                    if self.var_loot.get() and mode != '定點' and self.running:
                        for _ in range(2):
                            if not scan_loot(cx, cy, cw, ch, hwnd):
                                break
                            self.loots += 1
                            time.sleep(0.1)
                        self._stats()

                    # ── 零延遲轉移：有預掃描結果就直接打 ──
                    if next_mon and self.running:
                        mx, my = next_mon
                        self.log(f"預掃描→下一隻 ({mx},{my})")
                        self._status(f"戰鬥({mode})", ACC)
                        self._do_attack(mx, my, cx, cy, cw, ch, hwnd)
                        # 重新進入戰鬥等待（遞迴不好，用 continue）
                        time.sleep(0.3)
                    continue  # 回到主循環立刻掃描
                else:
                    self.log("卡怪！換目標")
                    alert('stuck')
                    continue

            else:
                # ── 沒找到怪物 ──
                no_monster_count += 1

                if self.running and self.var_roam.get() and mode != '定點':
                    # 用小地圖檢查偏移
                    drift = self._check_drift(cx, cy, cw, ch)

                    if drift > 0.15:  # 小地圖上偏移超過 15% = 走太遠
                        self._status(f"回定點", '#f5a623')
                        self.log(f"偏離定點({drift:.2f})，走回去")
                        self._walk_back_to_anchor(cx, cy, cw, ch, hwnd)
                        no_monster_count = 0
                    else:
                        # 正常漫遊
                        dist = min(150, self.var_roam_dist.get()) if no_monster_count <= 3 else self.var_roam_dist.get()
                        self._status("搜索", '#aaa')
                        r = roam(cx, cy, cw, ch, hwnd, dist)
                        if r:
                            mx, my = r
                            self.log(f"漫遊發現怪物！({mx},{my})")
                            self._do_attack(mx, my, cx, cy, cw, ch, hwnd)
                            no_monster_count = 0
                elif self.running:
                    time.sleep(1 + random.uniform(0, 0.5))

    def run(self):self.log("就緒");self.root.mainloop()

if __name__=="__main__":BotApp().run()
