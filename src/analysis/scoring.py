"""派生指標を 0〜100 のスコアに正規化し、観点別に束ねる。

正規化には「対象自治体の中での順位（パーセンタイル）」を使う。
絶対値を線形に伸縮すると、外れ値ひとつでほぼ全自治体が同じ点数に潰れるため。
スコアは常に「この8都県の中で相対的にどの位置か」を意味する。
"""

from typing import Any, NamedTuple

import pandas as pd


class MetricSpec(NamedTuple):
    key: str               # derive_metrics が返すキー
    label: str             # 表示名
    higher_is_better: bool # 大きいほど良いか
    dimension: str         # 属する観点
    description: str       # UIの説明文


METRIC_SPECS: list[MetricSpec] = [
    # --- 子育て・教育環境 -------------------------------------------------
    MetricSpec(
        "nurseries_per_1k_children", "保育所の密度", True, "childcare",
        "未就学児1000人あたりの保育所等の数。多いほど預け先を確保しやすい。",
    ),
    MetricSpec(
        "pupils_per_teacher", "小学校の手厚さ", False, "childcare",
        "小学校教員1人あたりの児童数。少ないほど一人ひとりに目が届きやすい。",
    ),
    MetricSpec(
        "child_welfare_per_child", "子ども1人あたり児童福祉費", True, "childcare",
        "自治体が子ども1人にいくら使っているか。子育て支援の厚みの目安。",
    ),
    MetricSpec(
        "child_facilities_per_1k_children", "児童福祉施設の密度", True, "childcare",
        "子ども1000人あたりの児童館・児童福祉施設等の数。",
    ),

    # --- 医療アクセス -----------------------------------------------------
    MetricSpec(
        "doctors_per_10k", "医師の密度", True, "medical",
        "人口1万人あたりの医師数。乳幼児期は受診頻度が高く効いてくる。",
    ),
    MetricSpec(
        "clinics_per_10k", "診療所の密度", True, "medical",
        "人口1万人あたりの一般診療所数。日常的なかかりつけ医の探しやすさ。",
    ),
    MetricSpec(
        "hospitals_per_10k", "病院の密度", True, "medical",
        "人口1万人あたりの病院数。入院や救急の受け皿。",
    ),

    # --- 住環境のゆとり ---------------------------------------------------
    MetricSpec(
        "detached_ratio", "戸建て中心の街か", True, "living",
        "住宅に占める一戸建の割合。家を建てて暮らす街並みかどうかの目安。",
    ),
    MetricSpec(
        "libraries_per_10k", "図書館の密度", True, "living",
        "人口1万人あたりの図書館数。",
    ),

    # --- 利便性（都心・中心都市へのアクセス） -----------------------------
    MetricSpec(
        "tokyo_distance_km", "東京都心への近さ", False, "convenience",
        "東京駅までの直線距離。通勤先としても、新幹線でつながる先としても基準になる。"
        "路線網は反映していないので、目安として見る。",
    ),
    MetricSpec(
        "hub_distance_km", "広域中心都市への近さ", False, "convenience",
        "最寄りの主要ターミナル（東京・横浜・大宮・千葉・水戸・仙台・盛岡・山形）"
        "までの直線距離。日常の通勤・買い物が向かう先への近さ。",
    ),
    MetricSpec(
        "pop_density_habitable", "生活利便施設の集積", True, "convenience",
        "可住地1km²あたりの人口。高いほど店・駅・病院が徒歩圏にそろいやすい。",
    ),

    # --- 将来の見通し -----------------------------------------------------
    MetricSpec(
        "proj_pop_change_2050", "2050年までの人口見通し", True, "future",
        "社人研の将来推計人口による2025年→2050年の変化率。",
    ),
    MetricSpec(
        "young_pop_change_10y", "年少人口の伸び", True, "future",
        "15歳未満人口の直近10年の変化率。子育て世帯に選ばれているか。",
    ),
    MetricSpec(
        "net_migration_rate", "社会増減", True, "future",
        "人口1000人あたりの転入超過数。街の勢いを映す。",
    ),
    MetricSpec(
        "fiscal_index", "自治体の財政力", True, "future",
        "財政力指数。高いほど独自の子育て支援を続ける体力がある。",
    ),

    # --- 手が届きやすさ ---------------------------------------------------
    MetricSpec(
        "land_unit_price", "土地の買いやすさ", False, "affordability",
        "住宅地の実取引㎡単価（中央値）。安いほど同じ予算で広い土地を買える。",
    ),
]


