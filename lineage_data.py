"""
天堂經典版遊戲資料庫
包含：地圖、怪物、NPC、道具、練功路線
"""

# ═══════════════════════════════════════════════════════════
# 地圖資料
# ═══════════════════════════════════════════════════════════

VILLAGES = {
    "說話之島": {"en": "Talking Island", "level": "1-15", "teleporter": True},
    "隱藏之谷": {"en": "Hidden Valley", "level": "1-15", "teleporter": True},
    "銀騎士村莊": {"en": "Silver Knight Village", "level": "10-25", "teleporter": True},
    "古魯丁村": {"en": "Gludin Village", "level": "15-30", "teleporter": True},
    "肯特村": {"en": "Kent Village", "level": "15-25", "teleporter": True},
    "風木村": {"en": "Windawood Village", "level": "20-35", "teleporter": True},
    "奇岩村": {"en": "Giran Village", "level": "25-40", "teleporter": True},
    "海音村": {"en": "Heine Village", "level": "30-45", "teleporter": True},
    "象牙塔村": {"en": "Ivory Tower Village", "level": "25-40", "teleporter": True},
    "亞丁城": {"en": "Aden Castle Town", "level": "35-50+", "teleporter": True},
    "燃柳村": {"en": "Burning Willow Village", "level": "15-30", "teleporter": True},
    "歐瑞村": {"en": "Orei Village", "level": "20-35", "teleporter": True},
    "威頓村": {"en": "Weldern Village", "level": "30-45", "teleporter": True},
    "妖精森林": {"en": "Elven Forest", "level": "10-25", "teleporter": True},
}

DUNGEONS = {
    "冒險洞穴": {"location": "說話之島", "floors": "1-2F", "level": "1-15"},
    "古魯丁地監": {"location": "古魯丁村", "floors": "1-7F", "level": "15-35"},
    "眠龍洞穴": {"location": "妖精森林", "floors": "1-3F", "level": "10-25"},
    "騎士地監": {"location": "銀騎士村莊", "floors": "1-4F", "level": "15-30"},
    "奇岩地監": {"location": "奇岩村", "floors": "1-4F", "level": "30-45"},
    "龍之谷地監": {"location": "龍之谷", "floors": "1-7F", "level": "35-55"},
    "海音地監": {"location": "海音村", "floors": "1-4F", "level": "30-45"},
    "象牙塔": {"location": "象牙塔村", "floors": "1-8F", "level": "8-60"},
    "水晶洞穴": {"location": "歐瑞", "floors": "1-3F", "level": "14-56"},
    "傲慢之塔": {"location": "亞丁", "floors": "1-30F+", "level": "45+"},
    "遺忘之島": {"location": "獨立區域", "floors": "地表", "level": "20-53"},
    "墮落的祝福之地": {"location": "特殊入場", "floors": "-", "level": "20+", "note": "需沙漏道具"},
}

# ═══════════════════════════════════════════════════════════
# 傳送師資料
# ═══════════════════════════════════════════════════════════

TELEPORTERS = {
    "銀騎士村莊": {
        "npc": "麥特",
        "destinations": {
            "肯特村": 55, "風木村": 55, "海音村": 55,
            "古魯丁村": 132, "奇岩村": 132, "亞丁城": 132,
            "燃柳村": 198, "威頓村": 198, "乞丐村": 198,
            "銀翼村": 246, "歐瑞村": 246,
            "正義神殿": 330, "混亂神殿": 330, "肯特葡萄園": 330,
            "說話之島": 770, "狄亞德要塞": 7480,
        }
    }
}

# ═══════════════════════════════════════════════════════════
# 怪物資料
# ═══════════════════════════════════════════════════════════

