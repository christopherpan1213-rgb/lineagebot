# LineageBot 開發規範

## 專案概述
天堂經典版（Lineage Classic）自動化 Bot，使用 Interception 驅動操控滑鼠/鍵盤。
主程式：`lineage_bot.py`，審計工具：`audit_bot.py`

## 必遵守規則

### 1. 滑鼠拖曳必須用 move_relative
遊戲用 Raw Input 讀滑鼠。拖曳攻擊**必須**用 `interception.move_relative(rx, ry)` 做增量移動。
`move_exact()`/`move_to()` 只用於**定位**（移到怪物、移到快捷欄），不用於拖曳。

### 2. 鍵盤被擋，用滑鼠點快捷欄
遊戲反外掛擋掉所有模擬鍵盤。喝水/技能一律用滑鼠點擊快捷欄格子。
- 道具（紅水/藍水）：雙擊（120ms 間隔）
- 法術（治癒/Buff）：連點 4 下

### 3. 拖曳攻擊時序
```
move_exact(目標)    → sleep(0.08~0.1)
game_down()         → sleep(0.15)        ← 關鍵等待
move_relative ×12步 → 每步 20-40ms
sleep(0.08)         → game_up()
```
拖曳距離 150-250px，方向任意（主要往下）。

### 4. 不要用管理員權限
Interception 驅動本身有權限，不需要 UAC 提權。

### 5. 座標用比例不用絕對值
用戶電腦 (1850×1387) 和朋友電腦 (770×820) 解析度差很多，所有位置必須用比例計算。

### 6. 掃描速度
- 遠程/定點：10ms
- 近戰：15ms
- 不要低於 10ms，遊戲來不及更新游標

### 7. 喝水後回到怪物位置
點快捷欄會移走滑鼠，喝完水只做 `move_exact(mx, my)` 回怪物位置，讓主迴圈 retry_attack 處理。

## 修改後必做
1. `python audit_bot.py` 跑兩次，確認 0 新 BUG
2. 確認打怪流程能動
3. 確認 exe 能啟動、start.bat 流程正常

## 攻擊模式一覽

| 模式 | 攻擊方式 | 戰鬥技能 | 特殊行為 |
|------|---------|----------|---------|
| 近戰 | 按住怪物不放 | skills.use_next() | — |
| 遠程 | move_relative 拖曳 + 攻擊鍵 | press_key(攻擊鍵) | 攻擊後後退保持距離 |
| 定點/純定點/墮落 | 攻擊鍵 + 拖曳 | press_key(攻擊鍵) | 墮落之地定時北移 |
| 召喚 | 拖曳 + 召喚鍵 | press_key(召喚鍵) | — |
| 隊伍 | 依角色（坦/輸出/補/輔） | 依角色 | — |
| 地監 | 按住怪物不放 | skills.use_next() | 寵物過濾+F4拾取+寵物補血 |

## 可整合的開源技術（已研究）

以下技術來自 GitHub 開源 Lineage Bot 專案，已寫入 agent 設定：

1. **形態學文字偵測找怪** — `threshold(252) + morphologyEx + findContours`，比游標偵測更快更準
2. **Bresenham 平滑滑鼠移動** — 模擬人類軌跡，反偵測
3. **HSV 色域偵測** — 比 RGB 閾值對光線變化更強健
4. **幀差分偵測遠處目標** — 多幀比較找移動物體
5. **模板比對確認選中** — `matchTemplate` 驗證操作是否成功
6. **圖像差異判斷技能冷卻** — `ImageChops.difference` 比對截圖
7. **雙 Random 隨機延遲** — 更接近常態分布的操作間隔
8. **排除區域** — 掃描時跳過 UI 區域避免誤判
9. **useless 計數器防卡死** — 連續 N 次無效操作自動脫困

## 檔案結構
- `lineage_bot.py` — 主程式（GUI + 戰鬥邏輯）
- `audit_bot.py` — 程式碼審計工具
- `hp_monitor.py` — HP/MP 像素偵測
- `update.py` — 自動更新系統
- `start.bat` — 啟動腳本（含更新檢查）
- `lineage_data.py` — 資料/常數
