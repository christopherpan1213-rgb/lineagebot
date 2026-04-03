"""
天堂經典版 Bot — 狀態機架構
全 Interception 驅動 + OpenCV 怪物偵測 + DXcam 高速截圖 + 狀態機防衝突
"""
BOT_VERSION = "15.2"
GITHUB_REPO = "christopherpan1213-rgb/lineagebot"
UPDATE_BRANCH = "main"
import ctypes, ctypes.wintypes

# 喝水改用滑鼠點快捷欄，不需要管理員權限

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
from enum import Enum

# ═══════════════════════════════ 狀態機 ═══════════════════════════════

class BotState(Enum):
    IDLE = "idle"              # 等待/未啟動
    SCANNING = "scanning"      # 螺旋掃描找怪
    ATTACKING = "attacking"    # 戰鬥中（滑鼠鎖定在怪物）
    DRINKING = "drinking"      # 點快捷欄喝水/治癒（滑鼠在快捷欄）
    WALKING = "walking"        # 墮落之地北移（滑鼠在地圖上方）
    LOOTING = "looting"        # 撿物
    DEAD = "dead"              # 死亡等待復活
    RESUPPLYING = "resupply"   # 回城補給中

# 合法的狀態轉換
VALID_TRANSITIONS = {
    BotState.IDLE:         [BotState.SCANNING, BotState.DRINKING],
    BotState.SCANNING:     [BotState.ATTACKING, BotState.DRINKING, BotState.IDLE, BotState.WALKING, BotState.DEAD, BotState.RESUPPLYING],
    BotState.ATTACKING:    [BotState.SCANNING, BotState.DRINKING, BotState.LOOTING, BotState.IDLE, BotState.DEAD],
    BotState.DRINKING:     [BotState.SCANNING, BotState.ATTACKING, BotState.IDLE],
    BotState.WALKING:      [BotState.SCANNING, BotState.DRINKING, BotState.IDLE],
    BotState.LOOTING:      [BotState.SCANNING, BotState.DRINKING, BotState.IDLE],
    BotState.DEAD:         [BotState.SCANNING, BotState.IDLE],
    BotState.RESUPPLYING:  [BotState.SCANNING, BotState.IDLE],
}

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
    import interception; interception.auto_capture_devices(mouse=True, keyboard=True); HAS_INTERCEPTION = True
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
    """HP/MP 條讀取 — 像素顏色偵測（不需要 OCR）
    原理：HP 條損失部分變白，剩餘部分是紅/暖色
          MP 條損失部分變白，剩餘部分是藍色
    速度：~1ms（vs OCR 3-5秒），任何 Windows 都能用
    """
    def __init__(self):
        self.ok = True
        self._hp_ratio = 1.0
        self._mp_ratio = 1.0
        self._hp_cur = 0
        self._hp_max = 0
        self._mp_cur = 0
        self._mp_max = 0
        self._last_read = 0
        self._read_interval = 0.5  # 每 0.5 秒讀一次（比 OCR 快很多）
        self._last_ocr_text = ""   # 相容性：保留給 debug log 用
        self._hp_bar = None  # (x_start, x_end, y_center) 相對於遊戲視窗的比例
        self._mp_bar = None
        self._calibrated = False

    def _find_bars(self, cx, cy, cw, ch):
        """自動找 HP/MP 條的位置（只需校準一次）
        找同時有 dark_red 和 dark_blue 的行（= HP 和 MP 條的行）
        """
        best_y = 0
        best_score = 0

        # 截取底部 UI 區域一次（避免多次截圖）
        y_start = int(ch * 0.73)
        y_end = int(ch * 0.86)
        frame = grab_region(cx, cy + y_start, cw, y_end - y_start)
        if frame is None or frame.size == 0:
            return False

        for y_off in range(frame.shape[0]):
            row = frame[y_off]
            r, g, b = row[:, 2].astype(int), row[:, 1].astype(int), row[:, 0].astype(int)
            # 嚴格 dark red（排除金色裝飾邊框）
            dr = ((r > 120) & (g < 80) & (b < 40)).sum()
            # 藍色
            db = ((b > 80) & ((b - r) > 20)).sum()
            if dr > 5 and db > 5 and dr + db > best_score:
                best_score = dr + db
                best_y = y_start + y_off

        if best_y == 0:
            return False

        # 取 3 行平均，用嚴格顏色找 red 和 blue 的主要叢集
        rows = grab_region(cx, cy + best_y - 1, cw, 3)
        if rows is None or rows.size == 0:
            return False
        r, g, b = rows[:,:,2].astype(int), rows[:,:,1].astype(int), rows[:,:,0].astype(int)

        dr_col = ((r > 120) & (g < 80) & (b < 40)).any(axis=0)
        db_col = ((b > 80) & ((b - r) > 20) & ((b - g) > 10)).any(axis=0)

        # HP: 找最大的 dark_red 連續叢集
        dr_xs = np.where(dr_col)[0]
        if len(dr_xs) > 3:
            gaps = np.diff(dr_xs)
            splits = np.where(gaps > 15)[0]
            if len(splits):
                clusters = np.split(dr_xs, splits + 1)
                largest = max(clusters, key=len)
            else:
                largest = dr_xs
            self._hp_bar = (largest[0] / cw, largest[-1] / cw, best_y / ch)

        # MP: 找最大的 blue 連續叢集
        db_xs = np.where(db_col)[0]
        if len(db_xs) > 3:
            gaps = np.diff(db_xs)
            splits = np.where(gaps > 15)[0]
            if len(splits):
                clusters = np.split(db_xs, splits + 1)
                largest = max(clusters, key=len)
            else:
                largest = db_xs
            self._mp_bar = (largest[0] / cw, largest[-1] / cw, best_y / ch)

        return self._hp_bar is not None

    def _read_bar_ratio(self, cx, cy, cw, ch, bar_info, bar_type='hp'):
        """讀取 HP/MP 條填充比例
        結構：[邊框] [白色=損失] [暗線] [填充色+文字=剩餘] [邊框]
        方法：
        1. 從校準的填充起點開始
        2. 往右延伸（含文字區），遇到連續暗區才停
        3. 往左掃找白色區（= 損失）
        4. HP = 填充寬 / (白色寬 + 填充寬)
        """
        if not bar_info:
            return 1.0

        red_x1_pct, red_x2_pct, y_pct = bar_info
        y = int(ch * y_pct)

        # 擴大截取範圍（往左多抓 15%，往右多抓一點）
        scan_left = int(cw * 0.15)
        x_start = max(0, int(cw * red_x1_pct) - scan_left)
        x_end = min(cw, int(cw * red_x2_pct) + int(cw * 0.05))
        region_w = x_end - x_start
        if region_w < 5:
            return 1.0

        frame = grab_region(cx + x_start, cy + y - 1, region_w, 3)
        if frame is None or frame.size == 0:
            return 1.0

        r, g, b = frame[:,:,2].astype(int), frame[:,:,1].astype(int), frame[:,:,0].astype(int)
        bright = (r + g + b) / 3

        if bar_type == 'hp':
            fill_col = ((r > 120) & (g < 80) & (b < 40)).any(axis=0)
        else:
            fill_col = ((b > 80) & ((b - r) > 20) & ((b - g) > 10)).any(axis=0)

        non_dark = (bright > 50).any(axis=0)
        white_col = (bright > 150).any(axis=0)

        fill_xs = np.where(fill_col)[0]
        if len(fill_xs) == 0:
            return 0.0

        first_fill = fill_xs[0]

        # 往右延伸：包含填充色 + 文字（非暗區），遇到 8+ 連續暗格停止
        bar_right = first_fill
        dark_run = 0
        for x in range(first_fill, frame.shape[1]):
            if non_dark[x]:
                bar_right = x
                dark_run = 0
            else:
                dark_run += 1
                if dark_run > 8:
                    break

        fill_width = bar_right - first_fill + 1

        # 往左掃找白色（損失）區域，跳過 1-3px 暗線邊框
        white_width = 0
        x = first_fill - 1
        skipped = 0
        while x >= 0 and not white_col[x] and skipped < 4:
            x -= 1; skipped += 1
        while x >= 0 and white_col[x]:
            white_width += 1; x -= 1

        total = fill_width + white_width
        if total < 3:
            return 1.0

        return fill_width / total

    def _update(self, cx, cy, cw, ch):
        """快速更新 HP/MP（每 0.5 秒）"""
        now = time.time()
        if now - self._last_read < self._read_interval:
            return

        # 首次自動校準
        if not self._calibrated:
            if self._find_bars(cx, cy, cw, ch):
                self._calibrated = True
            else:
                # 校準失敗，使用預設位置
                self._hp_bar = (0.10, 0.48, 0.803)
                self._mp_bar = (0.55, 0.85, 0.803)
                self._calibrated = True

        self._last_read = now
        self._hp_ratio = self._read_bar_ratio(cx, cy, cw, ch, self._hp_bar, 'hp')
        self._mp_ratio = self._read_bar_ratio(cx, cy, cw, ch, self._mp_bar, 'mp')
        # 相容性：估算數值（條的比例 * 假設最大值）
        if self._hp_max > 0:
            self._hp_cur = int(self._hp_ratio * self._hp_max)
        if self._mp_max > 0:
            self._mp_cur = int(self._mp_ratio * self._mp_max)
        self._last_ocr_text = f"pixel HP={self._hp_ratio:.0%} MP={self._mp_ratio:.0%}"

    def hp(self, sct, cx, cy, cw, ch):
        self._update(cx, cy, cw, ch)
        return self._hp_ratio

    def mp(self, sct, cx, cy, cw, ch):
        return self._mp_ratio

    def calibrate(self, sct, cx, cy, cw, ch):
        self._calibrated = False
        self._update(cx, cy, cw, ch)
        return self._hp_ratio >= 0

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

    # 墮落之地特化：掃描重心偏上方（怪物從上方刷新）
    if mode == '墮落之地':
        center_y = cy + int(sh * 0.35)  # 重心往上移

    # 步距依視窗大小縮放（以 860px 為基準）
    short_side = min(cw, sh)
    scale = short_side / 860

    if mode == '純定點':
        step = max(15, int(75 * scale))
        max_radius = short_side * 2 // 3
        scan_delay = 0.02
    elif mode == '墮落之地':
        step = max(15, int(75 * scale))
        max_radius = short_side * 3 // 4
        scan_delay = 0.012
    elif mode in ('遠程', '定點'):
        step = max(15, int(75 * scale))
        max_radius = short_side * 2 // 3
        scan_delay = 0.01
    else:  # 近戰
        step = max(15, int(65 * scale))
        max_radius = short_side // 2
        scan_delay = 0.015

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
                # 檢查是不是玩家（粉紅色名字）
                try:
                    name_area = grab_region(px - 40, py - 25, 80, 20)
                    if name_area is not None and name_area.size > 0:
                        r_ch = name_area[:,:,2].astype(int)
                        g_ch = name_area[:,:,1].astype(int)
                        b_ch = name_area[:,:,0].astype(int)
                        # 粉紅色: R>150, B>100, G<120
                        pink = (r_ch > 150) & (b_ch > 100) & (g_ch < 120)
                        if pink.sum() > 15:
                            if log:
                                log(f"掃到玩家，跳過({px},{py})")
                            continue
                except:
                    pass

                # 找到怪物！
                if log:
                    log(f"掃{count}點→打！({px},{py})")

                # 按下+拖曳攻擊
                time.sleep(0.05)
                game_down()
                time.sleep(0.08)

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
    # 墮落之地：掃完回到上方待命
    if mode == '墮落之地':
        move_exact(center_x, cy + int(sh * 0.3))
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
    def __init__(self): self.skills=[];self.last={};self._hotbar_fn=None
    def setup(self,sl,hotbar_fn=None):
        self.skills=[(k,cd) for k,cd in sl if k!='無'];self.last={k:0 for k,_ in self.skills}
        if hotbar_fn: self._hotbar_fn=hotbar_fn
    def use_next(self):
        now=time.time()
        for k,cd in self.skills:
            if now-self.last.get(k,0)>=cd:
                if self._hotbar_fn:
                    self._hotbar_fn(k, clicks=4)  # 法術類連點
                else:
                    press_key(k)  # fallback
                self.last[k]=now;return k
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

