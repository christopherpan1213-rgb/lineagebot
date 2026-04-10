"""
天堂經典版 Bot v14 — 狀態機架構
全 Interception 驅動 + OpenCV 怪物偵測 + DXcam 高速截圖 + 狀態機防衝突
"""
BOT_VERSION = "16.3"
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
    IDLE = "idle"           # 等待/未啟動
    SCANNING = "scanning"   # 螺旋掃描找怪
    ATTACKING = "attacking" # 戰鬥中（滑鼠鎖定在怪物）
    DRINKING = "drinking"   # 點快捷欄喝水/治癒（滑鼠在快捷欄）
    WALKING = "walking"     # 墮落之地北移（滑鼠在地圖上方）
    LOOTING = "looting"     # 撿物

# 合法的狀態轉換
VALID_TRANSITIONS = {
    BotState.IDLE:      [BotState.SCANNING, BotState.DRINKING],
    BotState.SCANNING:  [BotState.ATTACKING, BotState.DRINKING, BotState.IDLE, BotState.WALKING],
    BotState.ATTACKING: [BotState.SCANNING, BotState.DRINKING, BotState.LOOTING, BotState.IDLE],
    BotState.DRINKING:  [BotState.SCANNING, BotState.ATTACKING, BotState.IDLE],
    BotState.WALKING:   [BotState.SCANNING, BotState.DRINKING, BotState.IDLE],
    BotState.LOOTING:   [BotState.SCANNING, BotState.DRINKING, BotState.IDLE],
}

# 截圖引擎：優先 DXcam，fallback MSS
try:
    import dxcam
    _dxcam = dxcam.create(output_color="BGR")
    HAS_DXCAM = True
except:
    from mss import mss
    HAS_DXCAM = False

# OCR 引擎：EasyOCR（懶載入）
_ocr_reader = None
def get_ocr():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(['ch_tra', 'en'], gpu=False, verbose=False)
    return _ocr_reader

# 輸入引擎：優先 Interception
try:
    import interception; interception.auto_capture_devices(mouse=True, keyboard=True); HAS_INTERCEPTION = True
except: HAS_INTERCEPTION = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'bot_config.json')
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)
PROFILES_DIR = CONFIG_DIR  # 向後兼容
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
    """HP/MP 條讀取 — 像素偵測 + OCR 雙軌
    """
    def __init__(self):
        self.ok = True
        self._hp_ratio = -1.0   # -1 = 從未成功讀取
        self._mp_ratio = -1.0
        self._hp_ever_read = False  # 是否曾經成功讀過 HP
        self._mp_ever_read = False
        self._hp_cur = 0    # 目前 HP
        self._hp_max = 0    # 最大 HP
        self._mp_cur = 0    # 目前 MP
        self._mp_max = 0    # 最大 MP
        self._last_ocr = 0
        self._ocr_interval = 3  # 秒
        # exe 打包後 __file__ 指向暫存目錄，改用 exe 所在目錄
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self._ocr_script = os.path.join(base_dir, 'win_ocr.ps1')

    def _ocr_region(self, cx, cy, cw, ch, x_pct, w_pct, y_pct, h_pct):
        """截取指定區域，放大後 OCR 回傳文字"""
        try:
            bx = int(cw * x_pct)
            bw = int(cw * w_pct)
            by = int(ch * y_pct)
            bh = int(ch * h_pct)
            frame = grab_region(cx + bx, cy + by, bw, bh)
            if frame is None or frame.size == 0:
                return ""
            # 根據圖片大小決定放大倍率（太大會卡 OCR）
            scale = max(2, min(6, 800 // max(frame.shape[0], 1)))
            big = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            tmp = os.path.join(os.environ.get('TEMP', '.'), '_ocr_tmp.png')
            cv2.imwrite(tmp, big)
            import subprocess
            r = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-File', self._ocr_script, tmp],
                capture_output=True, text=True, timeout=8
            )
            try: os.remove(tmp)
            except: pass
            return r.stdout.strip()
        except:
            return ""

    def _parse_bar(self, text, bar='hp'):
        """從 OCR 文字解析 HP 或 MP 數值"""
        if not text:
            return False
        import re
        text = text.replace('O', '0').replace('o', '0').replace('l', '1').replace('I', '1')
        nums = re.findall(r'\d+', text)
        if len(nums) >= 2:
            cur = int(nums[-2])
            mx = int(nums[-1])
            if 0 < mx <= 99999 and 0 <= cur <= mx:
                if bar == 'hp':
                    self._hp_cur, self._hp_max = cur, mx
                    self._hp_ratio = cur / mx
                else:
                    self._mp_cur, self._mp_max = cur, mx
                    self._mp_ratio = cur / mx
                return True
        return False

    def _calibrate_positions(self, cx, cy, cw, ch):
        """自動搜尋 HP/MP 條位置 — 只截一次大圖 OCR"""
        try:
            # 截底部 25% 整張，一次 OCR 找 HP 和 MP
            # 只截中間 60% 寬度的底部 20%（避免截太大卡住 OCR）
            text = self._ocr_region(cx, cy, cw, ch, 0.20, 0.60, 0.78, 0.18)
            if not text:
                return False
            import re
            text_clean = text.replace('O','0').replace('o','0').replace('l','1').replace('I','1')
            hp_match = re.search(r'[Hh][Pp]\s*[:\s]\s*(\d+)\s*[/\\|\s]\s*(\d+)', text_clean)
            if hp_match:
                cur, mx = int(hp_match.group(1)), int(hp_match.group(2))
                if 0 < mx <= 99999 and 0 <= cur <= mx:
                    self._hp_cur, self._hp_max = cur, mx
                    self._hp_ratio = cur / mx
                    self._hp_pos = True  # 標記已校準
            mp_match = re.search(r'[Mm][Pp]\s*[:\s]\s*(\d+)\s*[/\\|\s]\s*(\d+)', text_clean)
            if mp_match:
                cur, mx = int(mp_match.group(1)), int(mp_match.group(2))
                if 0 < mx <= 99999 and 0 <= cur <= mx:
                    self._mp_cur, self._mp_max = cur, mx
                    self._mp_ratio = cur / mx
                    self._mp_pos = True
            return self._hp_ratio < 1.1
        except:
            return False

    def _bg_ocr(self, cx, cy, cw, ch):
        """背景執行緒：一次 OCR 底部 25%，同時讀 HP 和 MP"""
        try:
            # 只截中間 60% 寬度的底部 20%（避免截太大卡住 OCR）
            text = self._ocr_region(cx, cy, cw, ch, 0.20, 0.60, 0.78, 0.18)
            if text:
                self._last_ocr_text = text
                import re
                text_clean = text.replace('O','0').replace('o','0').replace('l','1').replace('I','1')
                hp_match = re.search(r'[Hh][Pp]\s*[:\s]\s*(\d+)\s*[/\\|\s]\s*(\d+)', text_clean)
                if hp_match:
                    cur, mx = int(hp_match.group(1)), int(hp_match.group(2))
                    if 0 < mx <= 99999 and 0 <= cur <= mx:
                        self._hp_cur, self._hp_max = cur, mx
                        self._hp_ratio = cur / mx
                        self._hp_pos = True
                mp_match = re.search(r'[Mm][Pp]\s*[:\s]\s*(\d+)\s*[/\\|\s]\s*(\d+)', text_clean)
                if mp_match:
                    cur, mx = int(mp_match.group(1)), int(mp_match.group(2))
                    if 0 < mx <= 99999 and 0 <= cur <= mx:
                        self._mp_cur, self._mp_max = cur, mx
                        self._mp_ratio = cur / mx
                        self._mp_pos = True
        except:
            pass
        self._ocr_busy = False

    def _update(self, cx, cy, cw, ch):
        """啟動背景 OCR（非阻塞）"""
        now = time.time()
        if now - self._last_ocr < self._ocr_interval:
            return
        if getattr(self, '_ocr_busy', False):
            # OCR 卡超過 15 秒，強制解鎖
            if now - self._last_ocr > 15:
                self._ocr_busy = False
                self._ocr_fails = getattr(self, '_ocr_fails', 0) + 1
            else:
                return
        # OCR 連續失敗 3 次，加長間隔避免一直卡
        if getattr(self, '_ocr_fails', 0) >= 3:
            self._ocr_interval = 15  # 放慢到 15 秒一次
        self._last_ocr = now
        self._ocr_busy = True
        threading.Thread(target=self._bg_ocr, args=(cx, cy, cw, ch), daemon=True).start()

    def _load_pixel_config(self):
        """讀取 hp_config.json（由 hp_monitor.py 校準工具產生）"""
        try:
            cfg_path = os.path.join(SCRIPT_DIR, 'hp_config.json')
            with open(cfg_path) as f:
                data = json.load(f)
            self._pixel_hp_bar = tuple(data['hp_bar']) if 'hp_bar' in data else None
            self._pixel_mp_bar = tuple(data['mp_bar']) if 'mp_bar' in data else None
            return self._pixel_hp_bar is not None
        except:
            self._pixel_hp_bar = None
            self._pixel_mp_bar = None
            return False

    def _read_pixel_bar(self, cx, cy, cw, ch, bar_info, bar_type='hp'):
        """讀取 HP/MP 條比例 — 用紅色像素總數 / 滿血像素總數
        校準時記錄的是滿血時的位置，所以滿血時的紅色像素數就是 100%
        """
        if not bar_info:
            return None
        x1_pct, x2_pct, y_pct = bar_info
        y = int(ch * y_pct)
        x_start = max(0, int(cw * x1_pct))
        x_end = min(cw, int(cw * x2_pct))
        region_w = x_end - x_start
        if region_w < 10:
            return None
        try:
            # 截取 HP 條區域（上下各 2px）
            frame = grab_region(cx + x_start, cy + y - 2, region_w, 5)
            if frame is None or frame.size == 0:
                return None

            r = frame[:,:,2].astype(int)
            g = frame[:,:,1].astype(int)
            b = frame[:,:,0].astype(int)

            if bar_type == 'hp':
                # 紅色：R>80 且 R 明顯大於 G 和 B
                fill_mask = (r > 80) & ((r - g) > 20) & ((r - b) > 30)
            else:
                # 藍色：B>80 且 B 明顯大於 R
                fill_mask = (b > 80) & ((b - r) > 15)

            # 每行紅色像素佔比
            ratios = []
            for row in range(frame.shape[0]):
                count = fill_mask[row].sum()
                if count > 3:  # 有效行
                    ratios.append(count / region_w)

            if not ratios:
                return 0.0

            # 取中位數
            ratio = float(np.median(ratios))

            # 記錄滿血時的最大比例（第一次讀到的最大值就是 100%）
            max_key = f'_max_{bar_type}'
            prev_max = getattr(self, max_key, 0)
            if ratio > prev_max:
                setattr(self, max_key, ratio)
            max_ratio = getattr(self, max_key, ratio)

            # 歸一化：當前比例 / 最大比例
            if max_ratio > 0.01:
                return min(1.0, ratio / max_ratio)
            return ratio
        except:
            return None

    def _auto_find_bars(self, cx, cy, cw, ch):
        """自動搜尋 HP/MP 條位置（不需要校準檔）
        天堂的 HP/MP 條在畫面底部 UI 區域，紅色=HP，藍色=MP
        """
        if getattr(self, '_auto_found', False):
            return
        try:
            # 截取底部 30% 區域
            bottom_y = int(ch * 0.70)
            bottom_h = ch - bottom_y
            frame = grab_region(cx, cy + bottom_y, cw, bottom_h)
            if frame is None or frame.size == 0:
                return

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            h_ch, s_ch, v_ch = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]

            # 找紅色橫條（HP）：R>80, R-G>30, R-B>40（用 RGB 更直接）
            r_ch = frame[:,:,2].astype(int)
            g_ch2 = frame[:,:,1].astype(int)
            b_ch = frame[:,:,0].astype(int)
            red_mask = ((r_ch > 80) & ((r_ch - g_ch2) > 30) & ((r_ch - b_ch) > 40)).astype(np.uint8)

            # 找最長的紅色橫條
            best_hp_y = None
            best_hp_len = 0
            best_hp_x1 = 0
            best_hp_x2 = 0
            min_bar = int(cw * 0.05)   # HP 條至少 5% 寬
            max_bar = int(cw * 0.25)   # HP 條最多 25% 寬
            for row_y in range(frame.shape[0]):
                red_cols = np.where(red_mask[row_y] > 0)[0]
                if len(red_cols) < 20:
                    continue
                # 找最長連續段
                x1, x2 = red_cols[0], red_cols[-1]
                run_len = x2 - x1
                if run_len > best_hp_len and min_bar < run_len < max_bar:
                    best_hp_len = run_len
                    best_hp_y = row_y
                    best_hp_x1 = x1
                    best_hp_x2 = x2

            if best_hp_y is not None and best_hp_len > 20:
                # 轉換為全視窗比例
                abs_y = (bottom_y + best_hp_y) / ch
                x1_pct = best_hp_x1 / cw
                x2_pct = best_hp_x2 / cw
                self._pixel_hp_bar = (x1_pct, x2_pct, abs_y)

            # 找藍色橫條（MP）：B>80, B-R>20
            blue_mask = ((b_ch > 80) & ((b_ch - r_ch) > 20)).astype(np.uint8)
            best_mp_y = None
            best_mp_len = 0
            best_mp_x1 = 0
            best_mp_x2 = 0
            for row_y in range(frame.shape[0]):
                blue_cols = np.where(blue_mask[row_y] > 0)[0]
                if len(blue_cols) < 20:
                    continue
                x1, x2 = blue_cols[0], blue_cols[-1]
                run_len = x2 - x1
                if run_len > best_mp_len and min_bar < run_len < max_bar:
                    best_mp_len = run_len
                    best_mp_y = row_y
                    best_mp_x1 = x1
                    best_mp_x2 = x2

            if best_mp_y is not None and best_mp_len > 20:
                abs_y = (bottom_y + best_mp_y) / ch
                x1_pct = best_mp_x1 / cw
                x2_pct = best_mp_x2 / cw
                self._pixel_mp_bar = (x1_pct, x2_pct, abs_y)

            self._auto_found = (self._pixel_hp_bar is not None)
        except:
            pass

    def hp(self, sct, cx, cy, cw, ch):
        # 1. 嘗試載入校準檔
        if not hasattr(self, '_pixel_hp_bar'):
            self._load_pixel_config()
        # 2. 沒校準檔就自動搜尋（每次都重試直到找到）
        if not self._pixel_hp_bar:
            self._auto_find_bars(cx, cy, cw, ch)
        # 3. 像素偵測
        if self._pixel_hp_bar:
            val = self._read_pixel_bar(cx, cy, cw, ch, self._pixel_hp_bar, 'hp')
            if val is not None:
                self._hp_ratio = val
                self._hp_ever_read = True
                return val
            else:
                # 像素偵測失敗，重置讓下次重新搜尋
                self._pixel_hp_bar = None
                self._auto_found = False
        # 4. Fallback: OCR
        self._update(cx, cy, cw, ch)
        if self._hp_ever_read:
            return self._hp_ratio
        # 從未成功讀取過 → 回傳 -1 讓生存系統用定時模式
        return -1.0

    def mp(self, sct, cx, cy, cw, ch):
        if not hasattr(self, '_pixel_mp_bar'):
            self._load_pixel_config()
        if not self._pixel_mp_bar:
            self._auto_find_bars(cx, cy, cw, ch)
        if self._pixel_mp_bar:
            val = self._read_pixel_bar(cx, cy, cw, ch, self._pixel_mp_bar, 'mp')
            if val is not None:
                self._mp_ratio = val
                self._mp_ever_read = True
                return val
        if self._mp_ever_read:
            return self._mp_ratio
        return -1.0

    def calibrate(self, sct, cx, cy, cw, ch):
        self._load_pixel_config()
        if not self._pixel_hp_bar:
            self._auto_find_bars(cx, cy, cw, ch)
        self._last_ocr = 0
        self._ocr_busy = False
        self._bg_ocr(cx, cy, cw, ch)
        return self._hp_ratio >= 0