MONSTERS = [
    # 說話之島 / 成長之島
    {"name": "哥布林", "level": 1, "hp": 15, "exp": 5, "aggro": False, "location": "說話之島"},
    {"name": "小惡魔", "level": 2, "hp": 15, "exp": 5, "aggro": False, "location": "說話之島"},
    {"name": "地靈", "level": 3, "hp": 20, "exp": 10, "aggro": False, "location": "說話之島"},
    {"name": "惡魔弓箭手", "level": 4, "hp": 25, "exp": 10, "aggro": False, "location": "說話之島"},
    {"name": "鹿", "level": 5, "hp": 20, "exp": 10, "aggro": False, "location": "說話之島"},
    {"name": "牧羊犬", "level": 6, "hp": 40, "exp": 26, "aggro": False, "location": "說話之島"},
    {"name": "矮人", "level": 7, "hp": 45, "exp": 26, "aggro": False, "location": "說話之島"},
    {"name": "山豬", "level": 8, "hp": 55, "exp": 37, "aggro": False, "location": "說話之島"},
    {"name": "史萊姆", "level": 8, "hp": 30, "exp": 37, "aggro": False, "location": "說話之島"},
    {"name": "殭屍", "level": 9, "hp": 60, "exp": 37, "aggro": True, "location": "說話之島"},
    {"name": "浮眼", "level": 10, "hp": 50, "exp": 50, "aggro": True, "location": "說話之島"},
    {"name": "惡魔戰士", "level": 12, "hp": 70, "exp": 65, "aggro": True, "location": "說話之島"},
    {"name": "骷髏", "level": 14, "hp": 90, "exp": 101, "aggro": True, "location": "說話之島"},
    {"name": "石頭乾德", "level": 18, "hp": 180, "exp": 170, "aggro": False, "location": "說話之島"},

    # 象牙塔
    {"name": "紙人", "level": 8, "hp": 40, "exp": 65, "aggro": False, "location": "象牙塔 4-5F"},
    {"name": "密密", "level": 15, "hp": 120, "exp": 226, "aggro": True, "location": "象牙塔 4-5F"},
    {"name": "影魔", "level": 15, "hp": 110, "exp": 322, "aggro": True, "location": "象牙塔 6-8F"},
    {"name": "鬼魂(綠)", "level": 17, "hp": 120, "exp": 290, "aggro": False, "location": "象牙塔 6-7F"},
    {"name": "鬼魂(紅)", "level": 20, "hp": 120, "exp": 401, "aggro": False, "location": "象牙塔 6-7F"},
    {"name": "死神", "level": 22, "hp": 140, "exp": 485, "aggro": True, "location": "象牙塔 6-8F"},
    {"name": "活鎧甲", "level": 31, "hp": 300, "exp": 962, "aggro": True, "location": "象牙塔 4-5F, 8F"},
    {"name": "高崙鋼鐵怪", "level": 35, "hp": 650, "exp": 1226, "aggro": True, "location": "象牙塔"},
    {"name": "惡魔", "level": 60, "hp": 2200, "exp": 3722, "aggro": True, "location": "象牙塔 8F"},

    # 水晶洞穴
    {"name": "雪人", "level": 14, "hp": 80, "exp": 197, "aggro": False, "location": "水晶洞穴 1F"},
    {"name": "高崙冰石人", "level": 17, "hp": 220, "exp": 325, "aggro": False, "location": "水晶洞穴 1-3F"},
    {"name": "冰人", "level": 26, "hp": 200, "exp": 677, "aggro": False, "location": "水晶洞穴 1-3F"},
    {"name": "冰原老虎", "level": 27, "hp": 270, "exp": 730, "aggro": False, "location": "水晶洞穴 1-3F"},
    {"name": "雪怪", "level": 30, "hp": 400, "exp": 901, "aggro": False, "location": "水晶洞穴 1-3F"},
    {"name": "冰之女皇", "level": 56, "hp": 1800, "exp": 3137, "aggro": True, "location": "水晶洞穴 3F", "boss": True},

    # 歐瑞
    {"name": "諾銀", "level": 8, "hp": 60, "exp": 65, "aggro": False, "location": "歐瑞"},
    {"name": "熊", "level": 12, "hp": 110, "exp": 145, "aggro": False, "location": "歐瑞"},
    {"name": "艾爾摩士兵", "level": 21, "hp": 150, "exp": 442, "aggro": False, "location": "歐瑞"},
    {"name": "艾爾摩法師", "level": 22, "hp": 130, "exp": 485, "aggro": False, "location": "歐瑞"},
    {"name": "艾爾摩將軍", "level": 25, "hp": 180, "exp": 626, "aggro": False, "location": "歐瑞"},

    # 遺忘之島
    {"name": "鱷魚", "level": 20, "hp": 150, "exp": 401, "aggro": False, "location": "遺忘之島"},
    {"name": "蜥蜴人", "level": 20, "hp": 180, "exp": 401, "aggro": False, "location": "遺忘之島"},
    {"name": "狼人", "level": 34, "hp": 180, "exp": 1157, "aggro": True, "location": "遺忘之島"},
    {"name": "夏洛伯", "level": 34, "hp": 170, "exp": 1157, "aggro": True, "location": "遺忘之島"},
    {"name": "歐熊", "level": 35, "hp": 250, "exp": 1226, "aggro": True, "location": "遺忘之島"},
    {"name": "黑暗精靈", "level": 35, "hp": 350, "exp": 1226, "aggro": True, "location": "遺忘之島"},
    {"name": "卡司特", "level": 36, "hp": 240, "exp": 1297, "aggro": True, "location": "遺忘之島"},
    {"name": "食人妖精", "level": 37, "hp": 300, "exp": 1370, "aggro": True, "location": "遺忘之島"},
    {"name": "巨斧牛人", "level": 37, "hp": 300, "exp": 1370, "aggro": True, "location": "遺忘之島"},
    {"name": "萊肯", "level": 37, "hp": 220, "exp": 1370, "aggro": True, "location": "遺忘之島"},
    {"name": "蛇女藍", "level": 37, "hp": 240, "exp": 1370, "aggro": True, "location": "遺忘之島"},
    {"name": "蛇女綠", "level": 37, "hp": 240, "exp": 1370, "aggro": True, "location": "遺忘之島"},
    {"name": "楊果里恩", "level": 38, "hp": 250, "exp": 1445, "aggro": True, "location": "遺忘之島"},
    {"name": "格利芬", "level": 41, "hp": 410, "exp": 1682, "aggro": True, "location": "遺忘之島"},
    {"name": "哈維", "level": 41, "hp": 250, "exp": 1682, "aggro": True, "location": "遺忘之島"},
    {"name": "鏈鎚牛人", "level": 41, "hp": 430, "exp": 1682, "aggro": True, "location": "遺忘之島"},
    {"name": "巨大鱷魚", "level": 42, "hp": 440, "exp": 1765, "aggro": True, "location": "遺忘之島"},
    {"name": "變形怪", "level": 42, "hp": 350, "exp": 1765, "aggro": True, "location": "遺忘之島"},
    {"name": "卡司特王", "level": 43, "hp": 360, "exp": 1850, "aggro": True, "location": "遺忘之島"},
    {"name": "多羅", "level": 43, "hp": 330, "exp": 1850, "aggro": True, "location": "遺忘之島"},
    {"name": "食人妖精王", "level": 45, "hp": 480, "exp": 2026, "aggro": True, "location": "遺忘之島"},
    {"name": "亞魯巴", "level": 45, "hp": 550, "exp": 2026, "aggro": True, "location": "遺忘之島"},
    {"name": "亞力安", "level": 47, "hp": 600, "exp": 2210, "aggro": True, "location": "遺忘之島"},
    {"name": "邪惡蜥蜴", "level": 48, "hp": 800, "exp": 2305, "aggro": True, "location": "遺忘之島"},
    {"name": "獨眼巨人", "level": 50, "hp": 880, "exp": 2501, "aggro": True, "location": "遺忘之島"},
    {"name": "飛龍", "level": 53, "hp": 1200, "exp": 2810, "aggro": True, "location": "遺忘之島"},

    # 墮落的祝福之地
    {"name": "墮落的妖魔法師", "level": 25, "hp": 200, "exp": 600, "aggro": True, "location": "墮落的祝福之地"},
    {"name": "墮落的妖魔鬥士", "level": 27, "hp": 250, "exp": 700, "aggro": True, "location": "墮落的祝福之地"},
    {"name": "墮落的妖魔弓箭手", "level": 26, "hp": 180, "exp": 650, "aggro": True, "location": "墮落的祝福之地"},
]

