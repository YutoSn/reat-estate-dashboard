"""
e-Stat「社会・人口統計体系（市区町村データ 基礎データ）」から取得する指標のカタログ。

各指標は (統計表ID, e-Statカテゴリコード) で一意に定まる。
統計表IDは分野ごとに 00000202NN（NN=分野の連番）で分かれている。

    01: A 人口・世帯   02: B 自然環境   03: C 経済基盤   04: D 行政基盤
    05: E 教育         07: G 文化       08: H 居住       09: I 健康・医療
    10: J 福祉         11: K 安全

過去に I5101 を「小学校数」として扱っていたが、実際には「病院数」であり
全面的に誤っていた。ここでは getMetaInfo で実データと突き合わせた上で定義している。

なお git履歴（d966b52 以前）には次のマッピングが残っている。**流用しないこと。**

    I5101 → elementary_schools   実際は 病院数
    I5102 → junior_high_schools  実際は 一般診療所数
    I6100 → libraries            実際は 医師数
    J4403 → pediatricians        未検証
    J2506 / I510110 / I5103      未検証

現行カタログと突き合わせられる3件はすべて誤っていた。同じ表にある
`J4403`（小児科医師数として画面に出していた）にも根拠は無い。
診療科別の指標を足すときは、必ず getMetaInfo で確認してから定義する。

    python scripts/list_estat_categories.py 0000020209 --grep 小児科
"""

from typing import NamedTuple

# 分野コード -> 統計表ID
DATASET_POPULATION = "0000020201"  # A 人口・世帯
DATASET_NATURE = "0000020202"      # B 自然環境
DATASET_ECONOMY = "0000020203"     # C 経済基盤
DATASET_ADMIN = "0000020204"       # D 行政基盤
DATASET_EDUCATION = "0000020205"   # E 教育
DATASET_CULTURE = "0000020207"     # G 文化・スポーツ
DATASET_HOUSING = "0000020208"     # H 居住
DATASET_HEALTH = "0000020209"      # I 健康・医療
DATASET_WELFARE = "0000020210"     # J 福祉・社会保障
DATASET_SAFETY = "0000020211"      # K 安全


class Indicator(NamedTuple):
    key: str          # DB上の指標キー
    dataset_id: str   # e-Stat 統計表ID
    code: str         # e-Stat cat01 コード
    label: str        # 日本語表示名
    unit: str         # 単位
    group: str        # UI上のグルーピング


