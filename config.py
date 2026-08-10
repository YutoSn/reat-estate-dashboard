"""アプリ全体の設定。"""

import datetime

# 対象都道府県コード
# 03: 岩手県, 04: 宮城県, 06: 山形県, 08: 茨城県,
# 11: 埼玉県, 12: 千葉県, 13: 東京都, 14: 神奈川県
TARGET_PREFECTURE_CODES = ["03", "04", "06", "08", "11", "12", "13", "14"]

# 不動産取引データの取得年数（過去N年）
TARGET_YEARS = 20

# 統計データをグラフ表示する際の遡り年数
STATS_HISTORY_YEARS = 30

# データベースファイル
DUCKDB_FILE = "land_price.duckdb"

# 市区町村の代表点（緯度経度）。scripts/build_municipality_geo.py で生成する。
MUNICIPALITY_GEO_FILE = "data/municipality_geo.csv"

# --- 都心・広域中心へのアクセス -------------------------------------------
# 「都心」は東京駅を指す。通勤の目的地としても、新幹線でつながる先としても
# ここを基準にすると全都県で意味が通る。
TOKYO_CENTER = ("東京駅", 35.681236, 139.767125)

# 対象8都県それぞれで、就業と商業がいちばん集まるターミナル。
# 岩手・宮城・山形に住む人にとっての「中心」は東京ではなく盛岡・仙台・山形なので、
# 東京駅までの距離とは別に、最寄りのこの中心までの距離も測る。
REGIONAL_HUBS = [
    ("東京駅", 35.681236, 139.767125),
    ("横浜駅", 35.465786, 139.622313),
    ("大宮駅", 35.906296, 139.623752),
    ("千葉駅", 35.613182, 140.113277),
    ("水戸駅", 36.370699, 140.476252),
    ("仙台駅", 38.260132, 140.882314),
    ("盛岡駅", 39.701279, 141.136506),
    ("山形駅", 38.240399, 140.330029),
]

# --- 世帯年収から予算を出すときの前提 --------------------------------------
# 画面で変えられる値の初期値と、変えられない前提（金利・返済年数）をここに集める。
# フロントエンドは /api/meta 経由でこの値を受け取るので、定義はここだけにある。
BUDGET_MODEL = {
    # 借入可能額の計算
    "interest_rate": 1.5,       # 年利（%）フラット35の目安
    "loan_years": 35,           # 返済年数
    "repayment_ratio": 25,      # 年収に対する年間返済額の割合（%）の初期値
    "repayment_ratio_options": [20, 25, 30],
    # 土地以外にかかる費用（万円）。建物本体・付帯工事・諸費用の合計の初期値。
    "building_budget": 2500,
    # 必要な土地面積（㎡）。0 は「その地域の取引面積の中央値を使う」の意味。
    "land_area": 0,
    "land_area_options": [0, 120, 150, 200],
    # 地域中央値を使うときの上下限。取引の少ない自治体で極端な値が出るのを防ぐ。
    "land_area_min": 100,
    "land_area_max": 300,
    # 予算に対してこの倍率まで余裕があれば「余裕を持って届く」＝満点にする。
    "comfortable_margin": 1.5,
    # これを下回ると手が届かないものとして0点にする。
    "reachable_floor": 0.6,
}

# --- 子どもの成長タイムライン ---------------------------------------------
# 「現在1歳未満の子ども」を起点に、住まい選びで効いてくる時期を定義する。
# 家を建てる判断は 0〜15年先の環境がどうなるかで決まるため、
# 各ステージが何年後に来るかをアプリ全体で共有する。
CHILD_BIRTH_YEAR = 2025

CHILD_STAGES = [
    # (キー, ラベル, 開始年齢, 終了年齢, 関連する人口指標)
    ("nursery", "保育園・こども園", 0, 5, "pop_0_5"),
    ("elementary", "小学校", 6, 11, "pop_6_11"),
    ("junior", "中学校", 12, 14, "pop_12_14"),
]


def stage_years(birth_year: int = CHILD_BIRTH_YEAR) -> list[dict]:
    """各ステージの西暦年レンジを返す。"""
    return [
        {
            "key": key,
            "label": label,
            "start_year": birth_year + start_age,
            "end_year": birth_year + end_age,
            "start_age": start_age,
            "end_age": end_age,
            "population_indicator": indicator,
        }
        for key, label, start_age, end_age, indicator in CHILD_STAGES
    ]


def current_year() -> int:
    return datetime.datetime.now().year
