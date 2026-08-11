"""派生指標を 0〜100 のスコアに正規化し、観点別に束ねる。

正規化には「対象自治体の中での順位（パーセンタイル）」を使う。
絶対値を線形に伸縮すると、外れ値ひとつでほぼ全自治体が同じ点数に潰れるため。
スコアは常に「この8都県の中で相対的にどの位置か」を意味する。
"""

from typing import Any, NamedTuple

import pandas as pd

from config import BALANCE_MODEL
from src.indicators import INDICATOR_BY_KEY


class MetricSpec(NamedTuple):
    key: str               # derive_metrics が返すキー
    label: str             # 表示名
    higher_is_better: bool # 大きいほど良いか
    dimension: str         # 属する観点
    description: str       # UIの説明文
    unit: str = ""         # 派生指標そのものの単位
    formula: str = ""      # 計算式（画面にそのまま出す）
    inputs: tuple[str, ...] = ()  # 計算に使う e-Stat 指標のキー

    @property
    def digits(self) -> int:
        """画面に出すときの小数桁。単位ごとに素直な桁数を選ぶ。"""
        if self.unit in {"人", "円", "円/㎡", "人/km²"}:
            return 0
        if self.unit == "-":
            return 2
        return 1


METRIC_SPECS: list[MetricSpec] = [
    # --- 子育て・教育環境 -------------------------------------------------
    MetricSpec(
        "nurseries_per_1k_children", "保育所の密度", True, "childcare",
        "未就学児1000人あたりの保育所等の数。多いほど預け先を確保しやすい。",
        unit="か所/千人",
        formula="保育所等数 ÷ 0〜5歳人口 × 1000",
        inputs=("nurseries", "pop_0_5"),
    ),
    MetricSpec(
        "pupils_per_teacher", "小学校の手厚さ", False, "childcare",
        "小学校教員1人あたりの児童数。少ないほど一人ひとりに目が届きやすい。",
        unit="人",
        formula="小学校児童数 ÷ 小学校教員数",
        inputs=("elem_pupils", "elem_teachers"),
    ),
    MetricSpec(
        "child_welfare_per_child", "子ども1人あたり児童福祉費", True, "childcare",
        "自治体が子ども1人にいくら使っているか。子育て支援の厚みの目安。",
        unit="円",
        formula="児童福祉費（千円）× 1000 ÷ 15歳未満人口",
        inputs=("child_welfare_exp", "pop_0_14"),
    ),
    MetricSpec(
        "child_facilities_per_1k_children", "児童福祉施設の密度", True, "childcare",
        "子ども1000人あたりの児童館・児童福祉施設等の数。",
        unit="施設/千人",
        formula="児童福祉施設等数 ÷ 15歳未満人口 × 1000",
        inputs=("child_facilities", "pop_0_14"),
    ),

    # --- 医療アクセス -----------------------------------------------------
    MetricSpec(
        "doctors_per_10k", "医師の密度", True, "medical",
        "人口1万人あたりの医師数。乳幼児期は受診頻度が高く効いてくる。",
        unit="人/万人",
        formula="医師数 ÷ 総人口 × 10000",
        inputs=("doctors", "pop_total"),
    ),
    MetricSpec(
        "clinics_per_10k", "診療所の密度", True, "medical",
        "人口1万人あたりの一般診療所数。日常的なかかりつけ医の探しやすさ。",
        unit="施設/万人",
        formula="一般診療所数 ÷ 総人口 × 10000",
        inputs=("clinics", "pop_total"),
    ),
    MetricSpec(
        "hospitals_per_10k", "病院の密度", True, "medical",
        "人口1万人あたりの病院数。入院や救急の受け皿。",
        unit="施設/万人",
        formula="病院数 ÷ 総人口 × 10000",
        inputs=("hospitals", "pop_total"),
    ),

    # --- 住環境のゆとり ---------------------------------------------------
    MetricSpec(
        "detached_ratio", "戸建て中心の街か", True, "living",
        "住宅に占める一戸建の割合。家を建てて暮らす街並みかどうかの目安。",
        unit="%",
        formula="一戸建住宅数 ÷ 居住世帯あり住宅数 × 100",
        inputs=("detached_houses", "dwellings_occupied"),
    ),
    MetricSpec(
        "libraries_per_10k", "図書館の密度", True, "living",
        "人口1万人あたりの図書館数。",
        unit="館/万人",
        formula="図書館数 ÷ 総人口 × 10000",
        inputs=("libraries", "pop_total"),
    ),

    # --- 利便性（都心・中心都市へのアクセス） -----------------------------
    MetricSpec(
        "tokyo_distance_km", "東京都心への近さ", False, "convenience",
        "東京駅までの直線距離。通勤先としても、新幹線でつながる先としても基準になる。"
        "路線網は反映していないので、目安として見る。",
        unit="km",
        formula="市区町村の代表点から東京駅までの大圏距離",
    ),
    MetricSpec(
        "hub_distance_km", "広域中心都市への近さ", False, "convenience",
        "最寄りの主要ターミナル（東京・横浜・大宮・千葉・水戸・仙台・盛岡・山形）"
        "までの直線距離。日常の通勤・買い物が向かう先への近さ。",
        unit="km",
        formula="代表点から8つの主要ターミナルまでの大圏距離のうち最小のもの",
    ),
    MetricSpec(
        "pop_density_habitable", "生活利便施設の集積", True, "convenience",
        "可住地1km²あたりの人口。高いほど店・駅・病院が徒歩圏にそろいやすい。",
        unit="人/km²",
        formula="総人口 ÷（可住地面積(ha) ÷ 100）",
        inputs=("pop_total", "habitable_area"),
    ),

    # --- 将来の見通し -----------------------------------------------------
    MetricSpec(
        "proj_pop_change_2050", "2050年までの人口見通し", True, "future",
        "社人研の将来推計人口による2025年→2050年の変化率。",
        unit="%",
        formula="（将来推計人口2050 − 将来推計人口2025）÷ 将来推計人口2025 × 100",
        inputs=("proj_pop_2025", "proj_pop_2050"),
    ),
    MetricSpec(
        "young_pop_change_10y", "年少人口の伸び", True, "future",
        "15歳未満人口の直近10年の変化率。子育て世帯に選ばれているか。",
        unit="%",
        formula="（最新の15歳未満人口 − 10年前の15歳未満人口）÷ 10年前 × 100",
        # 両端の年と値は時系列から取るので、derive_metrics 側の extra_inputs で渡す
    ),
    MetricSpec(
        "net_migration_rate", "社会増減", True, "future",
        "人口1000人あたりの転入超過数。街の勢いを映す。",
        unit="人/千人",
        formula="（転入者数 − 転出者数）÷ 総人口 × 1000",
        inputs=("in_migrants", "out_migrants", "pop_total"),
    ),
    MetricSpec(
        "fiscal_index", "自治体の財政力", True, "future",
        "財政力指数。高いほど独自の子育て支援を続ける体力がある。",
        unit="-",
        formula="財政力指数をそのまま使う",
        inputs=("fiscal_index",),
    ),

    # --- 手が届きやすさ ---------------------------------------------------
    MetricSpec(
        "land_unit_price", "土地の買いやすさ", False, "affordability",
        "住宅地の実取引㎡単価（中央値）。安いほど同じ予算で広い土地を買える。",
        unit="円/㎡",
        formula="直近3年の「宅地(土地)×住宅地」の取引㎡単価の中央値"
                "（面積がマスクされた取引と、取引10件未満の自治体は除く）",
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
    scores: pd.DataFrame,
    weights: dict[str, float] | None = None,
    floor: float | None = None,
    penalty_per_point: float | None = None,
) -> pd.Series:
    """観点別スコアを重み付けして総合点にする。

    重みはUIから変更できる。何を重視するかは家庭ごとに違うため、
    単一の「正解の総合点」を押し付けない設計にしている。

    加重平均のあとに **弱点補正** を掛ける。平均だけで並べると、5観点が80点でも
    1観点が20点の街が、全観点60点台の街より上に来てしまう。家を建てて15年住む
    場所としては、突出した強みより決定的に困る点が無いことの方が効くため、
    最も低い観点が基準点を下回っているぶんだけ総合点から差し引く。

    差し引く量を「下回った点数 × 係数」にしているのは、基準点をまたいだ瞬間に
    順位が飛ぶのを避けるため。49点と51点の街の扱いが連続的になる。
    """
    active = weights or {k: v["default_weight"] for k, v in DIMENSIONS.items()}
    if floor is None:
        floor = BALANCE_MODEL["floor"]
    if penalty_per_point is None:
        penalty_per_point = BALANCE_MODEL["penalty_per_point"]

    total = pd.Series(0.0, index=scores.index)
    weight_sum = pd.Series(0.0, index=scores.index)
    # 重みを掛けている観点だけを弱点判定の対象にする。
    # 重み0はその観点を見ないという意思表示なので、低くても減点しない。
    weighted_columns = []

    for dimension, weight in active.items():
        column = f"dim_{dimension}"
        if column not in scores.columns or weight <= 0:
            continue
        weighted_columns.append(column)
        values = scores[column]
        mask = values.notna()
        total[mask] += values[mask] * weight
        weight_sum[mask] += weight

    result = total / weight_sum.replace(0, pd.NA)

    if floor and penalty_per_point and weighted_columns:
        weakest = scores[weighted_columns].min(axis=1, skipna=True)
        shortfall = (floor - weakest).clip(lower=0).fillna(0)
        result = (result - shortfall * penalty_per_point).clip(lower=0)

    return result.round(1)


def weakest_dimension(
    scores: dict[str, Any], weights: dict[str, float] | None = None
) -> tuple[str, float] | None:
    """重みを掛けている観点のうち、最も点数の低いものを返す。"""
    active = weights or {k: v["default_weight"] for k, v in DIMENSIONS.items()}
    candidates = [
        (dimension, scores[f"dim_{dimension}"])
        for dimension, weight in active.items()
        if weight > 0 and scores.get(f"dim_{dimension}") is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[1])


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
    """フロントエンドに渡す指標カタログ。計算式と入力もそのまま出す。"""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "dimension": spec.dimension,
            "higher_is_better": spec.higher_is_better,
            "description": spec.description,
            "unit": spec.unit,
            "digits": spec.digits,
            "formula": spec.formula,
            "inputs": [
                {
                    "key": key,
                    "label": INDICATOR_BY_KEY[key].label if key in INDICATOR_BY_KEY else key,
                    "unit": INDICATOR_BY_KEY[key].unit if key in INDICATOR_BY_KEY else "",
                }
                for key in spec.inputs
            ],
        }
        for spec in METRIC_SPECS
    ]


