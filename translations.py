"""
物体検出ラベルの日本語翻訳辞書。
Google Cloud Vision APIのLABEL_DETECTION結果を日本語で表示するために使用。
"""

OBJECT_TRANSLATIONS = {
    # 人物・身体
    "person": "人", "face": "顔", "head": "頭", "hand": "手",
    "finger": "指", "hair": "髪", "eye": "目", "smile": "笑顔",
    # 衣類
    "clothing": "衣類", "shirt": "シャツ", "jacket": "ジャケット",
    "shoe": "靴", "hat": "帽子", "glasses": "メガネ", "tie": "ネクタイ",
    "dress": "ドレス", "suit": "スーツ",
    # 家具・室内
    "furniture": "家具", "table": "テーブル", "chair": "椅子",
    "desk": "机", "shelf": "棚", "bed": "ベッド", "sofa": "ソファ",
    "door": "ドア", "window": "窓", "wall": "壁", "floor": "床",
    "ceiling": "天井", "room": "部屋", "building": "建物",
    # 電子機器
    "laptop": "ノートPC", "computer": "コンピュータ", "monitor": "モニター",
    "screen": "画面", "keyboard": "キーボード", "mouse": "マウス",
    "phone": "電話", "smartphone": "スマホ", "tablet": "タブレット",
    "camera": "カメラ", "television": "テレビ",
    # 食べ物・飲み物
    "food": "食べ物", "drink": "飲み物", "water": "水",
    "bottle": "ボトル", "cup": "カップ", "plate": "皿",
    # 乗り物
    "car": "車", "vehicle": "車両", "truck": "トラック",
    "bicycle": "自転車", "motorcycle": "バイク", "bus": "バス",
    "train": "電車", "airplane": "飛行機", "boat": "船",
    # 動物
    "animal": "動物", "dog": "犬", "cat": "猫", "bird": "鳥",
    "fish": "魚", "horse": "馬",
    # 自然
    "tree": "木", "flower": "花", "plant": "植物", "grass": "草",
    "sky": "空", "cloud": "雲", "mountain": "山",
    # 道具・物品
    "book": "本", "paper": "紙", "pen": "ペン", "bag": "鞄",
    "box": "箱", "tool": "工具", "machine": "機械", "metal": "金属",
    "plastic": "プラスチック", "wood": "木材", "glass": "ガラス",
    "light": "照明", "sign": "標識", "clock": "時計",
    # 産業・工場
    "equipment": "機器", "pipe": "パイプ", "wire": "ワイヤー",
    "cable": "ケーブル", "circuit board": "基板", "screw": "ネジ",
    "bolt": "ボルト", "nut": "ナット", "gear": "歯車",
    # その他
    "text": "文字", "number": "数字", "logo": "ロゴ",
    "photograph": "写真", "art": "アート", "design": "デザイン",
    "technology": "技術", "engineering": "エンジニアリング",
    "office": "オフィス", "indoor": "室内", "outdoor": "屋外",
}
