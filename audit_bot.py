"""
天堂 Bot 自動審計腳本
每次修改 lineage_bot.py 後執行，檢查常見 bug
用法: python audit_bot.py
"""
import ast, re, sys, os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lineage_bot.py')
errors = []
warnings = []

def error(msg): errors.append(f"[BUG] {msg}")
def warn(msg): warnings.append(f"[WARN] {msg}")

print("=" * 60)
print("  天堂 Bot 程式碼審計")
print("=" * 60)

# ── 1. 語法檢查 ──
print("\n[1] 語法檢查...")
try:
    with open(FILE, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source)
    print("  OK: 語法正確")
except SyntaxError as e:
    error(f"語法錯誤: {e}")
    print(f"  FAIL: {e}")
    sys.exit(1)

lines = source.split('\n')

# ── 2. 未定義變數引用 ──
print("\n[2] 檢查常見變數名錯誤...")
# 在 f-string 中引用的變數
for i, line in enumerate(lines, 1):
    # 檢查 f-string 中的 {key} 但函式中沒有 key = ...
    if 'f"' in line or "f'" in line:
        fvars = re.findall(r'\{(\w+)', line)
        for v in fvars:
            if v in ('self', 'hp', 'mp', 'k', 'key', 'mode', 'i', 'n', 'e', 'f', 's', 'c', 'p', 'r', 'g', 'b'):
                continue  # 常見短名跳過

# 專門檢查 log() 裡用 key 但 scope 裡只有 k
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if 'self.log(f"' in stripped or "self.log(f'" in stripped:
        if '{key}' in stripped:
            # 往上找最近的 k = 或 key =
            found_key = False
            for j in range(i-1, max(0, i-20), -1):
                if re.match(r'\s+key\s*=', lines[j-1]):
                    found_key = True
                    break
                if re.match(r'\s+k\s*=', lines[j-1]):
                    # 有 k 但用了 key → bug
                    error(f"第 {i} 行: log 中用 {{key}} 但變數名是 k")
                    break
                if lines[j-1].strip().startswith('def ') or lines[j-1].strip().startswith('class '):
                    break

# ── 3. press_key 殘留檢查 ──
print("\n[3] 檢查 press_key 殘留（應該都改成 _click_hotbar）...")
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('#') or stripped.startswith('def press_key'):
        continue
    if 'press_key(' in stripped and 'fallback' not in stripped and 'keyboard.on_press_key' not in stripped:
        warn(f"第 {i} 行: 仍在使用 press_key() — 遊戲可能擋鍵盤: {stripped[:60]}")

# ── 4. interception 直接呼叫（無保護）──
print("\n[4] 檢查 interception 直接呼叫（應該用 game_click/game_up 等）...")
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('#'):
        continue
    if 'interception.' in stripped and 'HAS_INTERCEPTION' not in stripped:
        # 允許: auto_capture_devices, 在 try/except 中, 在 if HAS_INTERCEPTION 區塊中
        if 'auto_capture_devices' in stripped:
            continue
        # 檢查前 5 行有沒有 try: 或 if HAS_INTERCEPTION
        context = '\n'.join(lines[max(0,i-6):i])
        if 'try:' in context or 'HAS_INTERCEPTION' in context:
            continue
        warn(f"第 {i} 行: 直接呼叫 interception（無 fallback）: {stripped[:60]}")

# ── 5. _click_hotbar 返回 None 檢查 ──
print("\n[5] 檢查 _get_hotbar_pos 是否覆蓋所有 F 鍵...")
# 從代碼中提取 x_map 的 keys
hotbar_keys = set()
for i, line in enumerate(lines, 1):
    m = re.findall(r'x_map\[(\d+)\]', line)
    for k in m:
        hotbar_keys.add(int(k))
if hotbar_keys:
    missing = set(range(1, 13)) - hotbar_keys
    if missing:
        error(f"_get_hotbar_pos 缺少 F{missing} 的位置映射")
    else:
        print(f"  OK: F1-F12 全部有位置 ({sorted(hotbar_keys)})")

# ── 6. GUI 變數是否有對應邏輯 ──
print("\n[6] 檢查 GUI 開關是否接到邏輯...")
gui_vars = {}
for i, line in enumerate(lines, 1):
    m = re.match(r'\s+self\.(var_\w+)\s*=\s*tk\.\w+Var', line)
    if m:
        gui_vars[m.group(1)] = i