# 怪物名稱集合（用於偵測）
MONSTER_NAMES = {m["name"] for m in MONSTERS}

# 按地圖分組
def get_monsters_by_location(location):
    return [m for m in MONSTERS if location in m["location"]]

# ═══════════════════════════════════════════════════════════
# 道具資料
# ═══════════════════════════════════════════════════════════

POTIONS = {
    # HP 藥水
    "紅色藥水": {"type": "hp", "recovery": 16, "weight": 7.8, "price": 20},
    "橙色藥水": {"type": "hp", "recovery": 46, "weight": 9.8, "price": 110},
    "白色藥水": {"type": "hp", "recovery": 75, "weight": 11.7, "price": 330},
    "濃縮體力恢復劑": {"type": "hp", "recovery": 16, "weight": 3.9, "price": 30},
    "濃縮強力體力恢復劑": {"type": "hp", "recovery": 46, "weight": 4.9, "price": 165},
    "濃縮終極體力恢復劑": {"type": "hp", "recovery": 75, "weight": 5.9, "price": 495},
    "古代體力恢復藥水": {"type": "hp", "recovery": 16, "weight": 7.8, "price": None, "note": "無喝水延遲"},
    "古代強力體力恢復劑": {"type": "hp", "recovery": 46, "weight": 9.8, "price": None, "note": "無喝水延遲"},
    "古代終極體力恢復劑": {"type": "hp", "recovery": 75, "weight": 11.7, "price": None, "note": "無喝水延遲"},
    # MP 藥水
    "藍色藥水": {"type": "mp", "recovery": 50, "weight": 7.8, "price": None},
    # Buff 藥水
    "綠色藥水": {"type": "buff", "effect": "移速x1.33 5分鐘", "weight": 4.7, "price": 140},
    "高級綠色藥水": {"type": "buff", "effect": "移速x1.33 30分鐘", "weight": 14.1, "price": 900},
    "勇敢藥水": {"type": "buff", "effect": "騎士加速", "weight": 9.4, "price": 400},
    "慎重藥水": {"type": "buff", "effect": "法師魔攻+2", "weight": 9.4, "price": 300},
    "自我加速藥水": {"type": "buff", "effect": "加速", "weight": 4.7, "price": 299},
    # 解毒
    "翡翠藥水": {"type": "cure", "effect": "解除所有毒", "weight": 7.8, "price": 55},
}

