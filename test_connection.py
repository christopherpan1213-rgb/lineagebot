"""測試能不能連到 GitHub 下載檔案"""
import urllib.request
import ssl

url = "https://raw.githubusercontent.com/christopherpan1213-rgb/lineagebot/main/lineage_bot.py"

print("測試連線到 GitHub...")
print(f"URL: {url}")
print()

# 方法 1: 正常連線
try:
    req = urllib.request.Request(url, headers={"User-Agent": "LineageBot"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read(200).decode("utf-8")
        print("[方法1] 成功！前 200 字:")
        print(data[:200])
except Exception as e:
    print(f"[方法1] 失敗: {e}")
    print()

    # 方法 2: 跳過 SSL 驗證
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "LineageBot"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = resp.read(200).decode("utf-8")
            print("[方法2 無SSL驗證] 成功！前 200 字:")
            print(data[:200])
    except Exception as e2:
        print(f"[方法2 無SSL驗證] 也失敗: {e2}")

input("\n按 Enter 關閉...")