# 哪些 var 有在 _loop/_check_survival/_do_attack/_combat_skill 中被 .get()
bot_logic_start = None
bot_logic_end = len(lines)
for i, line in enumerate(lines, 1):
    if 'def _loop(self)' in line:
        bot_logic_start = i
    if 'def _check_survival' in line and bot_logic_start is None:
        bot_logic_start = i

if bot_logic_start:
    # 搜尋整個檔案（GUI 變數在多個方法中被使用）
    all_code = source
    unused_gui = []
    for var, line_num in sorted(gui_vars.items()):
        # 計算 .get() 被呼叫的次數（排除定義行）
        get_count = all_code.count(f'self.{var}.get()')
        idx_count = all_code.count(f'self.{var}[')
        # 排除 GUI 專用的變數
        if var in ('var_class', 'var_hotkey'):
            continue
        # 只有在定義處的 1 次引用 = 沒被其他地方使用
        if get_count == 0 and idx_count == 0:
            unused_gui.append((var, line_num))
    # 只報告真正空殼的功能
    known_unimplemented = {'var_antipk', 'var_pk_act', 'var_humanize', 'var_sslog', 'var_map'}
    for var, line_num in unused_gui:
        if var in known_unimplemented:
            continue  # 已知開發中，不重複警告
        warn(f"第 {line_num} 行: {var} 定義了 GUI 但從未被 .get() 呼叫")

# ── 7. BarReader 一致性 ──
print("\n[7] 檢查 BarReader 與生存系統的一致性...")
if 'bars._hp_max' in source and 'bars._hp_cur' in source:
    # 檢查是否還在用舊的 cur/max 判斷
    for i, line in enumerate(lines, 1):
        if 'bars._hp_max' in line and 'bars._hp_cur' in line:
            warn(f"第 {i} 行: 仍在用 bars._hp_cur/_hp_max（像素模式下永遠為 0）")
        if 'hp_max > 0' in line and 'bars' in lines[max(0,i-5):i+1].__repr__():
            pass  # context check

# Check that hp ratio is used for potion decisions
survival_code = ''
for i, line in enumerate(lines, 1):
    if 'def _check_survival' in line:
        for j in range(i, min(i+100, len(lines))):
            survival_code += lines[j] + '\n'
        break

if 'need_hp = hp < hp_thr' in survival_code or 'need_hp = hp <' in survival_code:
    print("  OK: 紅水用 HP 比例判斷")
else:
    warn("紅水判斷可能沒用 HP 比例（像素偵測結果）")

if 'need_mp = mp < mp_thr' in survival_code or 'need_mp = mp <' in survival_code:
    print("  OK: 藍水用 MP 比例判斷")
else:
    warn("藍水判斷可能沒用 MP 比例")

# ── 8. 狀態機轉換 ──
print("\n[8] 檢查狀態機轉換...")
state_calls = []
for i, line in enumerate(lines, 1):
    m = re.search(r'_set_state\(BotState\.(\w+)\)', line)
    if m:
        state_calls.append((i, m.group(1)))
if state_calls:
    print(f"  共 {len(state_calls)} 次狀態轉換呼叫")

# ── 9. 字型 fallback ──
print("\n[9] 檢查字型硬編碼...")
hardcoded_fonts = 0
for i, line in enumerate(lines, 1):
    if "'Microsoft JhengHei'" in line and '_pick_font' not in line and '_UI_FONT' not in line and 'fallback' not in lines[max(0,i-3):i+1].__repr__():
        hardcoded_fonts += 1
        if hardcoded_fonts <= 3:
            warn(f"第 {i} 行: 硬編碼字型 'Microsoft JhengHei'")
if hardcoded_fonts == 0:
    print("  OK: 無硬編碼字型")

# ── 10. 版本號 ──
print("\n[10] 版本資訊...")
for i, line in enumerate(lines, 1):
    if line.startswith('BOT_VERSION'):
        print(f"  {line.strip()}")
        break

# ═══ 結果 ═══
print("\n" + "=" * 60)
if errors:
    print(f"  發現 {len(errors)} 個 BUG:")
    for e in errors:
        print(f"    {e}")
if warnings:
    print(f"  發現 {len(warnings)} 個警告:")
    for w in warnings:
        print(f"    {w}")
if not errors and not warnings:
    print("  全部通過!")
print("=" * 60)

sys.exit(1 if errors else 0)
