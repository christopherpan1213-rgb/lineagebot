"""自動更新 — 從 GitHub 下載最新版"""
import urllib.request
import os
import sys

REPO = "christopherpan1213-rgb/lineagebot"
BRANCH = "main"
FILES = ["lineage_bot.py", "lineage_data.py"]
BASE_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

app_dir = os.path.dirname(os.path.abspath(__file__))

for fname in FILES:
    url = f"{BASE_URL}/{fname}"
    fpath = os.path.join(app_dir, fname)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LineageBot-Updater"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 100:
            print(f"  [跳過] {fname} - 下載內容異常")
            continue
        # 備份舊檔
        if os.path.exists(fpath):
            bak = fpath + ".bak"
            try:
                if os.path.exists(bak):
                    os.remove(bak)
                os.rename(fpath, bak)
            except:
                pass
        # 寫入新檔
        with open(fpath, "wb") as f:
            f.write(data)
        # 讀版本號
        ver = ""
        for line in data.decode("utf-8", errors="ignore").split("\n"):
            if line.strip().startswith("BOT_VERSION"):
                ver = line.split("=")[1].strip().strip("\"'")
                break
        if ver:
            print(f"  [OK] {fname} (v{ver})")
        else:
            print(f"  [OK] {fname}")
    except Exception as e:
        print(f"  [失敗] {fname} - {e}")
        print(f"         使用本地版本")

print("  更新完成!")