bars = BarReader()

# ═══════════════════════════════ 擬人化工具 ═══════════════════════════════

def human_sleep(base):
    """雙 Random 隨機延遲 — 兩個 random 疊加更接近常態分布"""
    gap = base * 0.1
    actual = base - gap + random.uniform(0, gap) + random.uniform(0, gap)
    time.sleep(max(0.001, actual))

def smooth_move(x, y):
    """Bresenham 平滑滑鼠移動 — 模擬人類軌跡"""
    try:
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        x0, y0 = pt.x, pt.y
    except:
        move_exact(x, y)
        return

    dx, dy = x - x0, y - y0
    dist = max(1, int(math.sqrt(dx*dx + dy*dy)))

    # 短距離直接移動
    if dist < 30:
        move_exact(x, y)
        return

    # 長距離分段平滑移動
    steps = min(dist // 5, 30)  # 最多 30 步
    for i in range(1, steps + 1):
        t = i / steps
        # 加一點隨機抖動模擬人手
        jx = int(x0 + dx * t) + random.randint(-1, 1)
        jy = int(y0 + dy * t) + random.randint(-1, 1)
        move_exact(jx, jy)
        if i % 2 == 0:
            time.sleep(random.uniform(0.005, 0.012))
    move_exact(x, y)

# ═══════════════════════════════ 排除區域 ═══════════════════════════════

def _in_exclude_zone(px, py, cx, cy, cw, ch):
    """判斷座標是否在 UI 排除區域（不應該掃描的地方）"""
    sh = int(ch * 0.75)
    # 底部 UI 區域
    if py > cy + sh:
        return True
    # 右側工具欄
    if px > cx + cw - int(cw * 0.06):
        return True
    # 左上角小地圖
    if px < cx + int(cw * 0.12) and py < cy + int(sh * 0.15):
        return True
    # 角色中心（自己的名字/角色）
    ccx, ccy = cx + cw // 2, cy + sh // 2
    if abs(px - ccx) < 60 and abs(py - ccy) < 40:
        return True
    return False

# ═══════════════════════════════ 幀差分偵測 ═══════════════════════════════

class FrameDiffer:
    """幀差分偵測遠處移動目標"""
    def __init__(self):
        self._prev_frame = None

    def detect_movement(self, cx, cy, cw, ch, min_area=200):
        """回傳有移動的區域中心座標列表 [(x,y), ...]"""
        sh = int(ch * 0.75)
        frame = grab_region(cx, cy, cw, sh)
        if frame is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._prev_frame is None:
            self._prev_frame = gray
            return []

        # 計算幀差
        diff = cv2.absdiff(self._prev_frame, gray)
        self._prev_frame = gray
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

        # 形態學去噪
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.dilate(thresh, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            mx, my = cx + x + w // 2, cy + y + h // 2
            # 排除 UI 區域和角色中心
            if not _in_exclude_zone(mx, my, cx, cy, cw, ch):
                results.append((mx, my))

        return results[:5]

_frame_differ = FrameDiffer()

# ═══════════════════════════════ 模板比對 ═══════════════════════════════

def _confirm_target_selected(cx, cy, cw, ch):
    """用 HSV 色域偵測確認是否成功選中目標
    選中怪物後，怪物腳下會出現藍色/紅色選取圓圈
    """
    try:
        frame, sh = grab_scene(cx, cy, cw, ch)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 藍色選取圓圈 (H:100-130, S:50-255, V:50-255)
        blue_mask = cv2.inRange(hsv, (100, 50, 50), (130, 255, 255))
        blue_px = blue_mask.sum() // 255

        # 紅色選取圓圈 (H:0-10 or 170-180, S:50-255, V:50-255)
        red_mask1 = cv2.inRange(hsv, (0, 50, 50), (10, 255, 255))
        red_mask2 = cv2.inRange(hsv, (170, 50, 50), (180, 255, 255))
        red_px = (red_mask1.sum() + red_mask2.sum()) // 255

        # 有足夠的藍色或紅色像素 = 選中了
        return (blue_px + red_px) > 100
    except:
        return True  # 失敗時假設成功

# ═══════════════════════════════ 怪物偵測 ═══════════════════════════════

def detect_monster_names(cx, cy, cw, ch):
    """
    用 OpenCV 偵測怪物名字（白字無背景框）
    過濾玩家名字（白字有深色背景框）
    回傳螢幕絕對座標列表 [(x, y), ...]
    """
    frame, sh = grab_scene(cx, cy, cw, ch)

    # Step 1: HSV 色域偵測白色文字（比固定 RGB 閾值對光線更強健）
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 白色：低飽和度、高亮度
    white_mask = cv2.inRange(hsv, (0, 0, 220), (180, 40, 255))

    # 排除角色中心和邊緣（排除區域）
    ccx, ccy = cw // 2, sh // 2
    cv2.circle(white_mask, (ccx, ccy), 80, 0, -1)
    white_mask[:15, :] = 0
    white_mask[:, :25] = 0
    white_mask[:, -25:] = 0
    # 排除右側工具欄
    toolbar_x = int(cw * 0.94)
    white_mask[:, toolbar_x:] = 0
    # 排除左上角小地圖
    minimap_x = int(cw * 0.12)
    minimap_y = int(sh * 0.15)
    white_mask[:minimap_y, :minimap_x] = 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

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


def _is_pet(px, py):
    """偵測是否為寵物：兩行白色名字 + 紅色血條
    寵物特徵：頭上有兩行白字（主人名+寵物名）且有紅色血條
    """
    try:
        # 1. 名字區域：兩行白色文字
        name_area = grab_region(px - 70, py - 60, 140, 40)
        if name_area is None or name_area.size == 0:
            return False

        r_ch = name_area[:,:,2].astype(int)
        g_ch = name_area[:,:,1].astype(int)
        b_ch = name_area[:,:,0].astype(int)
        white = (r_ch > 180) & (g_ch > 180) & (b_ch > 180)
        if white.sum() < 15:
            return False

        # 兩行：上半和下半都有白色像素
        h = name_area.shape[0]
        if white[:h//2, :].sum() < 5 or white[h//2:, :].sum() < 5:
            return False

        # 2. 紅色血條
        bar_area = grab_region(px - 80, py - 22, 160, 8)
        if bar_area is not None and bar_area.size > 0:
            br = bar_area[:,:,2].astype(int)
            bg = bar_area[:,:,1].astype(int)
            bb = bar_area[:,:,0].astype(int)
            red = (br > 140) & (bg < 80) & (bb < 80)
            if red.sum() > 30:
                return True

        return False
    except:
        return False

def _find_pet(cx, cy, cw, ch):
    """在畫面上找到寵物位置（兩行白字+紅色血條）
    回傳 (x, y) 或 None
    """
    sh = int(ch * 0.75)
    center_x, center_y = cx + cw // 2, cy + sh // 2
    # 從角色附近往外找（寵物通常在角色旁邊）
    for r in range(50, 300, 40):
        for angle_i in range(12):
            a = 2 * math.pi * angle_i / 12
            px = int(center_x + r * math.cos(a))
            py = int(center_y + r * math.sin(a))
            if not (cx + 20 < px < cx + cw - 20 and cy + 20 < py < cy + sh - 20):
                continue
            if _is_pet(px, py):
                return (px, py)
    return None

def scan_and_attack(cx, cy, cw, ch, hwnd, log=None, exclude=None, mode='近戰', pet_filter=False, blacklist=None):
    """掃描+攻擊一體化
    近戰：點擊怪物（角色自動走過去打）
    遠程/定點/其他：按住+拖曳（觸發遠程自動攻擊）
    pet_filter=True 時跳過寵物
    blacklist: 怪物名稱黑名單列表
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

    # 步距依視窗大小縮放（以 860px 寬為基準）
    scale = min(cw, sh) / 860

    if mode == '純定點':
        step = max(30, int(75 * scale))
        max_radius = min(cw, sh) * 2 // 3
        scan_delay = 0.02   # 20ms — 慢速穩定掃描
    elif mode == '墮落之地':
        step = max(30, int(75 * scale))
        max_radius = min(cw, sh) * 3 // 4  # 更大範圍
        scan_delay = 0.012  # 12ms
    elif mode == '地監':
        step = max(25, int(65 * scale))
        max_radius = min(cw, sh) * 3 // 4  # 大範圍掃描
        scan_delay = 0.012  # 12ms
    elif mode in ('遠程', '定點', '純定點', '墮落之地'):
        step = max(30, int(75 * scale))
        max_radius = min(cw, sh) * 2 // 3
        scan_delay = 0.01   # 10ms
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
            # 排除 UI 區域
            if _in_exclude_zone(px, py, cx, cy, cw, ch):
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

                # 寵物過濾
                if pet_filter and _is_pet(px, py):
                    if log:
                        log(f"掃到寵物，跳過({px},{py})")
                    continue

                # 怪物黑名單過濾（用 OCR 辨識名字）
                if blacklist and len(blacklist) > 0:
                    try:
                        name_img = grab_region(px - 60, py - 30, 120, 20)
                        if name_img is not None:
                            import cv2 as _cv2
                            gray_n = _cv2.cvtColor(name_img, _cv2.COLOR_BGR2GRAY)
                            _, mask_n = _cv2.threshold(gray_n, 180, 255, _cv2.THRESH_BINARY)
                            big_n = _cv2.resize(mask_n, None, fx=3, fy=3)
                            reader = get_ocr()
                            texts = reader.readtext(big_n, detail=0)
                            name_text = ''.join(texts)
                            if any(b in name_text for b in blacklist):
                                if log:
                                    log(f"黑名單怪物[{name_text}]，跳過({px},{py})")
                                continue
                    except:
                        pass

                # 找到怪物！
                if log:
                    log(f"掃{count}點→打！({px},{py})")

                if mode == '地監':
                    # 地監：按住怪物名字不放，角色自動走過去打
                    move_exact(px, py)
                    time.sleep(0.08)
                    game_down()
                else:
                    # 遠程/定點/其他：按住+拖曳觸發遠程自動攻擊
                    move_exact(px, py)
                    time.sleep(0.08)
                    game_down()
                    time.sleep(0.15)

                    drag_dist = random.randint(150, 250)
                    drag_dx = random.randint(-15, 15)
                    steps = 12
                    try:
                        for s in range(1, steps + 1):
                            rx = drag_dx * s // steps - drag_dx * (s-1) // steps
                            ry = drag_dist * s // steps - drag_dist * (s-1) // steps
                            interception.move_relative(rx, ry)
                            time.sleep(random.uniform(0.02, 0.04))
                    except:
                        drag_y = min(cy + sh - 20, py + drag_dist)
                        for s in range(1, steps + 1):
                            move_exact(
                                px + drag_dx * s // steps,
                                py + (drag_y - py) * s // steps)
                            time.sleep(0.03)

                    time.sleep(0.08)
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

def attack_melee(mx, my, cx=0, cy=0, cw=0, ch=0):
    """近戰攻擊：移到怪物→按住→拖曳（跟遠程一樣）"""
    attack_drag(mx, my, cx, cy, cw, ch)

def attack_drag(mx, my, cx, cy, cw, ch):
    """遠程拖曳攻擊：移到怪物→按住→拖曳→放開
    用 move_relative 做真實拖曳，遊戲用 Raw Input 才能偵測到
    """
    move_exact(mx, my)
    time.sleep(0.1)

    game_down()
    time.sleep(0.15)

    drag_dist = random.randint(150, 250)
    drag_dx = random.randint(-15, 15)
    steps = 12
    try:
        for s in range(1, steps + 1):
            rx = drag_dx * s // steps - drag_dx * (s-1) // steps
            ry = drag_dist * s // steps - drag_dist * (s-1) // steps
            interception.move_relative(rx, ry)
            time.sleep(random.uniform(0.02, 0.04))
    except:
        sh = int(ch * 0.75)
        drag_y = min(cy + sh - 20, my + drag_dist)
        for s in range(1, steps + 1):
            move_exact(
                mx + drag_dx * s // steps,
                my + (drag_y - my) * s // steps)
            time.sleep(0.03)

    time.sleep(0.08)
    game_up()

def attack(mx, my, cx, cy, cw, ch):
    """向後兼容：預設用拖曳攻擊"""
    attack_drag(mx, my, cx, cy, cw, ch)

# ═══════════════════════════════ 補血機系統 ═══════════════════════════════

def _get_party_slot_pos(cx, cy, cw, ch, slot_index):
    """取得隊伍 UI 中第 N 個成員的名字點擊座標和 HP 條座標
    slot_index: 0-7（最多 8 人）
    佈局：2 列 4 行，slot 0-1 在第一行，2-3 在第二行...
    基於全螢幕遊戲的精確像素分析（v16.0）
    """
    # 隊伍 UI 起始位置（比例，基於遊戲客戶端區域）
    ui_x = cx + int(cw * 0.009)   # 左邊界（蛇姬格子左端）
    ui_y = cy + int(ch * 0.782)   # 名字行 Y
    slot_w = int(cw * 0.078)      # 每格寬度
    row_h = int(ch * 0.038)       # 行高（名字+HP+間距）
    hp_offset_y = int(ch * 0.020) # HP 條在名字下方

    col = slot_index % 2   # 0=左, 1=右
    row = slot_index // 2  # 0-3

    name_x = ui_x + col * slot_w + slot_w // 2
    name_y = ui_y + row * row_h
    hp_x = ui_x + col * slot_w
    hp_y = name_y + hp_offset_y

    return {
        'name': (name_x, name_y),
        'hp_x': hp_x,
        'hp_y': hp_y,
        'hp_w': slot_w,
    }

def _read_party_hp(cx, cy, cw, ch, slot_index):
    """讀取隊伍成員的 HP 比例（0.0~1.0），-1 表示該位置沒人"""
    pos = _get_party_slot_pos(cx, cy, cw, ch, slot_index)
    try:
        bar = grab_region(pos['hp_x'], pos['hp_y'], pos['hp_w'], 5)
        if bar is None or bar.size == 0:
            return -1

        hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:,:,0].astype(int), hsv[:,:,1].astype(int), hsv[:,:,2].astype(int)

        # 紅色 HP 條：H=0-10 或 170-180, S>60, V>60
        red_mask = ((h < 10) | (h > 170)) & (s > 60) & (v > 60)
        red_count = red_mask.any(axis=0).sum()

        # 深灰色（HP 損失）：V<50, S<40
        dark_mask = (v < 50) & (s < 40)
        dark_count = dark_mask.any(axis=0).sum()

        total = red_count + dark_count
        if total < 5:
            return -1  # 沒人（沒有 HP 條）

        return red_count / total
    except:
        return -1

def _is_party_slot_occupied(cx, cy, cw, ch, slot_index):
    """檢查隊伍位置是否有人（名字區域有白色文字）"""
    pos = _get_party_slot_pos(cx, cy, cw, ch, slot_index)
    try:
        name_area = grab_region(pos['name'][0] - 30, pos['name'][1] - 8, 60, 16)
        if name_area is None:
            return False
        hsv = cv2.cvtColor(name_area, cv2.COLOR_BGR2HSV)
        white = cv2.inRange(hsv, (0, 0, 180), (180, 40, 255))
        return white.sum() // 255 > 10
    except:
        return False

# ═══════════════════════════════ 高寵輔助：隊友追蹤 ═══════════════════════════════

def _find_teammate_bar(cx, cy, cw, ch):
    """在遊戲場景中找隊友的玫瑰紅血條位置
    隊友血條顏色：R>150, G=30-80, B=50-113（玫瑰紅，跟怪物/寵物的純紅不同）
    回傳 (x, y) 螢幕絕對座標，或 None
    """
    sh = int(ch * 0.75)
    try:
        frame = grab_region(cx, cy, cw, sh)
        if frame is None or frame.size == 0:
            return None

        r = frame[:,:,2].astype(int)
        g = frame[:,:,1].astype(int)
        b = frame[:,:,0].astype(int)

        # 隊友血條：玫瑰紅（R>150, G=25-90, B=40-120, R-G>80）
        # 跟怪物純紅（B<50）和寵物紅（B<80）區別在於 B 較高
        mask = (r > 150) & (g > 25) & (g < 90) & (b > 40) & (b < 120) & ((r - g) > 80)

        # 找最長的橫條
        best_y = None
        best_len = 0
        best_x1 = 0
        best_x2 = 0
        for row_y in range(frame.shape[0]):
            cols = np.where(mask[row_y])[0]
            if len(cols) < 20:
                continue
            x1, x2 = cols[0], cols[-1]
            run = x2 - x1
            # 血條寬度在 80-200px 之間
            if run > best_len and 80 < run < 200:
                best_len = run
                best_y = row_y
                best_x1 = x1
                best_x2 = x2

        if best_y is not None:
            # 回傳血條中心的螢幕絕對座標
            abs_x = cx + (best_x1 + best_x2) // 2
            abs_y = cy + best_y
            return (abs_x, abs_y)

        return None
    except:
        return None

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
    _apply_cfg(gui, CONFIG_FILE)

def _apply_cfg(gui, filepath):
    """從指定 JSON 檔載入設定到 GUI"""
    if not os.path.exists(filepath):return
    try:
        with open(filepath) as f:c=json.load(f)
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

def list_profiles():
    """列出所有設定檔名稱"""
    profiles = []
    for f in sorted(os.listdir(PROFILES_DIR)):
        if f.endswith('.json'):
            profiles.append(f[:-5])  # 去掉 .json
    return profiles

def _collect_all_vars(gui):
    """收集所有 var_ 設定值（支援 list 型態的 BooleanVar/IntVar 等）"""
    c = {}
    for a in dir(gui):
        if not a.startswith('var_'):
            continue
        v = getattr(gui, a)
        if isinstance(v, (tk.BooleanVar, tk.StringVar, tk.IntVar, tk.DoubleVar)):
            c[a] = v.get()
        elif isinstance(v, list) and v:
            if isinstance(v[0], (tk.BooleanVar, tk.StringVar, tk.IntVar, tk.DoubleVar)):
                c[a] = [x.get() for x in v]
    c['monster_blacklist'] = gui.monster_blacklist
    return c

def save_profile(gui, name):
    """儲存目前設定到指定名稱的設定檔"""
    c = _collect_all_vars(gui)
    fp = os.path.join(PROFILES_DIR, f"{name}.json")
    with open(fp, 'w') as f:
        json.dump(c, f, indent=2, ensure_ascii=False)

def load_profile(gui, name):
    """從指定名稱的設定檔載入設定"""
    fp = os.path.join(PROFILES_DIR, f"{name}.json")
    _apply_cfg(gui, fp)

def delete_profile(name):
    """刪除指定名稱的設定檔"""
    fp = os.path.join(PROFILES_DIR, f"{name}.json")
    if os.path.exists(fp):
        os.remove(fp)

def autosave(gui):
    """自動儲存到 _autosave.json"""
    try:
        c = _collect_all_vars(gui)
        fp = os.path.join(PROFILES_DIR, '_autosave.json')
        with open(fp, 'w') as f:
            json.dump(c, f, indent=2, ensure_ascii=False)
    except:
        pass

def autoload(gui):
    """啟動時自動載入上次的設定"""
    fp = os.path.join(PROFILES_DIR, '_autosave.json')
    if os.path.exists(fp):
        _apply_cfg(gui, fp)
        return True
    return False

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
FONT=('Microsoft JhengHei',11); FONTS=('Microsoft JhengHei',10); FONTM=('Consolas',10)

class BotApp:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title(f"天堂經典版 Bot v{BOT_VERSION}")
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
        self.var_pet_en=tk.BooleanVar(value=False)  # 帶寵物模式
        self.var_pet_heal_en=tk.BooleanVar(value=False)  # 寵物補血
        self.var_pet_heal_key=tk.StringVar(value='F7')   # 治癒術快捷鍵
        self.var_pet_heal_sec=tk.IntVar(value=30)        # 每幾秒補一次
        self.var_pet_heal_thr=tk.IntVar(value=50)        # 血量低於%觸發
        # 補血機
        self.var_healer_en=tk.BooleanVar(value=False)   # 補血機開關
        self.var_healer_key=tk.StringVar(value='F7')    # 治癒術快捷鍵
        self.var_healer_thr=tk.IntVar(value=70)         # HP 低於此%觸發
        self.var_healer_sec=tk.DoubleVar(value=2.0)     # 檢查間隔秒數
        self.var_healer_self=tk.BooleanVar(value=True)  # 也補自己
        self.var_ocr_en=tk.BooleanVar(value=True)  # OCR 偵測開關
        # 墮落之地定時北移
        self.var_fallen_walk_en=tk.BooleanVar(value=True)
        self.var_fallen_walk_min=tk.IntVar(value=5)    # 每幾分鐘
        self.var_fallen_walk_sec=tk.IntVar(value=10)   # 點幾秒
        self.var_max_hp=tk.IntVar(value=0)   # 最大HP（0=自動偵測）
        self.var_max_mp=tk.IntVar(value=0)   # 最大MP（0=自動偵測）
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

        # 多組喝水配置（3 組，不同血量觸發不同藥水）
        self.var_pot_en = [tk.BooleanVar(value=(i==0)) for i in range(3)]
        self.var_pot_thr = [tk.IntVar(value=[60,40,20][i]) for i in range(3)]
        self.var_pot_key = [tk.StringVar(value=['F5','F5','F5'][i]) for i in range(3)]
        self.var_pot_type = [tk.StringVar(value=['紅水','橙水','萬能藥'][i]) for i in range(3)]

        # 反 PK 偵測
        self.var_antipk_en=tk.BooleanVar(value=False)
        self.var_antipk_act=tk.StringVar(value='回城')  # 回城/逃跑/警示

        # 自動販賣
        self.var_autosell_en=tk.BooleanVar(value=False)
        self.var_autosell_full=tk.IntVar(value=80)      # 背包滿度%觸發
        self.var_autosell_recall=tk.StringVar(value='F12')  # 回城卷快捷鍵

        # 高寵輔助模式
        self.var_hpet_follow=tk.BooleanVar(value=True)   # 自動跟隨隊友
        self.var_hpet_heal_key=tk.StringVar(value='F7')   # 治癒術快捷鍵
        self.var_hpet_heal_thr=tk.IntVar(value=70)        # HP 低於%補血
        self.var_hpet_buff_en=[tk.BooleanVar(value=False) for _ in range(3)]
        self.var_hpet_buff_key=[tk.StringVar(value='F8') for _ in range(3)]
        self.var_hpet_buff_sec=[tk.IntVar(value=300) for _ in range(3)]
        self.var_hpet_follow_sec=tk.DoubleVar(value=1.5)  # 跟隨檢查間隔

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
        self.var_timer_sec=[tk.DoubleVar(value=60.0) for _ in range(4)]
        self.var_timer_cnt=[tk.IntVar(value=1) for _ in range(4)]

        # 回城補給方案 (3套)
        self.var_supply=[tk.StringVar(value='紅水100個') for _ in range(3)]

        self._build()
        load_cfg(self)
        # 自動載入上次的設定檔
        if autoload(self):
            self.log("已載入上次設定")
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
        autosave(self)  # 關閉時自動儲存所有設定
        save_cfg(self);self.running=False;self.root.destroy()

    def _build(self):
        # ═══ 左側導航 ═══
        nav=tk.Frame(self.root,bg=BG1,width=130)
        nav.pack(side='left',fill='y')
        nav.pack_propagate(False)

        tk.Label(nav,text=f"天堂Bot v{BOT_VERSION}",bg=BG1,fg=ACC,font=('Microsoft JhengHei',14,'bold')).pack(pady=(10,15))

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

        # 設定檔管理（config/ 資料夾）
        sf_prof=self._section(p,"設定檔（config/）");sf_prof.pack(fill='x',padx=10,pady=3)
        r=self._frame(sf_prof);r.pack(fill='x',pady=2)
        self._lbl(r,"專案:").pack(side='left')
        self.var_profile=tk.StringVar(value='')
        self.profile_combo=self._combo(r,self.var_profile,list_profiles(),w=16)
        self.profile_combo.pack(side='left',padx=2)
        tk.Button(r,text="套用",font=FONTS,bg='#2980b9',fg='white',
                  command=self._load_profile).pack(side='left',padx=2)
        r2=self._frame(sf_prof);r2.pack(fill='x',pady=2)
        tk.Button(r2,text="儲存目前設定",font=FONTS,bg='#27ae60',fg='white',
                  command=self._save_profile).pack(side='left',padx=2)
        tk.Button(r2,text="另存新檔",font=FONTS,bg='#27ae60',fg='white',
                  command=self._saveas_profile).pack(side='left',padx=2)
        tk.Button(r2,text="刪除",font=FONTS,bg=ACC,fg='white',
                  command=self._delete_profile).pack(side='left',padx=2)
        tk.Button(r2,text="開啟資料夾",font=FONTS,bg='#555',fg='white',
                  command=lambda:os.startfile(CONFIG_DIR)).pack(side='left',padx=2)

        # Debug + 校準
        r=self._frame(p);r.pack(fill='x',padx=10,pady=2)
        tk.Button(r,text="校準HP條",font=FONTS,bg='#e67e22',fg='white',command=self._calibrate_hp).pack(side='left',padx=3)
        tk.Button(r,text="HP偵測截圖",font=FONTS,bg='#8e44ad',fg='white',command=self._debug_hp).pack(side='left',padx=3)

        # 日誌
        sf=self._section(p,"日誌");sf.pack(fill='both',padx=10,pady=(5,10),expand=True)
        self.log_w=tk.Text(sf,height=8,bg='#0d1117',fg='#58a6ff',font=('Consolas',8),state='disabled',wrap='word')
        self.log_w.pack(fill='both',expand=True)

    def _refresh_profiles(self):
        """更新設定檔下拉選單"""
        profiles = list_profiles()
        self.profile_combo['values'] = profiles

    def _save_profile(self):
        """儲存到目前選擇的設定檔（覆蓋）"""
        name = self.var_profile.get().strip()
        if not name:
            self._saveas_profile()
            return
        save_profile(self, name)
        self.log(f"設定已儲存: config/{name}.json")

    def _saveas_profile(self):
        """另存新檔"""
        from tkinter import simpledialog
        name = simpledialog.askstring("另存設定檔",
            "請輸入設定檔名稱:\n（例如：近戰骑士、遠程法師、地監寵物）",
            parent=self.root)
        if not name:
            return
        name = name.strip()
        save_profile(self, name)
        self.var_profile.set(name)
        self._refresh_profiles()
        self.log(f"設定已儲存: config/{name}.json")

    def _load_profile(self):
        """套用選擇的設定檔"""
        name = self.var_profile.get().strip()
        if not name:
            self.log("請先選擇設定檔")
            return
        load_profile(self, name)
        self.log(f"已套用設定檔: {name}")
        # 套用後更新 GUI 顯示
        try:
            self._on_mode()
        except:
            pass

    def _delete_profile(self):
        name = self.var_profile.get().strip()
        if not name:
            return
        from tkinter import messagebox
        if not messagebox.askyesno("刪除設定檔", f"確定刪除「{name}」？", parent=self.root):
            return
        delete_profile(name)
        self.var_profile.set('')
        self._refresh_profiles()
        self.log(f"設定已刪除: {name}")

    def _calibrate_hp(self):
        """手動校準 HP/MP 條位置 — 把滑鼠移到位置後按空白鍵確認"""
        from tkinter import messagebox
        g = find_game()
        if not g:
            self.log("找不到遊戲視窗！")
            return
        cx, cy, cw, ch = get_rect(g[0])

        messagebox.showinfo("校準 HP 條",
            "操作方式：\n\n"
            "1. 把滑鼠移到 HP 條的【左端】，按【空白鍵】確認\n"
            "2. 把滑鼠移到 HP 條的【右端】，按【空白鍵】確認\n\n"
            "（請確保 HP 是滿的）\n"
            "每步有 15 秒鐘", parent=self.root)

        self.log("校準中：移滑鼠到 HP 條左端，按空白鍵...")
        self._status("校準HP：移到左端按空白鍵", '#e67e22')

        def wait_space():
            """等使用者按空白鍵，回傳當前滑鼠位置"""
            start = time.time()
            while time.time() - start < 15:
                if keyboard.is_pressed('space'):
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    time.sleep(0.3)  # 防重複觸發
                    return (pt.x, pt.y)
                time.sleep(0.05)
            return None

        p1 = wait_space()
        if not p1:
            self.log("校準超時")
            return
        self.log(f"HP左端: ({p1[0]},{p1[1]})")
        self._status("校準HP：移到右端按空白鍵", '#e67e22')

        p2 = wait_space()
        if not p2:
            self.log("校準超時")
            return
        self.log(f"HP右端: ({p2[0]},{p2[1]})")

        # 計算比例
        x1_pct = (p1[0] - cx) / cw
        x2_pct = (p2[0] - cx) / cw
        y_pct = ((p1[1] + p2[1]) / 2 - cy) / ch

        bars._pixel_hp_bar = (x1_pct, x2_pct, y_pct)
        bars._auto_found = True
        bars._hp_ever_read = False

        cfg = {'hp_bar': [x1_pct, x2_pct, y_pct]}

        # MP 校準
        if messagebox.askyesno("校準 MP 條", "要繼續校準 MP 條嗎？\n\n移滑鼠到 MP 條左端→空白鍵\n移滑鼠到 MP 條右端→空白鍵", parent=self.root):
            self.log("校準中：移滑鼠到 MP 條左端，按空白鍵...")
            self._status("校準MP：移到左端按空白鍵", '#3498db')
            p3 = wait_space()
            if p3:
                self.log(f"MP左端: ({p3[0]},{p3[1]})")
                self._status("校準MP：移到右端按空白鍵", '#3498db')
                p4 = wait_space()
                if p4:
                    self.log(f"MP右端: ({p4[0]},{p4[1]})")
                    mx1 = (p3[0] - cx) / cw
                    mx2 = (p4[0] - cx) / cw
                    my = ((p3[1] + p4[1]) / 2 - cy) / ch
                    bars._pixel_mp_bar = (mx1, mx2, my)
                    cfg['mp_bar'] = [mx1, mx2, my]

        # 存檔
        cfg_path = os.path.join(SCRIPT_DIR, 'hp_config.json')
        with open(cfg_path, 'w') as f:
            json.dump(cfg, f, indent=2)

        self.log(f"校準完成！HP={bars._pixel_hp_bar}")
        self._status("校準完成", '#27ae60')

        # 測試讀取
        hp = bars.hp(None, cx, cy, cw, ch)
        self.log(f"測試讀取 HP={hp*100:.0f}%" if hp >= 0 else "測試讀取失敗")

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
        self._chk(r,"帶寵物",self.var_pet_en).pack(side='left',padx=8)
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

    # ═══ 生存頁（ROBOBEAR 風格：緊湊一行式佈局） ═══
    def _build_survival(self):
        p=self.pages['生存']

        # ── HP/MP 設定 ──
        sf=self._section(p,"❤ HP/MP 設定（填入最大值可顯示絕對數字）");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._lbl(r,"最大HP:").pack(side='left')
        self._spin(r,self.var_max_hp,0,99999,w=6,inc=10).pack(side='left')
        self._lbl(r,"  最大MP:").pack(side='left')
        self._spin(r,self.var_max_mp,0,99999,w=6,inc=10).pack(side='left')
        self._lbl(r,"  (0=用像素比例)").pack(side='left')

        # ── 喝水保護 ──
        sf=self._section(p,"⚔ 喝水保護");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"喝水保護",self.var_hp_en).pack(side='left')
        self._combo(r,self.var_hp_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"HP低於").pack(side='left')
        self._spin(r,self.var_hp_thr,5,90,w=3,inc=5).pack(side='left')
        self._lbl(r,"%").pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"藍水保護",self.var_mp_en).pack(side='left')
        self._combo(r,self.var_mp_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"MP低於").pack(side='left')
        self._spin(r,self.var_mp_thr,5,90,w=3,inc=5).pack(side='left')
        self._lbl(r,"%").pack(side='left')

        # 多組喝水
        pot_types = ['紅水','橙水','萬能藥','肉','自訂']
        for i in range(3):
            r=self._frame(sf);r.pack(fill='x',pady=1)
            self._chk(r,f"喝水{i+2}",self.var_pot_en[i]).pack(side='left')
            self._combo(r,self.var_pot_key[i],FKEYS,w=3).pack(side='left',padx=3)
            self._combo(r,self.var_pot_type[i],pot_types,w=5).pack(side='left',padx=2)
            self._lbl(r,"HP<").pack(side='left')
            self._spin(r,self.var_pot_thr[i],5,95,w=3,inc=5).pack(side='left')
            self._lbl(r,"%").pack(side='left')

        # ── 自補保護 ──
        sf=self._section(p,"✚ 自補保護");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"治癒術",self.var_heal_en).pack(side='left')
        self._combo(r,self.var_heal_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"HP低於").pack(side='left')
        self._spin(r,self.var_heal_thr,5,90,w=3,inc=5).pack(side='left')
        self._lbl(r,"%  x").pack(side='left')
        self._spin(r,self.var_heal_n,1,5,w=2).pack(side='left')

        # ── Buff 施放 ──
        sf=self._section(p,"✦ 自動施放Buff");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"綠水/Buff",self.var_buff_en).pack(side='left')
        self._combo(r,self.var_buff_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"每").pack(side='left')
        self._spin(r,self.var_buff_sec,60,3600,w=5,inc=60).pack(side='left')
        self._lbl(r,"秒").pack(side='left')

        # ── 回村保護 ──
        sf=self._section(p,"⛨ 回村保護");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"緊急回城",self.var_recall_en).pack(side='left')
        self._combo(r,self.var_recall_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"HP低於").pack(side='left')
        self._spin(r,self.var_recall_thr,5,30,w=3,inc=5).pack(side='left')
        self._lbl(r,"%").pack(side='left')
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"自動回城販賣",self.var_autosell_en).pack(side='left')
        self._combo(r,self.var_autosell_recall,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"背包>").pack(side='left')
        self._spin(r,self.var_autosell_full,50,95,w=3,inc=5).pack(side='left')
        self._lbl(r,"%").pack(side='left')

        # ── 反 PK 偵測 ──
        sf=self._section(p,"⚠ 反PK偵測");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"偵測玩家",self.var_antipk_en).pack(side='left')
        self._lbl(r,"動作:").pack(side='left',padx=(8,1))
        self._combo(r,self.var_antipk_act,['回城','逃跑','警示'],w=5).pack(side='left')

        # ── 定時保底（OCR 關閉時） ──
        sf=self._section(p,"⏱ 定時保底（OCR關閉時）");sf.pack(fill='x',padx=8,pady=2)
        r=self._frame(sf);r.pack(fill='x',pady=1)
        self._chk(r,"OCR偵測",self.var_ocr_en).pack(side='left')
        self._lbl(r,"  紅水每").pack(side='left')
        self._spin(r,self.var_hp_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"s  藍水每").pack(side='left')
        self._spin(r,self.var_mp_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"s  治癒每").pack(side='left')
        self._spin(r,self.var_heal_sec,3,60,w=3,inc=1).pack(side='left')
        self._lbl(r,"s").pack(side='left')

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

        # 更新（獨立一行）
        r=self._frame(sf2);r.pack(fill='x',pady=5)
        tk.Button(r,text=">>> 檢查更新 <<<",font=('Microsoft JhengHei',10,'bold'),bg='#e67e22',fg='white',command=self._check_update).pack(side='left',padx=3)
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
        for m in ['近戰','遠程','定點','純定點','墮落之地','召喚','隊伍','地監','補血機','高寵輔助']:
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
        # 地監
        f=self._section(p,"地監設定");self.mode_frames['地監']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._chk(r,"寵物補血",self.var_pet_heal_en).pack(side='left')
        self._lbl(r,"治癒鍵:").pack(side='left',padx=(8,1))
        self._combo(r,self.var_pet_heal_key,FKEYS,w=3).pack(side='left')
        self._lbl(r,"每").pack(side='left',padx=(8,1))
        self._spin(r,self.var_pet_heal_sec,10,120,w=3,inc=5).pack(side='left')
        self._lbl(r,"秒").pack(side='left')
        tk.Label(f,text="帶寵物刷地監專用\n按住怪物攻擊 + 自動過濾寵物\n打死後 F4 拾取 + 掃描撿物",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)

        # 補血機
        f=self._section(p,"補血機設定");self.mode_frames['補血機']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._chk(r,"啟用補血機",self.var_healer_en).pack(side='left')
        self._lbl(r,"治癒鍵:").pack(side='left',padx=(8,1))
        self._combo(r,self.var_healer_key,FKEYS,w=3).pack(side='left')
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"HP<").pack(side='left')
        self._spin(r,self.var_healer_thr,20,90,w=3,inc=10).pack(side='left')
        self._lbl(r,"% 觸發").pack(side='left')
        self._lbl(r,"  每").pack(side='left')
        self._spin(r,self.var_healer_sec,0.5,10,w=4,inc=0.5).pack(side='left')
        self._lbl(r,"秒檢查").pack(side='left')
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._chk(r,"也補自己",self.var_healer_self).pack(side='left')
        tk.Label(f,text="站著不動，專門幫隊友補血\n偵測隊伍 UI 的 HP 條\n點治癒鍵 → 點隊友名字",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)

        # 高寵輔助
        f=self._section(p,"高寵輔助設定");self.mode_frames['高寵輔助']=f
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._chk(r,"自動跟隨隊友",self.var_hpet_follow).pack(side='left')
        self._lbl(r,"每").pack(side='left',padx=(8,1))
        self._spin(r,self.var_hpet_follow_sec,1,10,w=4,inc=0.5).pack(side='left')
        self._lbl(r,"秒檢查").pack(side='left')
        r=self._frame(f);r.pack(fill='x',padx=6,pady=3)
        self._lbl(r,"治癒鍵:").pack(side='left')
        self._combo(r,self.var_hpet_heal_key,FKEYS,w=3).pack(side='left',padx=3)
        self._lbl(r,"HP<").pack(side='left')
        self._spin(r,self.var_hpet_heal_thr,20,90,w=3,inc=10).pack(side='left')
        self._lbl(r,"%").pack(side='left')
        # 3 組 Buff
        for i in range(3):
            r=self._frame(f);r.pack(fill='x',padx=6,pady=1)
            self._chk(r,f"Buff{i+1}",self.var_hpet_buff_en[i]).pack(side='left')
            self._combo(r,self.var_hpet_buff_key[i],FKEYS,w=3).pack(side='left',padx=3)
            self._lbl(r,"每").pack(side='left')
            self._spin(r,self.var_hpet_buff_sec[i],30,3600,w=5,inc=30).pack(side='left')
            self._lbl(r,"秒").pack(side='left')
        tk.Label(f,text="自動跟隨隊友+補血+上Buff\n偵測隊友頭上的玫瑰紅血條追蹤位置\n補血/Buff 點左下隊伍 UI 施放",bg=BG2,fg='#888',font=FONTS).pack(padx=6,pady=6)

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

    def _bar(self,cv,tl,pct,w=120,cur=0,mx=0,bar_type='hp'):
        def _u():
            p=max(0,min(1,pct));cv.delete('all')
            cv.create_rectangle(0,0,w,16,fill='#222',outline='')
            c=ACC if p<0.3 else('#f5a623' if p<0.6 else'#27ae60')
            cv.create_rectangle(0,0,int(w*p),16,fill=c,outline='')
            # 用設定的最大值計算絕對數字
            max_val = self.var_max_hp.get() if bar_type=='hp' else self.var_max_mp.get()
            if max_val > 0:
                abs_cur = int(p * max_val)
                tl.config(text=f"{abs_cur}/{max_val}")
            elif mx > 0:
                tl.config(text=f"{cur}/{mx}")
            else:
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
        self.root.after(0,_u)

    def _toggle(self):
        if self.running:
            self.running=False;self._status("已停止");self.log("Bot 暫停");save_cfg(self);autosave(self)
        else:
            self.running=True;self.t0=time.time();self.bot_state=BotState.IDLE;self._status("運行中",'#27ae60');self.log("Bot 啟動")
            self._last_activity = time.time()
            skills.setup([(self.var_sk[i].get(),self.var_cd[i].get()) for i in range(7)])
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
        """取得快捷欄格子的螢幕座標 (F5-F12)
        上排: F5 F6 F7 F8
        下排: F9 F10 F11 F12
        """
        right_edge = cx + cw - 10
        big_w = int(cw * 0.052)
        bottom_y = cy + int(ch * 0.91)
        top_y = bottom_y - int(ch * 0.060)

        # F12→F9 的 X 位置（從右往左）— 下排
        x12 = right_edge - big_w // 2
        x_map = {12: x12, 11: x12 - big_w, 10: x12 - big_w*2, 9: x12 - big_w*3}
        # F5-F8 上排（跟 F9-F12 同 X，不同 Y）
        x_map[5] = x_map[9]
        x_map[6] = x_map[10]
        x_map[7] = x_map[11]
        x_map[8] = x_map[12]
        # F1-F4：在 F5-F8 再上面一排
        top2_y = top_y - int(ch * 0.060)
        x_map[1] = x_map[5]
        x_map[2] = x_map[6]
        x_map[3] = x_map[7]
        x_map[4] = x_map[8]

        # 解析 slot_key（"F5" → 5）
        try:
            num = int(slot_key.upper().replace('F', ''))
        except:
            return None
        if num not in x_map:
            return None

        if num <= 4:
            y = top2_y
        elif num <= 8:
            y = top_y
        else:
            y = bottom_y
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
        if HAS_INTERCEPTION:
            try: interception.mouse_up('left')
            except: pass
        else:
            try: mouse_lib.release('left')
            except: pass
        time.sleep(0.2)
        # 移到快捷欄
        move_exact(x, y)
        time.sleep(0.25)
        # 連點（直接用 interception 或 mouse_lib）
        for i in range(clicks):
            if HAS_INTERCEPTION:
                try:
                    interception.mouse_down('left')
                    time.sleep(0.04)
                    interception.mouse_up('left')
                except:
                    mouse_lib.click('left')
            else:
                mouse_lib.click('left')
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
        hp = mp = -1.0
        hp_unknown = True  # HP 是否未知（無法讀取）

        if self.var_ocr_en.get():
            try:
                prev_hp = getattr(self, '_prev_hp', 1.0)
                hp = bars.hp(None, cx, cy, cw, ch)
                if hp >= 0:
                    hp_unknown = False
                    self._bar(self.hp_cv, self.hp_tl, hp, cur=bars._hp_cur, mx=bars._hp_max, bar_type='hp')
                else:
                    # HP 讀不到，顯示「?」
                    self.hp_tl.config(text="無法讀取")
                mp = bars.mp(None, cx, cy, cw, ch)
                if mp >= 0:
                    self._bar(self.mp_cv, self.mp_tl, mp, cur=bars._mp_cur, mx=bars._mp_max, bar_type='mp')

                # HP 急降即時反應
                if hp >= 0 and prev_hp >= 0 and prev_hp - hp > 0.20 and self.var_hp_en.get():
                    self.log(f"HP急降！{prev_hp*100:.0f}%→{hp*100:.0f}%")
                    k = self.var_hp_key.get()
                    self._click_hotbar(cx, cy, cw, ch, k)
                    timers['hp'] = now
                    self.pots += 1
                if hp >= 0:
                    self._prev_hp = hp
            except:
                pass

        # HP 未知或 OCR 關閉 → 強制定時喝水模式
        if hp_unknown or not self.var_ocr_en.get():
            bars._hp_max = 0
            bars._mp_max = 0
        # debug：每 5 秒顯示 HP/MP 讀值
        if not hasattr(self, '_last_hp_debug'):
            self._last_hp_debug = 0
        if now - self._last_hp_debug > 5:
            hp_pct = f"{hp*100:.0f}%" if hp >= 0 else "?"
            mp_pct = f"{mp*100:.0f}%" if mp >= 0 else "?"
            self.log(f"[HP={hp_pct} MP={mp_pct} 偵測={'像素' if bars._hp_ever_read else '定時'}]")
            self._last_hp_debug = now

        # Buff（不需要 HP 值，定時觸發）
        if self.var_buff_en.get() and now - timers['buff'] > self.var_buff_sec.get():
            k = self.var_buff_key.get()
            self._click_hotbar(cx, cy, cw, ch, k, clicks=5)  # 法術類5下
            time.sleep(0.3)
            timers['buff'] = now
            self.buffs += 1
            self.log(f"喝綠水({k})")

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
            self._click_hotbar(cx, cy, cw, ch, self.var_recall_key.get(), clicks=2)
            self.log(f"緊急回城！HP={hp*100:.0f}%")
            alert('hp')
            self.running = False
            self._status("緊急回城", ACC)
            time.sleep(5)
            return hp, mp

        # 治癒術（HP 低於閾值 / OCR 關閉時定時施放）
        heal_trigger = (hp >= 0 and hp < self.var_heal_thr.get() / 100) \
                       or (bars._hp_max == 0 and now - timers['heal'] > self.var_heal_sec.get())
        if self.var_heal_en.get() and heal_trigger and now - timers['heal'] > 3:
            k = self.var_heal_key.get()
            for _ in range(self.var_heal_n.get()):
                self._click_hotbar(cx, cy, cw, ch, k, clicks=5)  # 法術類5下
                time.sleep(0.3)
            timers['heal'] = now
            self.heals += 1
            self.log(f"治癒術({k}) HP={hp*100:.0f}%")

        # 紅水 — HP 已知用比例判斷，HP 未知用定時喝
        hp_thr = self.var_hp_thr.get() / 100
        if hp >= 0 and not hp_unknown:
            need_hp = hp < hp_thr
        else:
            # HP 無法讀取 → 定時喝水保底
            need_hp = now - timers['hp'] > self.var_hp_sec.get()
        if self.var_hp_en.get() and need_hp and now - timers['hp'] > 4:
            k = self.var_hp_key.get()
            self._click_hotbar(cx, cy, cw, ch, k)
            timers['hp'] = now
            self.pots += 1
            if hp >= 0:
                self.log(f"喝紅水({k}) HP={hp*100:.0f}%")
            else:
                self.log(f"喝紅水({k}) 定時保底")

        # 藍水
        mp_thr = self.var_mp_thr.get() / 100
        if mp >= 0:
            need_mp = mp < mp_thr
        else:
            need_mp = now - timers['mp'] > self.var_mp_sec.get()
        if self.var_mp_en.get() and need_mp and now - timers['mp'] > 4:
            k = self.var_mp_key.get()
            self._click_hotbar(cx, cy, cw, ch, k)
            timers['mp'] = now
            self.mpots += 1
            if mp >= 0:
                self.log(f"喝藍水({k}) MP={mp*100:.0f}%")
            else:
                self.log(f"喝藍水({k}) 定時保底")

        # 多組喝水（按優先級：閾值高的先觸發）
        if hp >= 0 and not hp_unknown:
            for i in range(3):
                if not self.var_pot_en[i].get():
                    continue
                pot_timer = f'pot_{i}'
                if pot_timer not in timers:
                    timers[pot_timer] = 0
                pot_thr = self.var_pot_thr[i].get() / 100
                if hp < pot_thr and now - timers[pot_timer] > 4:
                    k = self.var_pot_key[i].get()
                    self._click_hotbar(cx, cy, cw, ch, k)
                    timers[pot_timer] = now
                    self.pots += 1
                    self.log(f"多組喝水#{i+1} {self.var_pot_type[i].get()}({k}) HP={hp*100:.0f}%")
                    break  # 一次只喝一瓶，下次再檢查

        # 反 PK 偵測（偵測畫面中的玩家粉紅色名字）
        if self.var_antipk_en.get() and hp >= 0:
            pk_timer = timers.get('pk_check', 0)
            if now - pk_timer > 3:  # 每 3 秒檢查一次
                try:
                    frame, sh = grab_scene(cx, cy, cw, ch)
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    # 粉紅色玩家名字 H=150-170, S>50, V>100
                    pink = cv2.inRange(hsv, (150, 50, 100), (170, 255, 255))
                    pink_count = pink.sum() // 255
                    if pink_count > 50:  # 有大量粉紅像素 = 有玩家
                        act = self.var_antipk_act.get()
                        self.log(f"偵測到玩家！({pink_count}px) 動作:{act}")
                        alert('pk')
                        if act == '回城':
                            self._click_hotbar(cx, cy, cw, ch, self.var_recall_key.get(), clicks=2)
                            self.running = False
                            self._status("PK回城", ACC)
                            return hp, mp
                        elif act == '逃跑':
                            # 隨機方向逃跑
                            sh_s = int(ch * 0.75)
                            fx = cx + random.randint(50, cw-50)
                            fy = cy + random.randint(50, sh_s-50)
                            game_click(fx, fy)
                            time.sleep(2)
                except:
                    pass
                timers['pk_check'] = now

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

        # 寵物補血（地監模式）
        # 有血條 = 受傷（滿血時血條不顯示），找到就補
        if self.var_pet_heal_en.get() and self.var_mode.get() == '地監':
            pet_timer = timers.get('pet_heal', 0)
            if now - pet_timer > self.var_pet_heal_sec.get():
                # 找受傷的寵物（兩行白字+紅色血條=受傷中）
                pet_pos = _find_pet(cx, cy, cw, ch)
                if pet_pos:
                    # 有血條就代表受傷，按治癒鍵 → 點擊寵物
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    press_key(self.var_pet_heal_key.get())
                    time.sleep(0.2)
                    game_click(pet_pos[0], pet_pos[1])
                    time.sleep(0.3)
                    self.log(f"寵物補血({pet_pos[0]},{pet_pos[1]})")
                    # 回到怪物位置
                    if hasattr(self, '_combat_monster') and self._combat_monster:
                        move_exact(self._combat_monster[0], self._combat_monster[1])
                timers['pet_heal'] = now

        self._stats()
        return hp, mp

    def _do_attack(self, mx, my, cx, cy, cw, ch, hwnd):
        """執行攻擊（依模式）"""
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        mode = self.var_mode.get()
        if mode in ('近戰', '地監'):
            attack_melee(mx, my, cx, cy, cw, ch)
        elif mode == '遠程':
            attack_drag(mx, my, cx, cy, cw, ch)
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
        elif mode in ('定點', '純定點', '墮落之地'):
            # 定點：按攻擊鍵 → 移到怪物 → 按住 → 拖曳 → 放開
            press_key(self.var_rng_key.get())
            time.sleep(0.1)
            move_exact(mx, my)
            time.sleep(0.08)
            game_down()
            time.sleep(0.15)
            drag_dist = random.randint(150, 250)
            drag_dx = random.randint(-15, 15)
            steps = 12
            try:
                for s in range(1, steps + 1):
                    rx = drag_dx * s // steps - drag_dx * (s-1) // steps
                    ry = drag_dist * s // steps - drag_dist * (s-1) // steps
                    interception.move_relative(rx, ry)
                    time.sleep(random.uniform(0.02, 0.04))
            except:
                drag_y = my + drag_dist
                for s in range(1, steps + 1):
                    move_exact(
                        mx + drag_dx * s // steps,
                        my + (drag_y - my) * s // steps)
                    time.sleep(0.03)
            time.sleep(0.08)
            game_up()
        elif mode == '召喚':
            attack_drag(mx, my, cx, cy, cw, ch)
            press_key(self.var_sum_atk.get())
            sh = int(ch * 0.75)
            move_exact(cx + cw // 2, cy + sh // 2)
            game_click()
        elif mode == '隊伍':
            role = self.var_pt_role.get()
            if role in ('坦克', '輸出'):
                attack_melee(mx, my, cx, cy, cw, ch)
            elif role == '補師':
                press_key(self.var_pt_heal.get())
            elif role == '輔助':
                press_key(self.var_pt_buff.get())
                attack_melee(mx, my, cx, cy, cw, ch)

    def _combat_skill(self, cx=0, cy=0, cw=0, ch=0):
        """戰鬥中持續施放技能（用鍵盤，不動滑鼠避免干擾戰鬥）"""
        mode = self.var_mode.get()
        if mode in ('近戰', '地監'):
            skills.use_next()
        elif mode in ('遠程', '定點', '純定點', '墮落之地'):
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

        # 自動校準 HP/MP 條位置
        cx0, cy0, cw0, ch0 = get_rect(g[0])
        bars._auto_found = False
        bars._pixel_hp_bar = None
        bars._pixel_mp_bar = None
        bars._load_pixel_config()
        if not bars._pixel_hp_bar:
            self.log("自動搜尋 HP/MP 條位置...")
            bars._auto_find_bars(cx0, cy0, cw0, ch0)
        if bars._pixel_hp_bar:
            self.log(f"HP條位置: Y={bars._pixel_hp_bar[2]:.3f} X={bars._pixel_hp_bar[0]:.3f}-{bars._pixel_hp_bar[1]:.3f}")
        else:
            self.log("⚠ 未找到HP條！將使用定時喝水模式")
        if bars._pixel_mp_bar:
            self.log(f"MP條位置: Y={bars._pixel_mp_bar[2]:.3f} X={bars._pixel_mp_bar[0]:.3f}-{bars._pixel_mp_bar[1]:.3f}")

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

        # 1. 立刻喝綠水（用滑鼠點快捷欄）
        if self.var_buff_en.get():
            k = self.var_buff_key.get()
            self._click_hotbar(cx_s, cy_s, cw_s, ch_s, k, clicks=5)
            timers['buff'] = time.time()
            self.buffs += 1
            self.log(f"啟動喝綠水({k})")
            time.sleep(0.5)

        # 2. 打開小地圖 (Ctrl+M) — 用 interception 鍵盤
        try:
            interception.press('ctrl')
            time.sleep(0.05)
            interception.press('m')
        except:
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

            # ── 補血機模式 ──
            if self.var_mode.get() == '補血機' and self.var_healer_en.get():
                healer_timer = timers.get('healer', 0)
                now_h = time.time()
                if now_h - healer_timer > self.var_healer_sec.get():
                    self._status("補血機", '#27ae60')
                    thr = self.var_healer_thr.get() / 100
                    healed = False
                    # 掃描所有隊友（slot 0=自己, 1-7=隊友）
                    start_slot = 0 if self.var_healer_self.get() else 1
                    for slot in range(start_slot, 8):
                        if not _is_party_slot_occupied(cx, cy, cw, ch, slot):
                            continue
                        hp_ratio = _read_party_hp(cx, cy, cw, ch, slot)
                        if hp_ratio < 0:
                            continue
                        if hp_ratio < thr:
                            # 需要補血！點治癒鍵 → 點隊友名字
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            self._click_hotbar(cx, cy, cw, ch, self.var_healer_key.get(), clicks=4)
                            human_sleep(0.2)
                            pos = _get_party_slot_pos(cx, cy, cw, ch, slot)
                            game_click(pos['name'][0], pos['name'][1])
                            human_sleep(0.3)
                            self.heals += 1
                            self.log(f"補血 slot{slot} HP={hp_ratio*100:.0f}%")
                            healed = True
                            break  # 一次補一個，下次再檢查
                    if not healed:
                        self._status("補血機待命", '#27ae60')
                    timers['healer'] = now_h
                    self._stats()
                else:
                    time.sleep(0.1)
                continue  # 補血機不打怪

            # ── 高寵輔助模式 ──
            if self.var_mode.get() == '高寵輔助':
                now_hp = time.time()

                # 1. 自動跟隨隊友（偵測畫面中的玫瑰紅血條）
                follow_timer = timers.get('hpet_follow', 0)
                if self.var_hpet_follow.get() and now_hp - follow_timer > self.var_hpet_follow_sec.get():
                    teammate_pos = _find_teammate_bar(cx, cy, cw, ch)
                    if teammate_pos:
                        tx, ty = teammate_pos
                        # 計算角色中心
                        sh_s = int(ch * 0.75)
                        my_x = cx + cw // 2
                        my_y = cy + sh_s // 2
                        # 距離太遠才跟隨（避免原地抖動）
                        dist = math.sqrt((tx - my_x)**2 + (ty - my_y)**2)
                        if dist > 80:
                            # 點擊隊友血條下方的地面跟過去
                            click_y = min(ty + 50, cy + sh_s - 20)
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            game_click(tx, click_y)
                            self._status(f"跟隨中 距離{dist:.0f}", '#27ae60')
                            self.log(f"跟隨隊友 ({tx},{ty}) 距離{dist:.0f}")
                        else:
                            self._status("高寵待命", '#27ae60')
                    else:
                        self._status("找不到隊友", '#f5a623')
                    timers['hpet_follow'] = now_hp

                # 2. 補血（偵測左下隊伍 UI，每 0.8 秒檢查）
                heal_timer = timers.get('hpet_heal', 0)
                if now_hp - heal_timer > 0.8:
                    thr = self.var_hpet_heal_thr.get() / 100
                    for slot in range(1, 8):  # slot 0 是自己
                        if not _is_party_slot_occupied(cx, cy, cw, ch, slot):
                            continue
                        hp_ratio = _read_party_hp(cx, cy, cw, ch, slot)
                        if hp_ratio < 0:
                            continue
                        if hp_ratio < thr:
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            self._click_hotbar(cx, cy, cw, ch, self.var_hpet_heal_key.get(), clicks=4)
                            time.sleep(0.2)
                            pos = _get_party_slot_pos(cx, cy, cw, ch, slot)
                            game_click(pos['name'][0], pos['name'][1])
                            time.sleep(0.3)
                            self.heals += 1
                            self.log(f"高寵補血 slot{slot} HP={hp_ratio*100:.0f}%")
                            break
                    timers['hpet_heal'] = now_hp

                # 3. 上 Buff（定時對隊友施放）
                for i in range(3):
                    if not self.var_hpet_buff_en[i].get():
                        continue
                    buff_timer = timers.get(f'hpet_buff_{i}', 0)
                    if now_hp - buff_timer > self.var_hpet_buff_sec[i].get():
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        self._click_hotbar(cx, cy, cw, ch, self.var_hpet_buff_key[i].get(), clicks=4)
                        time.sleep(0.2)
                        # 點第一個隊友（slot 1）
                        for slot in range(1, 8):
                            if _is_party_slot_occupied(cx, cy, cw, ch, slot):
                                pos = _get_party_slot_pos(cx, cy, cw, ch, slot)
                                game_click(pos['name'][0], pos['name'][1])
                                time.sleep(0.3)
                                break
                        timers[f'hpet_buff_{i}'] = now_hp
                        self.buffs += 1
                        self.log(f"高寵Buff{i+1}({self.var_hpet_buff_key[i].get()})")

                self._stats()
                time.sleep(0.1)
                continue  # 高寵不打怪

            # ── 自動練功循環 ──
            if not self.var_attack.get():
                time.sleep(0.5)
                continue

            mode = self.var_mode.get()
            self._status(f"掃描({mode})", '#f5a623')

            # 掃描+攻擊一體化（碰到怪物瞬間就打）
            self._set_state(BotState.SCANNING)
            pet = self.var_pet_en.get() or mode in ('地監', '召喚')  # 帶寵物的模式強制過濾
            bl = getattr(self, 'monster_blacklist', [])
            mon = scan_and_attack(cx, cy, cw, ch, hwnd, self.log, mode=mode, pet_filter=pet, blacklist=bl)

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
                    press_key(self.var_rng_key.get())
                elif mode == '召喚':
                    press_key(self.var_sum_atk.get())

                time.sleep(0.2)

                # ── 啟動預掃描（戰鬥中同時找下一隻怪） ──
                pre_scanner.start(cx, cy, cw, ch, hwnd, exclude=(mx, my))

                # ── 戰鬥等待 ──
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

                    # 技能施放（每 1 秒，地監按住不放不需要）
                    if mode != '地監' and now - last_skill > 1.0:
                        self._combat_skill(cx, cy, cw, ch)
                        last_skill = now

                    if mode == '地監':
                        # ── 地監：按住不放，偵測怪物死亡 ──
                        if not detect_monster_hp_bar(cx, cy, cw, ch, mx, my):
                            hp_bar_gone_count += 1
                            if hp_bar_gone_count >= 2:
                                killed = True
                                break
                        else:
                            hp_bar_gone_count = 0
                        time.sleep(0.2)
                    else:
                        # ── 遠程/定點/其他：原有邏輯 ──
                        # 死亡偵測方法1：怪物頭上 HP 條消失
                        if not detect_monster_hp_bar(cx, cy, cw, ch, mx, my):
                            hp_bar_gone_count += 1
                            if hp_bar_gone_count >= 2:
                                killed = True
                                break
                        else:
                            hp_bar_gone_count = 0

                        # 死亡偵測方法2：游標不再是劍
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

                # 近戰/地監：戰鬥結束放開滑鼠
                # 地監模式：戰鬥結束放開滑鼠
                if mode == '地監':
                    game_up()

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

                    # 快速撿物：原地按 F4
                    if self.var_loot.get() and mode not in ('定點','純定點','墮落之地') and self.running:
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        try:
                            interception.press('f4', presses=5, interval=0.1)
                        except:
                            for _ in range(5):
                                press_key('F4')
                                time.sleep(0.1)
                        self.loots += 1
                        self._stats()

                    # ── 自動回城販賣（每 N 次擊殺檢查） ──
                    if self.var_autosell_en.get() and self.kills % 20 == 0 and self.kills > 0:
                        # 簡易背包滿度估算：每 20 殺檢查，用擊殺數估算
                        est_full = min(95, self.kills * 2)  # 粗估
                        if est_full >= self.var_autosell_full.get():
                            self.log(f"背包估計 {est_full}% 滿，回城販賣")
                            self._click_hotbar(cx, cy, cw, ch, self.var_autosell_recall.get(), clicks=2)
                            self._status("回城販賣", '#f5a623')
                            alert('sell')
                            self.running = False
                            break

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

                # 幀差分偵測遠處移動目標（掃描找不到時的補充）
                if no_monster_count >= 2 and self.running:
                    far_targets = _frame_differ.detect_movement(cx, cy, cw, ch)
                    if far_targets:
                        fx, fy = far_targets[0]
                        self.log(f"幀差分→移動目標({fx},{fy})")
                        smooth_move(fx, fy)
                        human_sleep(0.1)
                        if get_cursor() != CURSOR_FINGER:
                            self._do_attack(fx, fy, cx, cy, cw, ch, hwnd)
                            no_monster_count = 0
                            continue

                if self.running and self.var_roam.get() and mode not in ('定點','純定點','墮落之地'):
                    # 用小地圖檢查偏移
                    drift = self._check_drift(cx, cy, cw, ch)

                    if drift > 0.15:  # 小地圖上偏移超過 15% = 走太遠
                        self._status(f"回定點", '#f5a623')
                        self.log(f"偏離定點({drift:.2f})，走回去")
                        self._walk_back_to_anchor(cx, cy, cw, ch, hwnd)
                        no_monster_count = 0
                    elif no_monster_count > 8:
                        # useless 計數器防卡死：連續找不到怪，隨機大距離移動脫困
                        self._status("脫困", '#f5a623')
                        self.log(f"連續{no_monster_count}次找不到怪，脫困移動")
                        dist = self.var_roam_dist.get() * 2
                        r = roam(cx, cy, cw, ch, hwnd, dist)
                        if r:
                            mx, my = r
                            self._do_attack(mx, my, cx, cy, cw, ch, hwnd)
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
          except Exception as e:
            import traceback
            self.log(f"[錯誤] {e} — 自動恢復")
            self.log(traceback.format_exc()[:200])
            time.sleep(1)
            continue

    def run(self):self.log("就緒");self.root.mainloop()

if __name__=="__main__":
    BotApp().run()