SCROLLS = {
    "瞬間移動卷軸": {"effect": "隨機傳送", "weight": 0.63, "price": 74},
    "傳送回家的卷軸": {"effect": "回城", "weight": 0.63, "price": 194},
    "血盟傳送卷軸": {"effect": "傳送至血盟", "weight": 0.63, "price": 194},
    "鑑定卷軸": {"effect": "鑑定物品", "weight": 0.63, "price": 74},
    "復活卷軸": {"effect": "復活玩家", "weight": 0.63, "price": 1196},
    "變身卷軸": {"effect": "變身30分鐘", "weight": 0.63, "price": None},
    "對盔甲施法的卷軸": {"effect": "防具+1~3", "weight": 0.63, "price": None},
    "對武器施法的卷軸": {"effect": "武器+1~3", "weight": 0.63, "price": None},
}

# ═══════════════════════════════════════════════════════════
# 練功路線推薦
# ═══════════════════════════════════════════════════════════

LEVELING_GUIDE = [
    {"level": "1-5", "location": "隱藏之谷 / 木人區", "monsters": ["哥布林", "小惡魔"], "tip": "新手任務跟著做"},
    {"level": "5-10", "location": "成長之島", "monsters": ["牧羊犬", "矮人", "山豬"], "tip": "經驗倍率極高"},
    {"level": "10-15", "location": "成長之島 / 冒險洞穴", "monsters": ["骷髏", "殭屍", "浮眼"], "tip": "殭屍8.5倍經驗"},
    {"level": "15-20", "location": "古魯丁地監 1-3F", "monsters": ["骷髏", "殭屍"], "tip": "銀武器打不死系x2"},
    {"level": "20-25", "location": "古魯丁地監 3-5F / 騎士地監", "monsters": ["狼人", "夏洛伯", "石頭乾德"], "tip": "開始需要組隊"},
    {"level": "25-30", "location": "古魯丁地監 5-7F / 食屍地", "monsters": ["狼人", "楊果里恩"], "tip": "食屍地賺錢"},
    {"level": "30-35", "location": "奇岩地監 / 遺忘之島", "monsters": ["黑暗精靈", "歐熊", "食人妖精"], "tip": "加入血盟"},
    {"level": "35-40", "location": "遺忘之島 / 龍之谷", "monsters": ["格利芬", "鏈鎚牛人", "多羅"], "tip": "必須組隊"},
    {"level": "40-45", "location": "遺忘之島深處", "monsters": ["食人妖精王", "亞魯巴", "邪惡蜥蜴"], "tip": "帶足藥水和回城卷"},
    {"level": "45-50", "location": "遺忘之島 / 傲慢之塔", "monsters": ["獨眼巨人", "飛龍"], "tip": "50等可二轉"},
    {"level": "50+", "location": "傲慢之塔 / 龍之谷深層", "monsters": ["高階惡魔", "龍族"], "tip": "極高PVP風險"},
]

# ═══════════════════════════════════════════════════════════
# NPC 商店（妖精森林最便宜）
# ═══════════════════════════════════════════════════════════

SHOP_PRICES = {
    "妖精森林": {
        "自我加速藥水": 299, "精靈玉": 149, "魔法寶石": 299,
        "瞬間移動卷軸": 74, "傳送回家的卷軸": 194,
        "鑑定卷軸": 74, "復活卷軸": 1196, "解毒藥水": 104,
    },
    "象牙塔": {
        "自我加速藥水": 330, "精靈玉": 165, "魔法寶石": 330,
        "瞬間移動卷軸": 82, "傳送回家的卷軸": 214,
        "鑑定卷軸": 82, "復活卷軸": 1320, "解毒藥水": 115,
    }
}

# ═══════════════════════════════════════════════════════════
# 遊戲機制
# ═══════════════════════════════════════════════════════════

GAME_MECHANICS = {
    "負重50%": "停止自然 HP/MP 回復",
    "銀/密銀武器": "對不死系怪物傷害 x2",
    "旅館休息": "HP/MP 回復速度 x3",
    "古代藥水": "無喝水延遲",
    "濃縮藥水": "重量約普通版一半",
    "武器強化安全值": "+6（超過可能碎裂）",
    "防具強化安全值": "+4（超過可能碎裂）",
}