# 字型：優先微軟正黑體，fallback 到其他中文字型或系統預設
def _pick_font():
    import tkinter as _tk
    _r = _tk.Tk(); _r.withdraw()
    available = _tk.font.families()
    _r.destroy()
    for name in ('Microsoft JhengHei', 'Microsoft YaHei', 'SimHei', 'PMingLiU', 'Arial'):
        if name in available:
            return name
    return 'TkDefaultFont'

try:
    import tkinter.font
    _UI_FONT = _pick_font()
except:
    _UI_FONT = 'Microsoft JhengHei'

FONT=(_UI_FONT,11); FONTS=(_UI_FONT,10); FONTM=('Consolas',10)

class BotApp:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title(f"天堂經典版 Bot v{BOT_VERSION}")
        self.root.geometry("780x680")
        self.root.minsize(700, 600)
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
        self.var_ocr_en=tk.BooleanVar(value=True)  # OCR 偵測開關
        # 墮落之地定時北移
        self.var_fallen_walk_en=tk.BooleanVar(value=True)
        self.var_fallen_walk_min=tk.IntVar(value=5)    # 每幾分鐘
        self.var_fallen_walk_sec=tk.IntVar(value=10)   # 點幾秒
        self.var_hp_en=tk.BooleanVar(value=True)
        self.var_hp_sec=tk.IntVar(value=60)      # 定時喝紅水秒數
        self.var_mp_en=tk.BooleanVar(value=False)
        self.var_mp_sec=tk.IntVar(value=60)      # 定時喝藍水秒數
        self.var_heal_en=tk.BooleanVar(value=True)
        self.var_heal_sec=tk.IntVar(value=60)    # 定時治癒術秒數
        self.var_buff_en=tk.BooleanVar(value=True)
        self.var_recall_en=tk.BooleanVar(value=False)
        self.var_antipk=tk.BooleanVar(value=False)
        self.var_dc_detect=tk.BooleanVar(value=True)
        self.var_humanize=tk.BooleanVar(value=True)
        self.var_sslog=tk.BooleanVar(value=False)
        self.var_path_en=tk.BooleanVar(value=False)

        # 新功能 v15
        self.var_auto_rez=tk.BooleanVar(value=False)       # 自動復活
        self.var_rez_delay=tk.IntVar(value=5)               # 復活等待秒數
        self.var_pk_cooldown=tk.IntVar(value=30)            # 防 PK 冷卻秒數
        self.var_fast_detect=tk.BooleanVar(value=False)     # 畫面差異偵測
        self.var_supply_en=tk.BooleanVar(value=False)       # 自動回城補給
        self.var_supply_count=tk.IntVar(value=100)          # 喝幾次水後回城
        self.var_dead_stuck=tk.BooleanVar(value=False)        # 死亡卡住自動關遊戲
        # v15.1 防偵測
        self.var_captcha_detect=tk.BooleanVar(value=False)  # 聖光揭露偵測
        self.var_geofence_en=tk.BooleanVar(value=False)     # 地理圍欄
        self.var_geofence_radius=tk.IntVar(value=10)        # 圍欄半徑（小地圖%）
        self.var_human_pause=tk.BooleanVar(value=False)     # 擬人化停頓
        self.var_human_pause_min=tk.IntVar(value=15)        # 每幾分鐘停一次
        self.var_human_pause_sec=tk.IntVar(value=5)         # 停幾秒
        self.var_max_hours=tk.DoubleVar(value=0)            # 最大運行時數（0=無限）

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
        nav=tk.Frame(self.root,bg=BG1,width=140)
        nav.pack(side='left',fill='y')
        nav.pack_propagate(False)

        tk.Label(nav,text=f"天堂Bot",bg=BG1,fg=ACC,font=(_UI_FONT,15,'bold')).pack(pady=(8,0))
        tk.Label(nav,text=f"v{BOT_VERSION}",bg=BG1,fg='#555',font=('Consolas',9)).pack(pady=(0,10))

        self.pages={}
        self.nav_btns={}
        page_names=['狀態','戰鬥','生存','技能','偵測','安全','模式','路徑','百科']
        self.content=tk.Frame(self.root,bg=BG2)
        self.content.pack(side='right',fill='both',expand=True)

        # 導航圖示
        nav_icons={'狀態':'[ ]','戰鬥':'[x]','生存':'[+]','技能':'[*]','偵測':'[?]',
                   '安全':'[!]','模式':'[~]','路徑':'[>]','百科':'[i]'}
        for name in page_names:
            icon=nav_icons.get(name,'')
            btn=tk.Button(nav,text=f" {icon} {name}",font=FONTS,bg=BG1,fg=FG,activebackground=ACC2,
                          activeforeground='white',relief='flat',anchor='w',padx=10,
                          command=lambda n=name:self._show_page(n))
            btn.pack(fill='x',pady=1)
            self.nav_btns[name]=btn
            page=tk.Frame(self.content,bg=BG2)
            self.pages[name]=page

        # 啟動按鈕 + 狀態指示
        tk.Frame(nav,bg=BG1).pack(fill='both',expand=True)
        self.nav_state_lbl=tk.Label(nav,text="IDLE",bg=BG1,fg='#555',font=('Consolas',8))
        self.nav_state_lbl.pack(pady=(0,3))
        self.start_btn=tk.Button(nav,text="▶ 啟動",font=(_UI_FONT,11,'bold'),
                                 bg='#27ae60',fg='white',relief='flat',command=self._toggle)
        self.start_btn.pack(fill='x',padx=8,pady=(0,10),ipady=5)

        self._build_status()
        self._build_combat()
        self._build_survival()
        self._build_skills()
        self._build_detect()
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
        f=tk.LabelFrame(p,text=t,bg=BG2,fg=ACC,font=(_UI_FONT,9,'bold'),padx=6,pady=4)
        return f

    # ═══ 狀態頁 ═══
    def _build_status(self):
        p=self.pages['狀態']

        # ── 職業 + 地圖 ──
        f=self._frame(p);f.pack(fill='x',padx=10,pady=(10,5))
        self._lbl(f,"職業:").pack(side='left')
        c=self._combo(f,self.var_class,CLASSES,w=8);c.pack(side='left',padx=2)
        c.bind('<<ComboboxSelected>>',lambda e:self._on_class_change())
        self._lbl(f,"地圖:").pack(side='left',padx=(10,0))
        maps=list(VILLAGES.keys())+list(DUNGEONS.keys())
        if not maps:maps=['墮落的祝福之地','說話之島','象牙塔','遺忘之島']
        self._combo(f,self.var_map,maps,w=14).pack(side='left',padx=2)

        # ── HP/MP 大條 ──
        bar_frame=self._section(p,"血量 / 魔力");bar_frame.pack(fill='x',padx=10,pady=5)
        HP_W=200
        for lbl,clr in [("HP",ACC),("MP","#3498db")]:
            r=self._frame(bar_frame);r.pack(fill='x',pady=3)
            tk.Label(r,text=lbl,bg=BG2,fg=clr,font=('Consolas',12,'bold'),width=3).pack(side='left')
            cv=tk.Canvas(r,width=HP_W,height=22,bg='#111',highlightthickness=1,highlightbackground='#333')
            cv.pack(side='left',padx=5)
            tl=tk.Label(r,text="100%",bg=BG2,fg='#eee',font=('Consolas',10));tl.pack(side='left',padx=5)
            if lbl=="HP":self.hp_cv,self.hp_tl=cv,tl
            else:self.mp_cv,self.mp_tl=cv,tl

        # ── 狀態 + 統計 ──
        stat_frame=self._section(p,"運行狀態");stat_frame.pack(fill='x',padx=10,pady=5)
        self.status_lbl=tk.Label(stat_frame,text="已停止",bg=BG2,fg='#aaa',font=(_UI_FONT,13,'bold'))
        self.status_lbl.pack(pady=(3,0))
        self.stat_lbl=tk.Label(stat_frame,text="殺:0  紅:0  藍:0  治:0  Buff:0  撿:0",bg=BG2,fg='#aaa',font=FONTM)
        self.stat_lbl.pack(pady=2)
        self.time_lbl=tk.Label(stat_frame,text="00:00:00 | 0.0 殺/時",bg=BG2,fg='#555',font=FONTM)
        self.time_lbl.pack(pady=(0,3))

        # ── 系統資訊 ──
        sys_f=self._frame(p);sys_f.pack(fill='x',padx=10,pady=2)
        if HAS_INTERCEPTION:
            cap = 'DXcam' if HAS_DXCAM else 'MSS'
            info=f"Interception OK | {cap} | 怪物庫:{len(MONSTER_NAMES)}"
            info_fg='#27ae60'
        else:
            info="Interception 未安裝 — 遊戲可能無法操控滑鼠"
            info_fg='#e74c3c'
        tk.Label(sys_f,text=info,bg=BG2,fg=info_fg,font=('Consolas',8)).pack(side='left')

        # ── 工具按鈕 ──
        tool_f=self._frame(p);tool_f.pack(fill='x',padx=10,pady=3)
        tk.Button(tool_f,text="HP校準",font=FONTS,bg='#8e44ad',fg='white',command=self._debug_hp).pack(side='left',padx=2)
        tk.Button(tool_f,text="重新校準條",font=FONTS,bg=ACC2,fg='white',
                  command=lambda:self._recalibrate_bars()).pack(side='left',padx=2)

        # ── 日誌 ──
        sf=self._section(p,"日誌");sf.pack(fill='both',padx=10,pady=(3,10),expand=True)
        self.log_w=tk.Text(sf,height=8,bg='#0d1117',fg='#58a6ff',font=('Consolas',8),state='disabled',wrap='word')
        self.log_w.pack(fill='both',expand=True)

    def _recalibrate_bars(self):
        """重新校準 HP/MP 條位置"""
        g = find_game()
        if not g:
            self.log("找不到遊戲視窗！"); return
        bars._calibrated = False
        bars.calibrate(None, *get_rect(g[0]))
        if bars._hp_bar:
            self.log(f"HP條: X={bars._hp_bar[0]:.3f}-{bars._hp_bar[1]:.3f} Y={bars._hp_bar[2]:.3f}")
        if bars._mp_bar:
            self.log(f"MP條: X={bars._mp_bar[0]:.3f}-{bars._mp_bar[1]:.3f} Y={bars._mp_bar[2]:.3f}")
        if not bars._hp_bar:
            self.log("HP條校準失敗，使用預設位置")

    def _debug_hp(self):
        """截圖並標記 HP/MP 條偵測位置，存到桌面"""
        g = find_game()
        if not g:
            self.log("找不到遊戲視窗！")
            return
        cx, cy, cw, ch = get_rect(g[0])
        frame = grab_region(cx, cy, cw, ch)

        # 標記 HP 條位置（紅色框）
        hp_y = int(ch * 0.792)
        hp_xs = int(cw * 0.30)
        hp_xe = int(cw * 0.45)
        cv2.rectangle(frame, (hp_xs, hp_y - 5), (hp_xe, hp_y + 5), (0, 0, 255), 2)
        cv2.putText(frame, "HP", (hp_xs, hp_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # 標記 MP 條位置（藍色框）
        mp_xs = int(cw * 0.55)
        mp_xe = int(cw * 0.70)
        cv2.rectangle(frame, (mp_xs, hp_y - 5), (mp_xe, hp_y + 5), (255, 0, 0), 2)
        cv2.putText(frame, "MP", (mp_xs, hp_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

        # 讀值
        hp = bars.hp(None, cx, cy, cw, ch)
        mp = bars.mp(None, cx, cy, cw, ch)
        cv2.putText(frame, f"HP={hp:.2f} MP={mp:.2f} Window={cw}x{ch}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # 存檔
        out = os.path.join(os.path.expanduser("~"), "Desktop", "hp_debug.png")
        cv2.imwrite(out, frame)
        self.log(f"HP偵測截圖已存: {out}")
        self.log(f"HP={hp:.2f} MP={mp:.2f} 視窗={cw}x{ch}")
        self.log(f"HP條位置: Y={hp_y} X={hp_xs}-{hp_xe}")

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

        # OCR 開關
        r=self._frame(p);r.pack(fill='x',padx=10,pady=3)
        self._chk(r,"HP/MP OCR偵測（關閉=定時喝水）",self.var_ocr_en).pack(side='left')

        # 定時喝水秒數（OCR 關閉時使用）
        sf_timer=self._section(p,"定時喝水（OCR關閉時）");sf_timer.pack(fill='x',padx=10,pady=3)
        r=self._frame(sf_timer);r.pack(fill='x',pady=2)
        self._lbl(r,"紅水 每").pack(side='left')
        self._spin(r,self.var_hp_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        self._lbl(r,"   藍水 每").pack(side='left')
        self._spin(r,self.var_mp_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        self._lbl(r,"   治癒 每").pack(side='left')
        self._spin(r,self.var_heal_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"秒").pack(side='left')

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

    # ═══ 偵測頁（新功能）═══
    def _build_detect(self):
        p=self.pages['偵測']

        # 畫面差異偵測
        sf=self._section(p,"快速找怪（畫面差異）");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"啟用畫面差異偵測（比螺旋掃描快）",self.var_fast_detect).pack(side='left')
        tk.Label(sf,text="連續截兩幀比對移動區域，自動偵測怪物\n找不到時自動 fallback 回螺旋掃描",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)

        # 防 PK
        sf2=self._section(p,"防 PK 偵測");sf2.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self._chk(r,"啟用反PK",self.var_antipk).pack(side='left')
        self._lbl(r,"動作:").pack(side='left',padx=(8,1))
        self._combo(r,self.var_pk_act,['回城','逃跑','警示'],w=5).pack(side='left')
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self._lbl(r,"冷卻:").pack(side='left')
        self._spin(r,self.var_pk_cooldown,5,120,w=4).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        tk.Label(sf2,text="偵測新玩家名字出現（白字+深色背景框）\n觸發後進入冷卻，避免重複",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)

        # 自動復活
        sf3=self._section(p,"死亡處理");sf3.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf3);r.pack(fill='x',pady=2)
        self._chk(r,"自動復活",self.var_auto_rez).pack(side='left')
        self._lbl(r,"等待:").pack(side='left',padx=(8,1))
        self._spin(r,self.var_rez_delay,1,30,w=3).pack(side='left')
        self._lbl(r,"秒後復活").pack(side='left')
        tk.Label(sf3,text="死亡後自動回村（遊戲機制），等待指定秒數\n回村後 Buff → 重播路徑回練功點（需先錄製路徑）",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)
        r=self._frame(sf3);r.pack(fill='x',pady=2)
        self._chk(r,"死亡卡住自動關遊戲（啟動5分鐘後，HP=0+畫面靜止→關閉遊戲）",self.var_dead_stuck).pack(side='left')

        # 自動回城補給
        sf4=self._section(p,"自動回城補給");sf4.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf4);r.pack(fill='x',pady=2)
        self._chk(r,"啟用",self.var_supply_en).pack(side='left')
        self._lbl(r,"每喝").pack(side='left',padx=(8,1))
        self._spin(r,self.var_supply_count,20,500,w=4,inc=10).pack(side='left')
        self._lbl(r,"次水後回城").pack(side='left')
        tk.Label(sf4,text="到達次數後用回城卷返回城鎮，發出警示音\n手動買完補給後按開始鍵繼續掛機",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)

        # 聖光揭露偵測
        sf5=self._section(p,"聖光揭露卷軸偵測");sf5.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf5);r.pack(fill='x',pady=2)
        self._chk(r,"啟用（偵測驗證碼視窗 → 暫停+警報）",self.var_captcha_detect).pack(side='left')
        tk.Label(sf5,text="其他玩家可用聖光揭露卷軸觸發人機驗證\n偵測到驗證視窗後自動暫停 Bot 並發出警報音",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)

        # 地理圍欄
        sf6=self._section(p,"地理圍欄（練功範圍限制）");sf6.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf6);r.pack(fill='x',pady=2)
        self._chk(r,"啟用",self.var_geofence_en).pack(side='left')
        self._lbl(r,"半徑:").pack(side='left',padx=(8,1))
        self._spin(r,self.var_geofence_radius,3,30,w=3).pack(side='left')
        self._lbl(r,"% 小地圖").pack(side='left')
        tk.Label(sf6,text="以啟動位置為中心，限制練功範圍\n超出範圍自動走回，用小地圖座標判定",
                 bg=BG2,fg='#888',font=FONTS).pack(anchor='w',padx=5)

    # ═══ 安全頁 ═══
    def _build_safety(self):
        p=self.pages['安全']

        # 擬人化防偵測
        sf=self._section(p,"擬人化防偵測");sf.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"隨機延遲（所有操作 ±20% 擾動）",self.var_humanize).pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._chk(r,"定期停頓（模擬 AFK）",self.var_human_pause).pack(side='left')
        self._lbl(r,"每").pack(side='left',padx=(8,1))
        self._spin(r,self.var_human_pause_min,5,60,w=3).pack(side='left')
        self._lbl(r,"分鐘停").pack(side='left')
        self._spin(r,self.var_human_pause_sec,3,30,w=3).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=2)
        self._lbl(r,"最大運行時數:").pack(side='left')
        self._spin(r,self.var_max_hours,0,24,w=4,inc=0.5).pack(side='left')
        self._lbl(r,"小時（0=無限）").pack(side='left')
        tk.Label(sf,text="NCSoft 會分析行為模式：固定間隔、24小時不停等\n建議開啟隨機延遲 + 定期停頓，配合 ATS 3小時時段",
                 bg=BG2,fg='#666',font=FONTS).pack(anchor='w',padx=5,pady=3)

        # 其他防護
        sf2=self._section(p,"其他防護");sf2.pack(fill='x',padx=10,pady=5)
        r=self._frame(sf2);r.pack(fill='x',pady=2)
        self._chk(r,"斷線偵測 + 警示音",self.var_dc_detect).pack(side='left')
        r=self._frame(sf2);r.pack(fill='x',pady=2)
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

        # 更新（獨立一行）
        r=self._frame(sf2);r.pack(fill='x',pady=5)
        tk.Button(r,text=">>> 檢查更新 <<<",font=(_UI_FONT,10,'bold'),bg='#e67e22',fg='white',command=self._check_update).pack(side='left',padx=3)
        self._lbl(r,f"v{BOT_VERSION}").pack(side='left',padx=8)
        self.update_lbl=tk.Label(r,text="",bg=BG2,fg='#2ecc71',font=FONTS)
        self.update_lbl.pack(side='left',padx=4)

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
        import json as _json
        app_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            # 1. 從 GitHub Releases API 取得最新版本
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'LineageBot'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                release = _json.loads(resp.read().decode('utf-8'))

            remote_ver = release.get('tag_name', '').lstrip('v')
            if not remote_ver:
                self.root.after(0, lambda: self.update_lbl.config(text="檢查失敗", fg='#e74c3c'))
                return

            if remote_ver == BOT_VERSION:
                self.root.after(0, lambda: self.update_lbl.config(
                    text=f"已是最新版 v{BOT_VERSION}", fg='#2ecc71'))
                self.root.after(0, lambda: self.log("已是最新版本"))
                return

            self.root.after(0, lambda: self.log(f"發現新版 v{remote_ver}，開始下載..."))
            updated = []

            # 2. 下載 exe（從 Release assets）
            for asset in release.get('assets', []):
                if asset['name'] == 'LineageBot.exe':
                    exe_url = asset['browser_download_url']
                    exe_new = os.path.join(app_dir, 'LineageBot.exe.new')
                    self.root.after(0, lambda: self.log("下載 LineageBot.exe..."))
                    req = urllib.request.Request(exe_url, headers={'User-Agent': 'LineageBot'})
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        with open(exe_new, 'wb') as f:
                            f.write(resp.read())
                    updated.append('LineageBot.exe')
                    break

            # 3. 下載 py 檔
            base_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{UPDATE_BRANCH}"
            for fname in ['lineage_bot.py', 'lineage_data.py']:
                try:
                    url = f"{base_url}/{fname}"
                    req = urllib.request.Request(url, headers={'User-Agent': 'LineageBot'})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        content = resp.read()
                    if len(content) < 100:
                        continue
                    fpath = os.path.join(app_dir, fname)
                    tmp = fpath + '.new'
                    with open(tmp, 'wb') as f:
                        f.write(content)
                    try: os.replace(tmp, fpath)
                    except:
                        import shutil; shutil.copy2(tmp, fpath)
                        try: os.remove(tmp)
                        except: pass
                    updated.append(fname)
                except:
                    pass

            # 4. 寫 version.txt
            with open(os.path.join(app_dir, 'version.txt'), 'w') as f:
                f.write(f"v{remote_ver}")

            if updated:
                exe_new = os.path.join(app_dir, 'LineageBot.exe.new')
                exe_dst = os.path.join(app_dir, 'LineageBot.exe')

                # 寫替換腳本
                bat = os.path.join(app_dir, '_apply_update.bat')
                with open(bat, 'w') as f:
                    f.write('@echo off\n')
                    f.write('echo Updating...\n')
                    f.write('timeout /t 3 /nobreak >nul\n')
                    f.write(f'if exist "{exe_new}" (\n')
                    f.write(f'  del /f "{exe_dst}" 2>nul\n')
                    f.write(f'  move /y "{exe_new}" "{exe_dst}"\n')
                    f.write(f')\n')
                    f.write(f'start "" "{exe_dst}"\n')
                    f.write('del "%~f0"\n')

                self.root.after(0, lambda: self.update_lbl.config(
                    text=f"v{BOT_VERSION} -> v{remote_ver}", fg='#e74c3c'))
                self.root.after(0, lambda: self.log(f"已更新: {', '.join(updated)}"))

                def auto_restart():
                    import tkinter.messagebox
                    tkinter.messagebox.showinfo("更新完成",
                        f"v{BOT_VERSION} -> v{remote_ver}\n程式將自動重啟")
                    # 啟動替換腳本，然後關閉自己
                    import subprocess
                    subprocess.Popen(f'cmd /c "{bat}"', shell=True,
                                     creationflags=0x00000008)  # DETACHED_PROCESS
                    self.running = False
                    self.root.destroy()
                    sys.exit(0)
                self.root.after(0, auto_restart)
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
        for m in ['近戰','遠程','定點','純定點','墮落之地','召喚','隊伍']:
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
        # 純定點
        f=self._section(p,"純定點設定");self.mode_frames['純定點']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"攻擊鍵:").pack(side='left')
        self._combo(r,self.var_rng_key,FKEYS,w=3).pack(side='left')
        tk.Label(f,text="掃描+射箭+喝水，絕不點地面移動\n滑鼠掃描較慢，確保穩定性",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)
        # 墮落之地
        f=self._section(p,"墮落之地特化");self.mode_frames['墮落之地']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"攻擊鍵:").pack(side='left')
        self._combo(r,self.var_rng_key,FKEYS,w=3).pack(side='left')
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._chk(r,"定時往上走",self.var_fallen_walk_en).pack(side='left')
        self._lbl(r,"每").pack(side='left',padx=(4,1))
        self._spin(r,self.var_fallen_walk_min,1,30,w=3).pack(side='left')
        self._lbl(r,"分鐘").pack(side='left')
        self._lbl(r,"  點").pack(side='left')
        self._spin(r,self.var_fallen_walk_sec,3,30,w=3).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        tk.Label(f,text="掃描重心偏上方，掃完回上方待命\n定時往上走：每隔N分鐘點擊地圖上方移動",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)
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
    def _click_hotbar_current(self, slot_key, clicks=2):
        """用目前視窗座標點快捷欄（給 SkillSystem 等外部呼叫用）"""
        rect = getattr(self, '_cur_rect', None)
        if not rect:
            g = find_game()
            if not g: return False
            rect = get_rect(g[0])
        return self._click_hotbar(*rect, slot_key, clicks)

    def _set_state(self, new_state):
        """安全的狀態轉換"""
        old = getattr(self, 'bot_state', BotState.IDLE)
        if new_state in VALID_TRANSITIONS.get(old, []):
            self.bot_state = new_state
            return True
        # 強制允許回到 IDLE 和 SCANNING
        if new_state in (BotState.IDLE, BotState.SCANNING):
            self.bot_state = new_state
            return True
        return False

    def log(self,msg):
        self._last_activity = time.time()  # 看門狗用
        ts=time.strftime("%H:%M:%S")
        def _u():
            self.log_w.config(state='normal');self.log_w.insert('end',f"[{ts}] {msg}\n")
            self.log_w.see('end');self.log_w.config(state='disabled')
        self.root.after(0,_u)

    def _bar(self,cv,tl,pct,w=200,cur=0,mx=0):
        def _u():
            p=max(0,min(1,pct));cv.delete('all')
            cv.create_rectangle(0,0,w,22,fill='#111',outline='')
            c=ACC if p<0.3 else('#f5a623' if p<0.6 else'#27ae60')
            cv.create_rectangle(0,0,int(w*p),22,fill=c,outline='')
            # 條上面顯示百分比文字
            cv.create_text(w//2,11,text=f"{p*100:.0f}%",fill='white',font=('Consolas',9,'bold'))
            tl.config(text=f"{p*100:.0f}%")
        self.root.after(0,_u)

    def _stats(self):
        def _u():
            state = getattr(self, 'bot_state', BotState.IDLE).value
            self.stat_lbl.config(text=f"[{state}] 殺:{self.kills} 紅:{self.pots} 藍:{self.mpots} 治:{self.heals} B:{self.buffs} 撿:{self.loots}")
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
            # 更新導航欄狀態
            state = getattr(self, 'bot_state', BotState.IDLE).value.upper()
            self.nav_state_lbl.config(text=state, fg='#27ae60' if self.running else '#555')
        self.root.after(0,_u)

    def _toggle(self):
        if self.running:
            self.running=False;self._status("已停止");self.log("Bot 暫停");save_cfg(self)
        else:
            self.running=True;self.t0=time.time();self.bot_state=BotState.IDLE;self._status("運行中",'#27ae60');self.log("Bot 啟動")
            self._last_activity = time.time()
            skills.setup([(self.var_sk[i].get(),self.var_cd[i].get()) for i in range(7)],
                         hotbar_fn=self._click_hotbar_current)
            if not self.thread or not self.thread.is_alive():
                self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()
            self._tick()
            self._watchdog()

    def _watchdog(self):
        """看門狗：30秒沒活動就自動重啟"""
        if not self.running:
            return
        last = getattr(self, '_last_activity', time.time())
        if time.time() - last > 30:
            self.log("[看門狗] 30秒無活動，自動重啟！")
            # 重啟主迴圈
            if self.thread and self.thread.is_alive():
                pass  # 舊執行緒會因 try/except 自動結束
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            self._last_activity = time.time()
        self.root.after(5000, self._watchdog)  # 每 5 秒檢查一次

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

    def _get_hotbar_pos(self, cx, cy, cw, ch, slot_key):
        """取得快捷欄格子的螢幕座標 (F1-F12)
        上排: F1 F2 F3 F4 F5 F6 F7 F8
        下排: F9 F10 F11 F12
        F5在F9正上方, F1在F5左邊繼續延伸
        """
        right_edge = cx + cw - 10
        big_w = int(cw * 0.052)
        bottom_y = cy + int(ch * 0.91)
        top_y = bottom_y - int(ch * 0.060)

        # F12→F9 的 X 位置（從右往左）
        x12 = right_edge - big_w // 2
        x_map = {12: x12, 11: x12 - big_w, 10: x12 - big_w*2, 9: x12 - big_w*3}
        # 上排 F5-F8 跟下排 F9-F12 同 X
        x_map[5] = x_map[9]
        x_map[6] = x_map[10]
        x_map[7] = x_map[11]
        x_map[8] = x_map[12]
        # 上排 F1-F4 在 F5 左邊繼續延伸
        x_map[4] = x_map[5] - big_w
        x_map[3] = x_map[5] - big_w * 2
        x_map[2] = x_map[5] - big_w * 3
        x_map[1] = x_map[5] - big_w * 4

        # 解析 slot_key（"F5" → 5）
        try:
            num = int(slot_key.upper().replace('F', ''))
        except:
            return None
        if num not in x_map:
            return None

        y = top_y if num <= 8 else bottom_y
        return (x_map[num], y)

    def _click_hotbar(self, cx, cy, cw, ch, slot_key, clicks=2):
        """點擊快捷欄格子 — 狀態機保護，不會跟攻擊衝突"""
        pos = self._get_hotbar_pos(cx, cy, cw, ch, slot_key)
        if not pos:
            return False

        # 記住之前的狀態，切換到 DRINKING
        prev_state = getattr(self, 'bot_state', BotState.IDLE)
        self._set_state(BotState.DRINKING)

        x, y = pos
        # 確保滑鼠完全放開（攻擊拖曳可能還在）
        game_up()
        time.sleep(0.2)
        # 移到快捷欄
        move_exact(x, y)
        time.sleep(0.25)
        # 連點
        for i in range(clicks):
            game_click()
            if i < clicks - 1:
                time.sleep(0.12)
        time.sleep(0.15)
        # 回到怪物位置
        if hasattr(self, '_combat_monster') and self._combat_monster:
            mx, my = self._combat_monster
            move_exact(mx, my)

        # 恢復之前的狀態
        self._set_state(prev_state)
        return True

    def _check_survival(self, hwnd, cx, cy, cw, ch, timers):
        """生存系統：HP/MP/治療/喝水/Buff — 每次循環都呼叫"""
        now = time.time()
        hp = mp = 1.0
        pixel_ok = False
        if self.var_ocr_en.get():
            try:
                hp = bars.hp(None, cx, cy, cw, ch)
                mp = bars.mp(None, cx, cy, cw, ch)
                # 校準成功且有合理值才算 pixel_ok
                if bars._calibrated and bars._hp_bar is not None and hp < 1.0:
                    pixel_ok = True
                self._bar(self.hp_cv, self.hp_tl, hp)
                if mp >= 0:
                    self._bar(self.mp_cv, self.mp_tl, mp)
            except:
                pass
        # debug：每 10 秒顯示 HP/MP 讀值，方便排查
        if not hasattr(self, '_last_hp_debug'):
            self._last_hp_debug = 0
        if now - self._last_hp_debug > 10:
            mode_str = "像素" if pixel_ok else "定時"
            self.log(f"[HP={hp*100:.0f}% MP={mp*100:.0f}% 模式={mode_str} | {getattr(bars,'_last_ocr_text','')}]")
            self._last_hp_debug = now

        # Buff（不需要 HP 值，定時觸發）
        if self.var_buff_en.get() and now - timers['buff'] > self.var_buff_sec.get():
            k = self.var_buff_key.get()
            self._click_hotbar(cx, cy, cw, ch, k, clicks=5)  # 法術類5下
            time.sleep(0.3)
            timers['buff'] = now
            self.buffs += 1
            self.log(f"喝綠水({k})")

        # 死亡（僅在像素偵測正常時判定，避免誤判）
        if pixel_ok and hp <= 0.01:
            self._handle_death(hwnd, cx, cy, cw, ch, timers)
            return hp, mp

        # 緊急回城（最高優先，僅在 HP 成功讀取時觸發）
        if self.var_recall_en.get() and hp >= 0 and hp < self.var_recall_thr.get() / 100:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            self._click_hotbar(cx, cy, cw, ch, self.var_recall_key.get(), clicks=2)
            self.log(f"緊急回城！HP={hp*100:.0f}%")
            alert('hp')
            # 不停止 bot，等待回城後可以重播路徑回來
            time.sleep(5)
            return hp, mp

        # 治癒術（HP 低於閾值 / OCR 關閉時定時施放）
        hp_thr = self.var_hp_thr.get() / 100
        mp_thr = self.var_mp_thr.get() / 100
        heal_thr = self.var_heal_thr.get() / 100

        heal_trigger = (pixel_ok and hp < heal_thr) \
                       or (not pixel_ok and now - timers['heal'] > self.var_heal_sec.get())
        if self.var_heal_en.get() and heal_trigger and now - timers['heal'] > 3:
            k = self.var_heal_key.get()
            for _ in range(self.var_heal_n.get()):
                self._click_hotbar(cx, cy, cw, ch, k, clicks=5)
                time.sleep(0.3)
            timers['heal'] = now
            self.heals += 1
            self.log(f"治癒術({k}) HP={hp*100:.0f}%")

        # 紅水 — 像素偵測有效用比例，無效用定時
        if pixel_ok:
            need_hp = hp < hp_thr
        else:
            need_hp = now - timers['hp'] > self.var_hp_sec.get()
        if self.var_hp_en.get() and need_hp and now - timers['hp'] > 4:
            k = self.var_hp_key.get()
            self._click_hotbar(cx, cy, cw, ch, k)
            timers['hp'] = now
            self.pots += 1
            if pixel_ok:
                self.log(f"喝紅水({k}) HP={hp*100:.0f}%")
            else:
                self.log(f"喝紅水({k}) 定時")

        # 藍水
        if pixel_ok:
            need_mp = mp < mp_thr
        else:
            need_mp = now - timers['mp'] > self.var_mp_sec.get()
        if self.var_mp_en.get() and need_mp and now - timers['mp'] > 4:
            k = self.var_mp_key.get()
            self._click_hotbar(cx, cy, cw, ch, k)
            timers['mp'] = now
            self.mpots += 1
            if pixel_ok:
                self.log(f"喝藍水({k}) MP={mp*100:.0f}%")
            else:
                self.log(f"喝藍水({k}) 定時")

        # Buff
        # 召喚重召喚
        mode = self.var_mode.get()
        if mode == '召喚' and now - timers['summon'] > self.var_sum_sec.get():
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            self._click_hotbar(cx, cy, cw, ch, self.var_sum_key.get(), clicks=4)
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
                    self._click_hotbar(cx, cy, cw, ch, tkey, clicks=2)
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
            self._click_hotbar(cx, cy, cw, ch, self.var_rng_key.get(), clicks=4)
            # 風箏走位（後退保持距離）
            if self.var_rng_kite.get():
                sh = int(ch * 0.75)
                d = self.var_rng_dist.get()
                dx, dy = cx + cw // 2 - mx, cy + sh // 2 - my
                dd = max(1, math.sqrt(dx * dx + dy * dy))
                sx = max(cx + 50, min(cx + cw - 50, mx + int(dx / dd * d)))
                sy = max(cy + 30, min(cy + sh - 30, my + int(dy / dd * d)))
                move_exact(sx, sy)
                game_click(sx, sy)
        elif mode in ('定點', '純定點', '墮落之地'):
            # 定點：點攻擊鍵快捷欄 → 移到怪物 → 按住 → 拖曳 → 放開
            self._click_hotbar(cx, cy, cw, ch, self.var_rng_key.get(), clicks=4)
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
            self._click_hotbar(cx, cy, cw, ch, self.var_sum_atk.get(), clicks=4)
            sh = int(ch * 0.75)
            move_exact(cx + cw // 2, cy + sh // 2)
            game_click()
        elif mode == '隊伍':
            role = self.var_pt_role.get()
            if role in ('坦克', '輸出'):
                attack(mx, my, cx, cy, cw, ch)
            elif role == '補師':
                self._click_hotbar(cx, cy, cw, ch, self.var_pt_heal.get(), clicks=4)
            elif role == '輔助':
                self._click_hotbar(cx, cy, cw, ch, self.var_pt_buff.get(), clicks=4)
                attack(mx, my, cx, cy, cw, ch)

    def _combat_skill(self):
        """戰鬥中持續施放技能（用鍵盤，不動滑鼠）"""
        mode = self.var_mode.get()
        if mode == '近戰':
            skills.use_next()
        elif mode in ('遠程', '定點', '純定點', '墮落之地'):
            press_key(self.var_rng_key.get())
        elif mode == '召喚':
            press_key(self.var_sum_atk.get())
        elif mode == '隊伍' and self.var_pt_role.get() == '補師':
            press_key(self.var_pt_heal.get())

    # ═══ 新功能：死亡復活 / 防PK / 畫面差異偵測 / 回城補給 ═══

    def _handle_death(self, hwnd, cx, cy, cw, ch, timers):
        """死亡處理：天堂經典版死亡後角色自動傳回村莊
        流程：偵測死亡 → 等待回村 → 喝水Buff → 重播路徑回練功點 or 暫停
        （不需要點復活按鈕，遊戲自動回村）
        """
        if not self.var_auto_rez.get():
            self.log("角色死亡！（自動復活未開啟）")
            alert('death')
            self.running = False
            self._status("死亡！", ACC)
            return False

        self._set_state(BotState.DEAD)
        self._status("死亡 — 回村中", '#e74c3c')
        self.log("角色死亡！等待自動回村...")
        alert('death')

        # 等待回村（遊戲會自動傳送，通常需要幾秒）
        delay = self.var_rez_delay.get()
        time.sleep(delay)

        if not self.running:
            return False

        # 重新取得視窗（回村後位置可能改變）
        g = find_game()
        if not g:
            self.running = False
            return False
        hwnd = g[0]
        cx, cy, cw, ch = get_rect(hwnd)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(1)

        self.log("已回村！重新 Buff...")

        # 回村後喝水 + Buff
        if self.var_buff_en.get():
            self._click_hotbar(cx, cy, cw, ch, self.var_buff_key.get(), clicks=5)
            timers['buff'] = time.time()
            time.sleep(0.5)

        # 重新校準 HP 條（村莊 UI 可能不同）
        bars._calibrated = False

        # 如果有錄製的路徑，自動重播回練功點
        if self.var_path_en.get() and path.pts:
            self.log("重播路徑回練功點...")
            self._status("回練功點", '#f5a623')
            path.play(cx, cy, cw, ch, hwnd)
            time.sleep(1)
            # 到達後重新記錄小地圖位置
            self.minimap_anchor = self._get_minimap_pos(cx, cy, cw, ch)
            self._set_state(BotState.SCANNING)
            self._status("復活完成，繼續掛機", '#27ae60')
        else:
            # 沒有路徑 → 暫停等使用者手動走回
            self.log("沒有錄製路徑，請手動走回練功點後按開始鍵")
            self._status("已回村 — 請手動走回練功點", '#e67e22')
            alert('dc')
            self.running = False

        return True

    def _check_pk(self, cx, cy, cw, ch):
        """防 PK 偵測：找畫面中的玩家名字（白字+深色均勻背景）
        回傳 True 如果偵測到玩家（非怪物）
        """
        if not self.var_antipk.get():
            return False

        # 冷卻檢查
        now = time.time()
        last_pk = getattr(self, '_last_pk_check', 0)
        if now - last_pk < self.var_pk_cooldown.get():
            return False

        try:
            sh = int(ch * 0.75)
            frame = grab_region(cx, cy, cw, sh)
            if frame is None:
                return False
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 高閾值二值化找白色文字
            _, white_mask = cv2.threshold(gray, 248, 255, cv2.THRESH_BINARY)

            # 排除角色中心
            ccx, ccy = cw // 2, sh // 2
            cv2.circle(white_mask, (ccx, ccy), 100, 0, -1)

            # 形態學：連接文字
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 5))
            closed = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            player_count = 0
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if w < 25 or w > 300 or h < 4 or h > 30:
                    continue

                # 背景分析：玩家名字有深色均勻背景
                pad = 5
                bg_y1, bg_y2 = max(0, y-pad), min(sh, y+h+pad)
                bg_x1, bg_x2 = max(0, x-pad), min(cw, x+w+pad)
                bg_region = gray[bg_y1:bg_y2, bg_x1:bg_x2].copy()
                text_mask = white_mask[bg_y1:bg_y2, bg_x1:bg_x2]
                bg_pixels = bg_region[text_mask == 0]

                if len(bg_pixels) < 10:
                    continue

                avg_bg = float(np.mean(bg_pixels))
                std_bg = float(np.std(bg_pixels))

                # 玩家名字特徵：深色均勻背景 (avg < 80, std < 30)
                if avg_bg < 80 and std_bg < 30:
                    player_count += 1

            if player_count > 0:
                self._last_pk_check = now
                return True

        except:
            pass
        return False

    def _frame_diff_detect(self, cx, cy, cw, ch):
        """畫面差異偵測：連續截兩幀比對，找移動區域
        回傳候選怪物位置列表 [(x, y), ...] 或空列表
        """
        try:
            sh = int(ch * 0.75)
            frame1 = grab_region(cx, cy, cw, sh)
            time.sleep(0.15)
            frame2 = grab_region(cx, cy, cw, sh)

            if frame1 is None or frame2 is None:
                return []

            # 灰度差異
            g1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
            g2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(g1, g2)

            # 閾值化：只保留明顯變化
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

            # 排除角色中心（自己的動畫）
            ccx, ccy = cw // 2, sh // 2
            cv2.circle(thresh, (ccx, ccy), 80, 0, -1)

            # 形態學去噪 + 連接
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

            # 找輪廓
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            candidates = []
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = w * h
                if area < 200 or area > 50000:  # 太小=噪點, 太大=鏡頭移動
                    continue
                # 轉換為螢幕絕對座標
                abs_x = cx + x + w // 2
                abs_y = cy + y + h // 2
                candidates.append((abs_x, abs_y, area))

            # 按面積排序
            candidates.sort(key=lambda c: -c[2])

            # 去重（距離太近的合併）
            filtered = []
            for x, y, a in candidates:
                if not any(abs(x-fx) < 60 and abs(y-fy) < 60 for fx, fy in filtered):
                    filtered.append((x, y))

            return filtered[:5]  # 最多 5 個候選
        except:
            return []

    def _check_supply(self, hwnd, cx, cy, cw, ch):
        """檢查是否需要回城補給
        回傳 True = 需要回城（已觸發回城流程）
        """
        if not self.var_supply_en.get():
            return False

        threshold = self.var_supply_count.get()
        total_used = self.pots + self.mpots

        if total_used < threshold:
            return False

        # 到達閾值 — 回城
        self._set_state(BotState.RESUPPLYING)
        self._status("回城補給中", '#f5a623')
        self.log(f"已喝 {total_used} 次水，回城補給！")
        alert('hp')

        # 點回城卷
        self._click_hotbar(cx, cy, cw, ch, self.var_recall_key.get(), clicks=2)
        time.sleep(8)  # 等待回城讀條

        self.log("已回城 — 請手動買補給，買完按開始鍵繼續")
        self._status("等待補給（按開始鍵繼續）", '#e67e22')

        # 重置計數器
        self.pots = 0
        self.mpots = 0

        # 暫停 bot，等使用者按開始鍵
        self.running = False
        return True

    def _check_captcha(self, cx, cy, cw, ch):
        """聖光揭露卷軸偵測：偵測畫面中央是否出現驗證碼對話框
        對話框特徵：畫面中央出現深色半透明遮罩 + 白色文字的彈窗
        """
        if not self.var_captcha_detect.get():
            return False

        # 每 5 秒檢查一次（避免太頻繁）
        now = time.time()
        if now - getattr(self, '_last_captcha_check', 0) < 5:
            return False
        self._last_captcha_check = now

        try:
            # 截取畫面中央區域（驗證碼對話框通常在中央）
            center_x = int(cw * 0.30)
            center_y = int(ch * 0.30)
            center_w = int(cw * 0.40)
            center_h = int(ch * 0.40)
            frame = grab_region(cx + center_x, cy + center_y, center_w, center_h)
            if frame is None:
                return False

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # TODO: 需要實際驗證碼截圖校準以下閾值
            # 目前用「畫面中央突然出現大片遮罩」作為粗略判斷
            # 比較前後兩次截圖的差異，避免誤判正常遊戲畫面
            dark_ratio = (gray < 60).sum() / gray.size
            white_ratio = (gray > 200).sum() / gray.size

            # 記錄基準值（正常遊戲畫面）
            if not hasattr(self, '_captcha_baseline'):
                self._captcha_baseline = dark_ratio
                return False

            # 與基準值比較：dark 突增 >25% 才觸發（排除正常 UI）
            dark_increase = dark_ratio - self._captcha_baseline
            if dark_increase > 0.25 and white_ratio > 0.02:
                self.log(f"[警告] 畫面異常變化（dark+{dark_increase:.0%}）可能是驗證碼！暫停 Bot")
                alert('pk')
                time.sleep(0.5)
                alert('pk')
                self.running = False
                self._status("驗證碼？請檢查遊戲畫面", '#e74c3c')
                return True
            else:
                # 更新基準值（緩慢追蹤，避免突變）
                self._captcha_baseline = self._captcha_baseline * 0.95 + dark_ratio * 0.05
        except:
            pass
        return False

    def _check_geofence(self, cx, cy, cw, ch, hwnd):
        """地理圍欄：檢查角色是否在允許範圍內
        用小地圖座標判定，超出範圍自動走回
        """
        if not self.var_geofence_en.get():
            return False
        if not hasattr(self, 'minimap_anchor') or self.minimap_anchor is None:
            return False

        current = self._get_minimap_pos(cx, cy, cw, ch)
        if current is None:
            return False

        dx = current[0] - self.minimap_anchor[0]
        dy = current[1] - self.minimap_anchor[1]
        drift = math.sqrt(dx * dx + dy * dy)

        radius = self.var_geofence_radius.get() / 100.0  # 轉為比例

        if drift > radius:
            self.log(f"超出圍欄（偏移{drift:.2f}>{radius:.2f}），走回定點")
            self._walk_back_to_anchor(cx, cy, cw, ch, hwnd)
            return True
        return False

    def _humanize_delay(self, base_sec):
        """擬人化延遲：在基礎延遲上加 ±20% 隨機擾動"""
        if self.var_humanize.get():
            jitter = base_sec * random.uniform(-0.20, 0.20)
            return max(0.01, base_sec + jitter)
        return base_sec

    def _check_human_pause(self, timers):
        """擬人化停頓：定期暫停模擬 AFK"""
        if not self.var_human_pause.get():
            return
        now = time.time()
        timer_key = 'human_pause'
        if timer_key not in timers:
            timers[timer_key] = now
        interval = self.var_human_pause_min.get() * 60
        if now - timers[timer_key] > interval:
            pause_sec = self.var_human_pause_sec.get() + random.uniform(-2, 2)
            pause_sec = max(1, pause_sec)
            self.log(f"擬人停頓 {pause_sec:.0f} 秒...")
            self._status("停頓中...", '#888')
            time.sleep(pause_sec)
            timers[timer_key] = now
            self.log("繼續掛機")

    def _check_dead_stuck(self, cx, cy, cw, ch, hwnd):
        """啟動 5 分鐘後，如果 HP=0 且畫面無移動 → 自動關閉遊戲"""
        if not self.var_dead_stuck.get():
            return False
        if not self.t0 or time.time() - self.t0 < 300:
            return False  # 還沒 5 分鐘

        hp = bars._hp_ratio
        if hp > 0.01:
            self._dead_stuck_count = 0
            return False

        # HP=0，檢查畫面是否靜止
        try:
            frame1 = grab_region(cx, cy, cw, int(ch * 0.75))
            time.sleep(1)
            frame2 = grab_region(cx, cy, cw, int(ch * 0.75))
            if frame1 is None or frame2 is None:
                return False
            diff = cv2.absdiff(
                cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY))
            motion = (diff > 20).sum()
            motion_ratio = motion / diff.size

            if motion_ratio < 0.005:  # 畫面幾乎沒動
                self._dead_stuck_count = getattr(self, '_dead_stuck_count', 0) + 1
                self.log(f"[警告] HP=0 + 畫面靜止 ({self._dead_stuck_count}/3)")
                if self._dead_stuck_count >= 3:
                    self.log("HP=0 且畫面無移動超過 3 次確認，關閉遊戲")
                    alert('death')
                    self.running = False
                    self._status("已關閉遊戲", '#e74c3c')
                    try:
                        import subprocess
                        subprocess.run(['taskkill', '/F', '/PID', str(
                            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(ctypes.c_ulong(0))) or 0
                        )], capture_output=True)
                    except:
                        pass
                    # 用 PID 方式關閉
                    try:
                        pid = ctypes.c_ulong(0)
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value:
                            import subprocess
                            subprocess.run(['taskkill', '/F', '/PID', str(pid.value)], capture_output=True)
                            self.log(f"已終止進程 PID={pid.value}")
                    except:
                        pass
                    return True
            else:
                self._dead_stuck_count = 0
        except:
            pass
        return False

    def _check_max_hours(self):
        """最大運行時數檢查"""
        max_h = self.var_max_hours.get()
        if max_h <= 0 or not self.t0:
            return False
        elapsed = (time.time() - self.t0) / 3600
        if elapsed >= max_h:
            self.log(f"已運行 {elapsed:.1f} 小時，達到上限 {max_h} 小時，自動停止")
            self.running = False
            self._status(f"時間到（{max_h}h）", '#f5a623')
            return True
        return False

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

        # 自動偵測手指游標 handle（純定點模式不需要）
        global CURSOR_FINGER
        if CURSOR_FINGER is None and self.var_mode.get() != '純定點':
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

        # 1. 立刻喝綠水（用滑鼠點快捷欄，鍵盤被遊戲擋）
        if self.var_buff_en.get():
            key = self.var_buff_key.get()
            self._click_hotbar(cx_s, cy_s, cw_s, ch_s, key, clicks=5)
            timers['buff'] = time.time()
            self.buffs += 1
            self.log(f"啟動喝綠水({key})")
            time.sleep(0.5)

        # 2. 小地圖需要手動開啟（Ctrl+M 鍵盤被遊戲擋）
        self.log("提示：請手動開啟小地圖 (Ctrl+M) 以啟用定點功能")
        time.sleep(0.3)

        # 3. 記錄小地圖上角色初始位置
        self.minimap_anchor = self._get_minimap_pos(cx_s, cy_s, cw_s, ch_s)
        if self.minimap_anchor:
            self.log(f"小地圖定點: {self.minimap_anchor}")
        else:
            self.log("小地圖定點記錄失敗")

        while True:
          try:
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
            self._cur_rect = (cx, cy, cw, ch)

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

            mode = self.var_mode.get()

            # ── 墮落之地定時北移 ──
            if mode == '墮落之地' and self.var_fallen_walk_en.get():
                timer_key = 'fallen_walk'
                if timer_key not in timers:
                    timers[timer_key] = time.time()
                interval = self.var_fallen_walk_min.get() * 60
                if time.time() - timers[timer_key] > interval:
                    walk_sec = self.var_fallen_walk_sec.get()
                    self._status("往上移動", '#f5a623')
                    self.log(f"墮落之地：往上走 {walk_sec} 秒")
                    upper_x = cx + cw // 2 + random.randint(-50, 50)
                    upper_y = cy + int(sh_scene * 0.15) + random.randint(-20, 20)
                    for _ in range(walk_sec):
                        if not self.running:
                            break
                        move_exact(upper_x + random.randint(-10, 10), upper_y + random.randint(-10, 10))
                        time.sleep(0.1)
                        game_click()
                        time.sleep(0.9)
                    timers[timer_key] = time.time()
                    self.log("北移完成，繼續掃描")

            # ── 自動練功循環 ──
            if not self.var_attack.get():
                time.sleep(0.5)
                continue

            mode = self.var_mode.get()
            self._status(f"掃描({mode})", '#f5a623')

            # 掃描：優先用畫面差異偵測（快），失敗再用螺旋掃描
            self._set_state(BotState.SCANNING)
            mon = None

            if self.var_fast_detect.get():
                candidates = self._frame_diff_detect(cx, cy, cw, ch)
                if candidates:
                    # 驗證候選：移游標過去看是不是怪物
                    for cand_x, cand_y in candidates:
                        move_exact(cand_x, cand_y)
                        time.sleep(0.05)
                        if get_cursor() != CURSOR_FINGER:
                            # 確認不是玩家（粉紅名字）
                            try:
                                name_area = grab_region(cand_x - 40, cand_y - 25, 80, 20)
                                if name_area is not None:
                                    r_ch = name_area[:,:,2].astype(int)
                                    g_ch = name_area[:,:,1].astype(int)
                                    pink = (r_ch > 150) & (g_ch < 120)
                                    if pink.sum() > 15:
                                        continue  # 玩家，跳過
                            except:
                                pass
                            # 找到怪物！攻擊
                            self.log(f"差異偵測→打！({cand_x},{cand_y})")
                            game_down()
                            time.sleep(0.08)
                            drag_y = min(cy + int(ch*0.75) - 20, cand_y + random.randint(150, 300))
                            for s in range(1, 6):
                                move_exact(cand_x + random.randint(-10,10),
                                           cand_y + (drag_y - cand_y) * s // 5)
                                time.sleep(0.02)
                            game_up()
                            mon = (cand_x, cand_y)
                            break

            # Fallback：螺旋掃描
            if not mon:
                mon = scan_and_attack(cx, cy, cw, ch, hwnd, self.log, mode=mode)

            if mon and self.running:
                mx, my = mon
                self._combat_monster = (mx, my)  # 記錄怪物位置（喝水後回來用）
                no_monster_count = 0
                self._status(f"戰鬥({mode})", ACC)

                # 遠程/定點/召喚模式的額外技能
                if mode in ('定點', '純定點', '墮落之地'):
                    # 定點：先按攻擊鍵 → 再點擊怪物+短拖曳
                    self._do_attack(mx, my, cx, cy, cw, ch, hwnd)
                elif mode == '遠程':
                    self._click_hotbar(cx, cy, cw, ch, self.var_rng_key.get(), clicks=4)
                elif mode == '召喚':
                    self._click_hotbar(cx, cy, cw, ch, self.var_sum_atk.get(), clicks=4)

                time.sleep(0.2)

                # ── 啟動預掃描（戰鬥中同時找下一隻怪） ──
                pre_scanner.start(cx, cy, cw, ch, hwnd, exclude=(mx, my))

                # ── 戰鬥等待（雙重偵測：HP條+游標，30ms級反應） ──
                self._set_state(BotState.ATTACKING)
                combat_start = time.time()
                stuck_time = self.var_stuck.get()
                retry_attack = 0
                last_skill = last_surv = 0
                killed = False
                hp_bar_gone_count = 0

                while time.time() - combat_start < stuck_time and self.running:
                    now = time.time()

                    # 生存檢查（每 1.5 秒，暫停攻擊狀態讓喝水可以執行）
                    if now - last_surv > 1.5:
                        self._set_state(BotState.SCANNING)  # 暫時解鎖
                        hp, mp = self._check_survival(hwnd, cx, cy, cw, ch, timers)
                        self._set_state(BotState.ATTACKING)  # 恢復
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

                    time.sleep(self._humanize_delay(0.17))

                # 停止預掃描，取得結果
                pre_scanner.stop()
                next_mon = pre_scanner.get()

                self._combat_monster = None  # 戰鬥結束清除怪物位置
                self._set_state(BotState.SCANNING)
                if killed:
                    self.kills += 1
                    self.log(f"擊殺！(#{self.kills})")
                    self._stats()

                    # 定點模式不回定點（角色本來就不動）

                    # 快速撿物（定點模式不撿）
                    if self.var_loot.get() and mode not in ('定點','純定點','墮落之地') and self.running:
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

                if self.running and self.var_roam.get() and mode not in ('定點','純定點','墮落之地'):
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

            # ── 附加檢查（不影響打怪主迴圈）──
            if self.running:
                self._check_dead_stuck(cx, cy, cw, ch, hwnd)
                self._check_max_hours()
                self._check_captcha(cx, cy, cw, ch)
                self._check_human_pause(timers)
                self._check_geofence(cx, cy, cw, ch, hwnd)
                if self._check_pk(cx, cy, cw, ch):
                    act = self.var_pk_act.get()
                    self.log(f"偵測到玩家！動作: {act}")
                    alert('pk')
                    if act == '回城':
                        self._click_hotbar(cx, cy, cw, ch, self.var_recall_key.get(), clicks=2)
                        time.sleep(self._humanize_delay(5))
                    elif act == '逃跑':
                        roam(cx, cy, cw, ch, hwnd, 400)
                if self.running:
                    self._check_supply(hwnd, cx, cy, cw, ch)

          except Exception as e:
            self.log(f"[錯誤] {e} — 自動恢復")
            time.sleep(1)
            continue

    def run(self):self.log("就緒");self.root.mainloop()

if __name__=="__main__":BotApp().run()
