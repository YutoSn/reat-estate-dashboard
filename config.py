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