DIMENSIONS: dict[str, dict[str, Any]] = {
    "childcare": {
        "short_label": "子育て",
        "label": "子育て・教育",
        "description": "保育の入りやすさ、学校の手厚さ、自治体の子育て投資。",
        "default_weight": 0.25,
    },
    "convenience": {
        "short_label": "利便性",
        "label": "利便性",
        "description": "都心・中心都市への近さと、生活利便施設の集まりやすさ。",
        "default_weight": 0.15,
    },
    "medical": {
        "short_label": "医療",
        "label": "医療アクセス",
        "description": "医師・診療所・病院の密度。乳幼児期に最も効く。",
        "default_weight": 0.15,
    },
    "living": {
        "short_label": "住環境",
        "label": "住環境",
        "description": "戸建て中心の街並みか、文化施設が身近か。",
        "default_weight": 0.10,
    },
    "future": {
        "short_label": "将来性",
        "label": "将来の見通し",
        "description": "人口推計、年少人口の動き、自治体の財政体力。",
        "default_weight": 0.20,
    },
    "affordability": {
        "short_label": "価格",
        "label": "手が届きやすさ",
        "description": "住宅地の実取引価格。安いほど高スコア。"
        "世帯年収を入れると、その予算で届くかどうかの評価に切り替わる。",
        "default_weight": 0.15,
    },
}

# 順位付けに足る母数がないときはスコアを出さない
MIN_SAMPLES = 20


def score_table(metric_df: pd.DataFrame) -> pd.DataFrame:
    """派生指標テーブルを 0〜100 のスコアテーブルに変換する。"""
    if metric_df.empty:
        return pd.DataFrame()

    scores = pd.DataFrame(index=metric_df.index)

    for spec in METRIC_SPECS:
        if spec.key not in metric_df.columns:
            continue
        series = pd.to_numeric(metric_df[spec.key], errors="coerce")
        if series.notna().sum() < MIN_SAMPLES:
            continue
        # 小→大 のパーセンタイル。低いほど良い指標は昇順を反転させる
        ranked = series.rank(pct=True, ascending=spec.higher_is_better)
        scores[f"score_{spec.key}"] = (ranked * 100).round(1)

    # 観点ごとに、取得できた指標の平均を取る
    for dimension in DIMENSIONS:
        columns = [
            f"score_{spec.key}"
            for spec in METRIC_SPECS
            if spec.dimension == dimension and f"score_{spec.key}" in scores.columns
        ]
        if columns:
            scores[f"dim_{dimension}"] = scores[columns].mean(axis=1, skipna=True).round(1)

    return scores


def composite_score(
    scores: pd.DataFrame, weights: dict[str, float] | None = None
) -> pd.Series:
    """観点別スコアを重み付けして総合点にする。

    重みはUIから変更できる。何を重視するかは家庭ごとに違うため、
    単一の「正解の総合点」を押し付けない設計にしている。
    """
    active = weights or {k: v["default_weight"] for k, v in DIMENSIONS.items()}

    total = pd.Series(0.0, index=scores.index)
    weight_sum = pd.Series(0.0, index=scores.index)

    for dimension, weight in active.items():
        column = f"dim_{dimension}"
        if column not in scores.columns or weight <= 0:
            continue
        values = scores[column]
        mask = values.notna()
        total[mask] += values[mask] * weight
        weight_sum[mask] += weight

    result = (total / weight_sum.replace(0, pd.NA)).round(1)
    return result


def scores_to_long(scores: pd.DataFrame) -> pd.DataFrame:
    """スコアテーブルを (municipality_code, metric, value) の long 形式にする。"""
    if scores.empty:
        return pd.DataFrame(columns=["municipality_code", "metric", "value"])
    long_df = (
        scores.reset_index()
        .melt(id_vars="municipality_code", var_name="metric", value_name="value")
        .dropna(subset=["value"])
    )
    return long_df


def metric_catalog() -> list[dict[str, Any]]:
    """フロントエンドに渡す指標カタログ。"""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "dimension": spec.dimension,
            "higher_is_better": spec.higher_is_better,
            "description": spec.description,
        }
        for spec in METRIC_SPECS
    ]