INDICATORS: list[Indicator] = [
    # --- 人口構造 ---------------------------------------------------------
    Indicator("pop_total", DATASET_POPULATION, "A2301", "総人口（住民基本台帳）", "人", "population"),
    Indicator("pop_census", DATASET_POPULATION, "A1101", "総人口（国勢調査）", "人", "population"),
    Indicator("pop_0_14", DATASET_POPULATION, "A1301", "15歳未満人口", "人", "population"),
    Indicator("pop_15_64", DATASET_POPULATION, "A1302", "15〜64歳人口", "人", "population"),
    Indicator("pop_65over", DATASET_POPULATION, "A1303", "65歳以上人口", "人", "population"),
    Indicator("households", DATASET_POPULATION, "A7101", "世帯数", "世帯", "population"),

    # --- 子どもの年齢階級別人口（成長タイムラインの土台） -----------------
    Indicator("pop_0_3", DATASET_POPULATION, "A1404", "0〜3歳人口", "人", "children"),
    Indicator("pop_0_5", DATASET_POPULATION, "A1405", "0〜5歳人口", "人", "children"),
    Indicator("pop_6_11", DATASET_POPULATION, "A1409", "6〜11歳人口", "人", "children"),
    Indicator("pop_12_14", DATASET_POPULATION, "A1411", "12〜14歳人口", "人", "children"),
    Indicator("births", DATASET_POPULATION, "A4101", "出生数", "人", "children"),

    # --- 人口の流れ -------------------------------------------------------
    Indicator("in_migrants", DATASET_POPULATION, "A5103", "転入者数", "人", "migration"),
    Indicator("out_migrants", DATASET_POPULATION, "A5104", "転出者数", "人", "migration"),
    Indicator("day_night_ratio", DATASET_POPULATION, "A6108", "昼夜間人口比率", "%", "migration"),

    # --- 公式の将来推計人口（社人研） -------------------------------------
    Indicator("proj_pop_2025", DATASET_POPULATION, "A191002", "将来推計人口（2025年）", "人", "projection"),
    Indicator("proj_pop_2030", DATASET_POPULATION, "A191003", "将来推計人口（2030年）", "人", "projection"),
    Indicator("proj_pop_2035", DATASET_POPULATION, "A191004", "将来推計人口（2035年）", "人", "projection"),
    Indicator("proj_pop_2040", DATASET_POPULATION, "A191005", "将来推計人口（2040年）", "人", "projection"),
    Indicator("proj_pop_2045", DATASET_POPULATION, "A191006", "将来推計人口（2045年）", "人", "projection"),
    Indicator("proj_pop_2050", DATASET_POPULATION, "A191007", "将来推計人口（2050年）", "人", "projection"),

    # --- 面積（密度計算用） -----------------------------------------------
    Indicator("habitable_area", DATASET_NATURE, "B1103", "可住地面積", "ha", "geography"),

    # --- 自治体の財政体力と子育て投資 -------------------------------------
    Indicator("fiscal_index", DATASET_ADMIN, "D2201", "財政力指数", "-", "finance"),
    Indicator("child_welfare_exp", DATASET_ADMIN, "D3203033", "児童福祉費", "千円", "finance"),
    Indicator("elem_school_exp", DATASET_ADMIN, "D3203102", "小学校費", "千円", "finance"),
    Indicator("junior_school_exp", DATASET_ADMIN, "D3203103", "中学校費", "千円", "finance"),
    Indicator("kindergarten_exp", DATASET_ADMIN, "D3203106", "幼稚園費", "千円", "finance"),

    # --- 学校（※旧実装は I系＝医療のコードを誤用していた） ----------------
    Indicator("kindergartens", DATASET_EDUCATION, "E1101", "幼稚園数", "園", "education"),
    Indicator("elem_schools", DATASET_EDUCATION, "E2101", "小学校数", "校", "education"),
    Indicator("elem_teachers", DATASET_EDUCATION, "E2401", "小学校教員数", "人", "education"),
    Indicator("elem_pupils", DATASET_EDUCATION, "E2501", "小学校児童数", "人", "education"),
    Indicator("junior_schools", DATASET_EDUCATION, "E3101", "中学校数", "校", "education"),
    Indicator("junior_teachers", DATASET_EDUCATION, "E3401", "中学校教員数", "人", "education"),
    Indicator("junior_students", DATASET_EDUCATION, "E3501", "中学校生徒数", "人", "education"),
    Indicator("libraries", DATASET_CULTURE, "G1401", "図書館数", "館", "education"),

    # --- 住宅ストック（家を建てる／住み替えの土地勘） ---------------------
    Indicator("dwellings_occupied", DATASET_HOUSING, "H1101", "居住世帯あり住宅数", "戸", "housing"),
    Indicator("owned_homes", DATASET_HOUSING, "H1310", "持ち家数", "戸", "housing"),
    Indicator("detached_houses", DATASET_HOUSING, "H1401", "一戸建住宅数", "戸", "housing"),

    # --- 医療（乳幼児期にいちばん効く） -----------------------------------
    Indicator("hospitals", DATASET_HEALTH, "I5101", "病院数", "施設", "medical"),
    Indicator("clinics", DATASET_HEALTH, "I5102", "一般診療所数", "施設", "medical"),
    Indicator("doctors", DATASET_HEALTH, "I6100", "医師数", "人", "medical"),

    # --- 保育 -------------------------------------------------------------
    # 詳細票(J2503/J2506)は2017年で更新が止まっているため、2023年まである
    # 基本票(J250302/J250204)を採用する。
    Indicator("nurseries", DATASET_WELFARE, "J250302", "保育所等数", "所", "childcare"),
    Indicator("child_facilities", DATASET_WELFARE, "J250204", "児童福祉施設等数", "施設", "childcare"),

    # --- 安全（※更新停止中。参考値としてのみ表示しスコアには使わない） ----
    Indicator("traffic_accidents", DATASET_SAFETY, "K3101", "交通事故発生件数", "件", "safety"),
    Indicator("crimes", DATASET_SAFETY, "K4201", "刑法犯認知件数", "件", "safety"),
]

# e-Stat側で更新が止まっており、現在の状況を表さない指標。
# 画面には観測年を明示したうえで参考値として出し、スコアには含めない。
STALE_INDICATORS = {"crimes", "traffic_accidents"}


INDICATOR_BY_KEY = {ind.key: ind for ind in INDICATORS}

# 将来推計人口の指標キー -> 推計対象年
PROJECTION_YEARS = {
    "proj_pop_2025": 2025,
    "proj_pop_2030": 2030,
    "proj_pop_2035": 2035,
    "proj_pop_2040": 2040,
    "proj_pop_2045": 2045,
    "proj_pop_2050": 2050,
}