def metric_ranks(scores_long: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """指標ごとの順位表を作る。1位が最も良い側。

    スコア（パーセンタイル）だけでは「402市区町村中の何位か」が分からない。
    「住環境が低いのはなぜか」を追うには、どの指標で何位なのかが要る。
    """
    ranks: dict[str, dict[str, Any]] = {}
    if scores_long.empty:
        return ranks

    for spec in METRIC_SPECS:
        subset = scores_long[scores_long["metric"] == f"raw_{spec.key}"]
        if subset.empty:
            continue
        series = pd.to_numeric(
            subset.set_index("municipality_code")["value"], errors="coerce"
        ).dropna()
        if series.empty:
            continue
        # 同じ値なら同順位。良い側が1位になるよう向きを合わせる。
        ordered = series.rank(ascending=not spec.higher_is_better, method="min")
        ranks[spec.key] = {
            "rank": {code: int(value) for code, value in ordered.items()},
            "total": int(series.size),
        }
    return ranks


def score_breakdown(
    metrics: dict[str, Any],
    scores: dict[str, Any],
    input_values: dict[str, tuple[float | None, int | None]],
    ranks: dict[str, dict[str, Any]],
    city_code: str,
    extra_inputs: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """観点ごとに「その点数がどう出たか」を組み立てる。

    観点の点数は構成指標のスコアの平均でしかない。低い観点を見たときに
    どの指標が足を引っ張っているのか、その指標はどの統計値から出たのかまで
    たどれるようにするのがここの目的。
    """
    extra_inputs = extra_inputs or {}

    result = []
    for dimension, meta in DIMENSIONS.items():
        rows = []
        for spec in METRIC_SPECS:
            if spec.dimension != dimension:
                continue
            entry = ranks.get(spec.key, {})
            rows.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "description": spec.description,
                    "unit": spec.unit,
                    "digits": spec.digits,
                    "formula": spec.formula,
                    "higher_is_better": spec.higher_is_better,
                    "value": metrics.get(spec.key),
                    "score": scores.get(f"score_{spec.key}"),
                    "rank": entry.get("rank", {}).get(city_code),
                    "total": entry.get("total"),
                    "inputs": [
                        {
                            "key": key,
                            "label": (
                                INDICATOR_BY_KEY[key].label
                                if key in INDICATOR_BY_KEY else key
                            ),
                            "unit": (
                                INDICATOR_BY_KEY[key].unit
                                if key in INDICATOR_BY_KEY else ""
                            ),
                            "value": input_values.get(key, (None, None))[0],
                            "year": input_values.get(key, (None, None))[1],
                        }
                        for key in spec.inputs
                    ] + extra_inputs.get(spec.key, []),
                }
            )

        result.append(
            {
                "dimension": dimension,
                "label": meta["label"],
                "short_label": meta["short_label"],
                "description": meta["description"],
                "score": scores.get(f"dim_{dimension}"),
                "metrics": rows,
            }
        )
    return result
