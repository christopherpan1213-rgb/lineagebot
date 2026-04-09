"""
HP/MP 即時監控工具 — 獨立程式，不影響 Bot
即時截取遊戲畫面，顯示 HP/MP 偵測狀況
"""
import tkinter as tk
import ctypes
import ctypes.wintypes
import numpy as np
import cv2
import time
import threading
from PIL import Image, ImageTk

ctypes.windll.shcore.SetProcessDpiAwareness(2)

# ═══════════════════════════════ 遊戲視窗 ═══════════════════════════════

def find_game():
    import win32gui
    r = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and 'Lineage Classic' in win32gui.GetWindowText(h):
            r.append((h, win32gui.GetWindowText(h)))
        return True
    win32gui.EnumWindows(cb, None)
    return r[0] if r else None

def get_rect(h):
    import win32gui
    cr = win32gui.GetClientRect(h)
    pt = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(h, ctypes.byref(pt))
    return pt.x, pt.y, cr[2], cr[3]

# ═══════════════════════════════ 截圖 ═══════════════════════════════

import json

HP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hp_config.json')

def save_hp_config(hp_bar, mp_bar):
    """儲存校準結果"""
    data = {}
    if hp_bar:
        data['hp_bar'] = list(hp_bar)
    if mp_bar:
        data['mp_bar'] = list(mp_bar)
    with open(HP_CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_hp_config():
    """讀取校準結果"""
    try:
        with open(HP_CONFIG_FILE) as f:
            data = json.load(f)
        hp = tuple(data['hp_bar']) if 'hp_bar' in data else None
        mp = tuple(data['mp_bar']) if 'mp_bar' in data else None
        return hp, mp
    except:
        return None, None

try:
    import dxcam
    _cam = dxcam.create(output_color="BGR")
    HAS_DXCAM = True
except:
    HAS_DXCAM = False

def grab(left, top, width, height):
    scr_w = ctypes.windll.user32.GetSystemMetrics(0)
    scr_h = ctypes.windll.user32.GetSystemMetrics(1)
    left, top = max(0, left), max(0, top)
    width = min(width, scr_w - left)
    height = min(height, scr_h - top)
    if width <= 0 or height <= 0:
        return np.zeros((10, 10, 3), dtype=np.uint8)
    if HAS_DXCAM:
        try:
            frame = _cam.grab(region=(left, top, left + width, top + height))
            if frame is not None:
                return frame
        except:
            pass
    from mss import mss
    sct = mss()
    shot = sct.grab({'left': left, 'top': top, 'width': width, 'height': height})
    return np.array(Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX'))[:, :, ::-1]

# ═══════════════════════════════ HP 偵測 ═══════════════════════════════

class HPDetector:
    def __init__(self):
        self.hp_bar = None  # (x1_pct, x2_pct, y_pct)
        self.mp_bar = None
        self.hp_ratio = 1.0
        self.mp_ratio = 1.0
        self.debug_info = ""
        # 嘗試讀取之前的校準結果
        hp, mp = load_hp_config()
        if hp:
            self.hp_bar = hp
            self.debug_info = f"從設定檔載入 HP 條位置"
        if mp:
            self.mp_bar = mp

    def find_bars(self, cx, cy, cw, ch):
        """自動找 HP/MP 條"""
        y_start = int(ch * 0.73)
        y_end = int(ch * 0.86)
        frame = grab(cx, cy + y_start, cw, y_end - y_start)
        if frame is None or frame.size == 0:
            self.debug_info = "截圖失敗"
            return False

        best_y = 0
        best_score = 0
        for y_off in range(frame.shape[0]):
            row = frame[y_off]
            r, g, b = row[:, 2].astype(int), row[:, 1].astype(int), row[:, 0].astype(int)
            dr = ((r > 120) & (g < 80) & (b < 40)).sum()
            db = ((b > 80) & ((b - r) > 20)).sum()
            if dr > 5 and db > 5 and dr + db > best_score:
                best_score = dr + db
                best_y = y_start + y_off

        if best_y == 0:
            self.debug_info = f"找不到 HP/MP 條（掃描 Y={y_start}-{y_end}，無 red+blue 共存行）"
            return False

        rows = grab(cx, cy + best_y - 1, cw, 3)
        if rows is None:
            return False
        r, g, b = rows[:,:,2].astype(int), rows[:,:,1].astype(int), rows[:,:,0].astype(int)
        dr_col = ((r > 120) & (g < 80) & (b < 40)).any(axis=0)
        db_col = ((b > 80) & ((b - r) > 20) & ((b - g) > 10)).any(axis=0)

        dr_xs = np.where(dr_col)[0]
        if len(dr_xs) > 3:
            gaps = np.diff(dr_xs)
            splits = np.where(gaps > 15)[0]
            if len(splits):
                clusters = np.split(dr_xs, splits + 1)
                largest = max(clusters, key=len)
            else:
                largest = dr_xs
            self.hp_bar = (largest[0] / cw, largest[-1] / cw, best_y / ch)

        db_xs = np.where(db_col)[0]
        if len(db_xs) > 3:
            gaps = np.diff(db_xs)
            splits = np.where(gaps > 15)[0]
            if len(splits):
                clusters = np.split(db_xs, splits + 1)
                largest = max(clusters, key=len)
            else:
                largest = db_xs
            self.mp_bar = (largest[0] / cw, largest[-1] / cw, best_y / ch)

        self.debug_info = f"HP條: Y={best_y} ({best_y/ch:.3f}) score={best_score}"
        if self.hp_bar:
            save_hp_config(self.hp_bar, self.mp_bar)
        return self.hp_bar is not None

    def read_bar(self, cx, cy, cw, ch, bar_info, bar_type='hp'):
        if not bar_info:
            return 1.0, "無條資訊"

        x1_pct, x2_pct, y_pct = bar_info
        y = int(ch * y_pct)
        scan_left = int(cw * 0.15)
        x_start = max(0, int(cw * x1_pct) - scan_left)
        x_end = min(cw, int(cw * x2_pct) + int(cw * 0.05))
        region_w = x_end - x_start
        if region_w < 5:
            return 1.0, "條太窄"

        frame = grab(cx + x_start, cy + y - 1, region_w, 3)
        if frame is None or frame.size == 0:
            return 1.0, "截圖失敗"

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
            return 0.0, "無填充色"

        first_fill = fill_xs[0]

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

        ww = 0
        x = first_fill - 1
        sk = 0
        while x >= 0 and not white_col[x] and sk < 4:
            x -= 1; sk += 1
        while x >= 0 and white_col[x]:
            ww += 1; x -= 1

        total = fill_width + ww
        if total < 3:
            return 1.0, "條太短"

        ratio = fill_width / total
        detail = f"fill={fill_width} white={ww} total={total}"
        return ratio, detail

    def update(self, cx, cy, cw, ch):
        if not self.hp_bar:
            self.find_bars(cx, cy, cw, ch)

        if self.hp_bar:
            self.hp_ratio, hp_detail = self.read_bar(cx, cy, cw, ch, self.hp_bar, 'hp')
        else:
            hp_detail = "未校準"

        if self.mp_bar:
            self.mp_ratio, mp_detail = self.read_bar(cx, cy, cw, ch, self.mp_bar, 'mp')
        else:
            mp_detail = "未校準"

        return hp_detail, mp_detail

# ═══════════════════════════════ GUI ═══════════════════════════════

class MonitorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HP/MP 即時監控")
        self.root.geometry("650x500")
        self.root.configure(bg='#1a1a2e')
        self.root.attributes('-topmost', True)

        self.detector = HPDetector()
        self.running = False

        # 上方：遊戲畫面預覽
        self.canvas = tk.Canvas(self.root, width=620, height=250, bg='#111', highlightthickness=0)
        self.canvas.pack(padx=10, pady=(10, 5))

        # HP/MP 大條
        bar_f = tk.Frame(self.root, bg='#1a1a2e')
        bar_f.pack(fill='x', padx=15, pady=5)

        for label, color in [("HP", "#e94560"), ("MP", "#3498db")]:
            r = tk.Frame(bar_f, bg='#1a1a2e')
            r.pack(fill='x', pady=3)
            tk.Label(r, text=label, bg='#1a1a2e', fg=color, font=('Consolas', 14, 'bold'), width=3).pack(side='left')
            cv = tk.Canvas(r, width=400, height=30, bg='#111', highlightthickness=1, highlightbackground='#333')
            cv.pack(side='left', padx=5)
            lbl = tk.Label(r, text="---%", bg='#1a1a2e', fg='white', font=('Consolas', 12), width=8)
            lbl.pack(side='left')
            if label == "HP":
                self.hp_cv, self.hp_lbl = cv, lbl
            else:
                self.mp_cv, self.mp_lbl = cv, lbl

        # 資訊面板
        info_f = tk.Frame(self.root, bg='#1a1a2e')
        info_f.pack(fill='both', expand=True, padx=10, pady=5)

        self.info_text = tk.Text(info_f, height=8, bg='#0d1117', fg='#58a6ff',
                                  font=('Consolas', 9), state='disabled', wrap='word')
        self.info_text.pack(fill='both', expand=True)

        # 按鈕
        btn_f = tk.Frame(self.root, bg='#1a1a2e')
        btn_f.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(btn_f, text="開始監控", font=('Arial', 11, 'bold'),
                  bg='#27ae60', fg='white', command=self._toggle).pack(side='left', padx=3)
        tk.Button(btn_f, text="重新校準", font=('Arial', 10),
                  bg='#e67e22', fg='white', command=self._recalibrate).pack(side='left', padx=3)
        tk.Button(btn_f, text="手動指定HP條", font=('Arial', 10),
                  bg='#8e44ad', fg='white', command=self._manual_calibrate).pack(side='left', padx=3)

    def _log(self, msg):
        self.info_text.config(state='normal')
        self.info_text.insert('end', f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.info_text.see('end')
        self.info_text.config(state='disabled')

    def _toggle(self):
        if self.running:
            self.running = False
        else:
            self.running = True
            threading.Thread(target=self._loop, daemon=True).start()

    def _recalibrate(self):
        self.detector.hp_bar = None
        self.detector.mp_bar = None
        self._log("已重置，下次更新會重新校準")

    def _manual_calibrate(self):
        """手動校準：截圖讓使用者點 HP 條左右端"""
        g = find_game()
        if not g:
            self._log("找不到遊戲視窗！")
            return

        cx, cy, cw, ch = get_rect(g[0])
        frame = grab(cx, cy, cw, ch)
        if frame is None:
            self._log("截圖失敗")
            return

        # 縮小顯示
        scale = min(800 / cw, 600 / ch)
        disp_w, disp_h = int(cw * scale), int(ch * scale)
        small = cv2.resize(frame, (disp_w, disp_h))

        # 開一個新視窗讓使用者點
        win = tk.Toplevel(self.root)
        win.title("點擊 HP 條的【左端】和【右端】")
        win.geometry(f"{disp_w+20}x{disp_h+60}")
        win.attributes('-topmost', True)

        img_rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        img_tk = ImageTk.PhotoImage(img_pil)

        cv_widget = tk.Canvas(win, width=disp_w, height=disp_h)
        cv_widget.pack(padx=10, pady=5)
        cv_widget.create_image(0, 0, anchor='nw', image=img_tk)
        cv_widget._img = img_tk  # 防止 GC

        clicks = []
        status = tk.Label(win, text="請點擊 HP 條的【左端】", font=('Arial', 11), fg='red')
        status.pack()

        def on_click(event):
            # 轉回遊戲座標
            gx = event.x / scale
            gy = event.y / scale
            clicks.append((gx / cw, gy / ch))

            # 畫標記
            cv_widget.create_oval(event.x - 5, event.y - 5, event.x + 5, event.y + 5,
                                   fill='red', outline='yellow', width=2)

            if len(clicks) == 1:
                status.config(text="請點擊 HP 條的【右端】")
            elif len(clicks) == 2:
                # 用兩個點的 Y 平均值和 X 範圍
                y_pct = (clicks[0][1] + clicks[1][1]) / 2
                x1_pct = min(clicks[0][0], clicks[1][0])
                x2_pct = max(clicks[0][0], clicks[1][0])
                self.detector.hp_bar = (x1_pct, x2_pct, y_pct)
                self._log(f"手動校準 HP: X={x1_pct:.3f}-{x2_pct:.3f} Y={y_pct:.3f}")
                status.config(text="HP 條已設定！請點擊 MP 條的【左端】", fg='blue')
            elif len(clicks) == 3:
                status.config(text="請點擊 MP 條的【右端】")
            elif len(clicks) == 4:
                y_pct = (clicks[2][1] + clicks[3][1]) / 2
                x1_pct = min(clicks[2][0], clicks[3][0])
                x2_pct = max(clicks[2][0], clicks[3][0])
                self.detector.mp_bar = (x1_pct, x2_pct, y_pct)
                self._log(f"手動校準 MP: X={x1_pct:.3f}-{x2_pct:.3f} Y={y_pct:.3f}")
                # 儲存到設定檔（Bot 也能讀）
                save_hp_config(self.detector.hp_bar, self.detector.mp_bar)
                self._log(f"已儲存到 {HP_CONFIG_FILE}")
                status.config(text="校準完成！已儲存", fg='green')
                win.after(1000, win.destroy)

        cv_widget.bind('<Button-1>', on_click)

    def _update_bar(self, cv, lbl, ratio, color):
        w = 400
        cv.delete('all')
        cv.create_rectangle(0, 0, w, 30, fill='#111')
        p = max(0, min(1, ratio))
        c = '#e74c3c' if p < 0.3 else ('#f5a623' if p < 0.6 else color)
        cv.create_rectangle(0, 0, int(w * p), 30, fill=c)
        cv.create_text(w // 2, 15, text=f"{p * 100:.1f}%", fill='white', font=('Consolas', 11, 'bold'))
        lbl.config(text=f"{p * 100:.1f}%")

    def _loop(self):
        self._log("開始監控...")
        while self.running:
            g = find_game()
            if not g:
                self._log("找不到遊戲視窗")
                time.sleep(2)
                continue

            cx, cy, cw, ch = get_rect(g[0])

            # 更新 HP/MP
            hp_detail, mp_detail = self.detector.update(cx, cy, cw, ch)

            # 更新 GUI（在主執行緒）
            hp_r = self.detector.hp_ratio
            mp_r = self.detector.mp_ratio
            debug = self.detector.debug_info

            def update_gui():
                self._update_bar(self.hp_cv, self.hp_lbl, hp_r, '#e94560')
                self._update_bar(self.mp_cv, self.mp_lbl, mp_r, '#3498db')

            self.root.after(0, update_gui)

            # 每 3 秒輸出一次 debug
            if not hasattr(self, '_last_log') or time.time() - self._last_log > 3:
                self.root.after(0, lambda: self._log(
                    f"HP={hp_r*100:.1f}% ({hp_detail}) | MP={mp_r*100:.1f}% ({mp_detail}) | {debug}"))
                self._last_log = time.time()

            # 截取底部 UI 預覽
            try:
                bottom = grab(cx, cy + int(ch * 0.78), cw, int(ch * 0.12))
                if bottom is not None:
                    # 畫 HP/MP 條位置標記
                    preview = bottom.copy()
                    ph = preview.shape[0]
                    if self.detector.hp_bar:
                        x1 = int(cw * self.detector.hp_bar[0])
                        x2 = int(cw * self.detector.hp_bar[1])
                        bar_y = int(ch * self.detector.hp_bar[2]) - int(ch * 0.78)
                        bar_y = max(0, min(ph - 1, bar_y))
                        cv2.rectangle(preview, (x1, max(0, bar_y - 3)), (x2, min(ph, bar_y + 3)), (0, 0, 255), 2)
                        cv2.putText(preview, f"HP {hp_r*100:.0f}%", (x1, max(15, bar_y - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    if self.detector.mp_bar:
                        x1 = int(cw * self.detector.mp_bar[0])
                        x2 = int(cw * self.detector.mp_bar[1])
                        bar_y = int(ch * self.detector.mp_bar[2]) - int(ch * 0.78)
                        bar_y = max(0, min(ph - 1, bar_y))
                        cv2.rectangle(preview, (x1, max(0, bar_y - 3)), (x2, min(ph, bar_y + 3)), (255, 0, 0), 2)
                        cv2.putText(preview, f"MP {mp_r*100:.0f}%", (x1, max(15, bar_y - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)

                    # 縮放到 canvas 大小
                    disp = cv2.resize(preview, (620, 250))
                    img_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                    img_pil = Image.fromarray(img_rgb)
                    img_tk = ImageTk.PhotoImage(img_pil)

                    def show_preview():
                        self.canvas.delete('all')
                        self.canvas.create_image(0, 0, anchor='nw', image=img_tk)
                        self.canvas._img = img_tk
                    self.root.after(0, show_preview)
            except:
                pass

            time.sleep(0.5)

        self._log("監控停止")

    def run(self):
        self.root.mainloop()

if __name__ == '__main__':
    MonitorApp().run()
