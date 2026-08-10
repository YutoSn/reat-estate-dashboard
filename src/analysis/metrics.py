"""生の統計値から、住まい選びの判断に使える派生指標を組み立てる。

素の「保育所数」「医師数」は自治体の人口規模に引きずられるため、そのままでは
比較に使えない。ここでは必ず人口や対象年齢の子ども数で割って密度に直す。
"""

from typing import Any

import pandas as pd

from src.analysis.geo import access_distances

# 指標ごとの「使える鮮度」の上限（年）。これより古い値しかなければ欠測扱い。
DEFAULT_MAX_AGE = 12

# 単価の中央値を信頼するのに必要な最低取引件数。
# 千代田区のように住宅地の純粋な土地取引がほぼ無い自治体では、
# 数件の中央値が実勢と大きくずれるため。
MIN_PRICE_DEALS = 10


def latest_value(
    stats: pd.DataFrame,
    indicator: str,
    max_age: int = DEFAULT_MAX_AGE,
    reference_year: int | None = None,
) -> tuple[float | None, int | None]:
    """指標の最新の有効値と、その観測年を返す。

    統計ごとに更新頻度が違う（国勢調査は5年、住民基本台帳は毎年）ため、
    「いつ時点の値か」を必ず一緒に持ち回る。
    """
    if stats.empty or indicator not in stats.columns:
        return None, None

    series = stats[indicator].dropna()
    if series.empty:
        return None, None

    latest_year = int(series.index.max())
    if reference_year is not None and latest_year < reference_year - max_age:
        return None, None
    return float(series.loc[series.index.max()]), latest_year


def _safe_ratio(
    numerator: float | None, denominator: float | None, scale: float = 1.0
) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * scale


def change_rate_detail(
    stats: pd.DataFrame, indicator: str, span_years: int = 10
) -> dict[str, Any] | None:
    """変化率と、それを出すのに使った2時点（年と値）。

    変化率だけを見せても「いつと比べた何%か」が分からないため、
    比較の両端を一緒に返して画面に出せるようにしている。
    """
    if stats.empty or indicator not in stats.columns:
        return None
    series = stats[indicator].dropna()
    if len(series) < 2:
        return None

    latest_year = int(series.index.max())
    target_year = latest_year - span_years
    # 目標年ちょうどが無ければ、それ以前で最も近い年を使う
    earlier = series[series.index <= target_year]
    if earlier.empty:
        earlier = series[series.index < latest_year]
        if earlier.empty:
            return None
    base = float(earlier.iloc[-1])
    latest = float(series.loc[series.index.max()])
    if base == 0:
        return None
    return {
        "rate": (latest - base) / base * 100.0,
        "base_year": int(earlier.index[-1]),
        "base_value": base,
        "latest_year": latest_year,
        "latest_value": latest,
    }


def change_rate(
    stats: pd.DataFrame, indicator: str, span_years: int = 10
) -> float | None:
    """指標の直近 span_years 年での変化率（%）。"""
    detail = change_rate_detail(stats, indicator, span_years)
    return detail["rate"] if detail else None


def derive_metrics(
    stats: pd.DataFrame,
    land_unit_price: float | None = None,
    land_price_change: float | None = None,
    land_area_median: float | None = None,
    land_deals: float | None = None,
    access: dict[str, Any] | None = None,
    reference_year: int | None = None,
) -> dict[str, Any]:
    """1市区町村分の派生指標をまとめて計算する。"""

    def val(indicator: str) -> float | None:
        return latest_value(stats, indicator, reference_year=reference_year)[0]

    def year_of(indicator: str) -> int | None:
        return latest_value(stats, indicator, reference_year=reference_year)[1]

    pop_total = val("pop_total") or val("pop_census")
    pop_0_5 = val("pop_0_5")
    pop_0_14 = val("pop_0_14")
    pop_65over = val("pop_65over")

    metrics: dict[str, Any] = {}

    # --- 規模と構成 -------------------------------------------------------
    metrics["pop_total"] = pop_total
    metrics["pop_0_14"] = pop_0_14
    metrics["young_ratio"] = _safe_ratio(pop_0_14, pop_total, 100)
    metrics["aging_ratio"] = _safe_ratio(pop_65over, pop_total, 100)

    # --- 保育・教育の手厚さ ----------------------------------------------
    # 保育所は「未就学児1000人あたり何か所か」で見る
    metrics["nurseries_per_1k_children"] = _safe_ratio(val("nurseries"), pop_0_5, 1000)
    metrics["kindergartens_per_1k_children"] = _safe_ratio(
        val("kindergartens"), pop_0_5, 1000
    )
    metrics["child_facilities_per_1k_children"] = _safe_ratio(
        val("child_facilities"), pop_0_14, 1000
    )
    # 教員1人あたり児童数は少ないほど手厚い
    metrics["pupils_per_teacher"] = _safe_ratio(val("elem_pupils"), val("elem_teachers"))
    metrics["students_per_teacher"] = _safe_ratio(
        val("junior_students"), val("junior_teachers")
    )
    # 1校あたり児童数（統廃合リスクの目安。極端に少ないと将来の統合対象）
    metrics["pupils_per_school"] = _safe_ratio(val("elem_pupils"), val("elem_schools"))
    metrics["elem_schools"] = val("elem_schools")
    metrics["junior_schools"] = val("junior_schools")
    metrics["libraries_per_10k"] = _safe_ratio(val("libraries"), pop_total, 10000)

    # --- 自治体が子どもにいくら使っているか ------------------------------
    # 児童福祉費は千円単位。子ども1人あたりの円に直す
    child_welfare = val("child_welfare_exp")
    metrics["child_welfare_per_child"] = (
        _safe_ratio(child_welfare * 1000 if child_welfare is not None else None, pop_0_14)
    )
    metrics["fiscal_index"] = val("fiscal_index")

    # --- 医療アクセス -----------------------------------------------------
    metrics["doctors_per_10k"] = _safe_ratio(val("doctors"), pop_total, 10000)
    metrics["clinics_per_10k"] = _safe_ratio(val("clinics"), pop_total, 10000)
    metrics["hospitals_per_10k"] = _safe_ratio(val("hospitals"), pop_total, 10000)

    # --- 安全 -------------------------------------------------------------
    metrics["crimes_per_10k"] = _safe_ratio(val("crimes"), pop_total, 10000)
    metrics["accidents_per_10k"] = _safe_ratio(val("traffic_accidents"), pop_total, 10000)

    # --- 人口の流れと将来 -------------------------------------------------
    in_mig = val("in_migrants")
    out_mig = val("out_migrants")
    if in_mig is not None and out_mig is not None and pop_total:
        metrics["net_migration_rate"] = (in_mig - out_mig) / pop_total * 1000
    else:
        metrics["net_migration_rate"] = None

    metrics["birth_rate"] = _safe_ratio(val("births"), pop_total, 1000)
    young_change = change_rate_detail(stats, "pop_0_14", 10)
    metrics["young_pop_change_10y"] = young_change["rate"] if young_change else None
    metrics["pop_change_10y"] = change_rate(stats, "pop_total", 10)
    metrics["day_night_ratio"] = val("day_night_ratio")

    # 社人研の将来推計人口による 2025→2050 の変化率
    proj_2025 = val("proj_pop_2025")
    proj_2050 = val("proj_pop_2050")
    metrics["proj_pop_change_2050"] = (
        (proj_2050 - proj_2025) / proj_2025 * 100
        if proj_2025 and proj_2050 and proj_2025 != 0
        else None
    )

    # --- 利便性 -----------------------------------------------------------
    # 都心・広域中心までの距離は直線距離（src/analysis/geo.py 参照）。
    access = access or {}
    metrics["tokyo_distance_km"] = access.get("tokyo_distance_km")
    metrics["hub_distance_km"] = access.get("hub_distance_km")
    metrics["hub_name"] = access.get("hub_name")

    # 可住地人口密度。総面積で割ると山林の広い市が不当に低く出るため、
    # 実際に人が住める土地（可住地）で割る。単位は 人/km²（可住地面積はha）。
    habitable_ha = val("habitable_area")
    metrics["pop_density_habitable"] = _safe_ratio(
        pop_total, habitable_ha / 100 if habitable_ha else None
    )

    # --- 住宅・価格 -------------------------------------------------------
    metrics["land_unit_price"] = land_unit_price
    metrics["land_price_change_10y"] = land_price_change
    metrics["land_area_median"] = land_area_median
    metrics["detached_ratio"] = _safe_ratio(
        val("detached_houses"), val("dwellings_occupied"), 100
    )
    metrics["ownership_ratio"] = _safe_ratio(
        val("owned_homes"), val("dwellings_occupied"), 100
    )

    # --- 統計表から直接は取れない入力値 -----------------------------------
    # 指標カタログの inputs は e-Stat の統計指標しか指せない。時系列の両端や
    # 取引データ由来の値はここで組み立てて、画面の内訳に並べられるようにする。
    extra_inputs: dict[str, list[dict[str, Any]]] = {}
    if young_change:
        extra_inputs["young_pop_change_10y"] = [
            {
                "label": "15歳未満人口（最新）",
                "value": young_change["latest_value"],
                "unit": "人",
                "year": young_change["latest_year"],
            },
            {
                "label": "15歳未満人口（比較時点）",
                "value": young_change["base_value"],
                "unit": "人",
                "year": young_change["base_year"],
            },
        ]
    if land_unit_price is not None:
        # 中央値そのものは指標の値なので繰り返さない。何件から取った中央値かを添える。
        entries = []
        if land_deals is not None:
            entries.append(
                {"label": "中央値の元になった取引件数", "value": land_deals,
                 "unit": "件", "year": None}
            )
        if land_area_median is not None:
            entries.append(
                {"label": "取引された土地の広さ（中央値）", "value": land_area_median,
                 "unit": "㎡", "year": None}
            )
        if entries:
            extra_inputs["land_unit_price"] = entries
    metrics["_extra_inputs"] = extra_inputs

    # --- 各値の観測年（透明性のため一緒に返す） --------------------------
    metrics["_years"] = {
        key: year_of(key)
        for key in [
            "pop_total", "pop_0_5", "pop_0_14", "nurseries", "child_facilities",
            "elem_pupils", "elem_teachers", "doctors", "clinics", "fiscal_index",
            "child_welfare_exp", "dwellings_occupied", "crimes", "habitable_area",
        ]
    }

    return metrics


def build_metric_table(
    all_stats: pd.DataFrame,
    price_latest: pd.DataFrame,
    price_history: pd.DataFrame,
    city_codes: list[str],
    land_area: pd.DataFrame | None = None,
    reference_year: int | None = None,
) -> pd.DataFrame:
    """全市区町村分の派生指標テーブルを作る。"""
    # 取引が数件しかない自治体の中央値は実勢を表さないため、下限を設ける
    if price_latest.empty:
        price_map: dict[str, float] = {}
    else:
        reliable = price_latest[price_latest["deals"] >= MIN_PRICE_DEALS]
        price_map = reliable.set_index("municipality_code")["land_unit_price"].to_dict()
    change_map = _land_price_change_map(price_history)

    if land_area is None or land_area.empty:
        area_map: dict[str, float] = {}
    else:
        reliable_area = land_area[land_area["deals"] >= MIN_PRICE_DEALS]
        area_map = (
            reliable_area.set_index("municipality_code")["land_area_median"].to_dict()
        )

    distances = access_distances()

    rows = []
    grouped = (
        all_stats.groupby("municipality_code") if not all_stats.empty else []
    )
    stats_by_city = {code: group for code, group in grouped}

    for code in city_codes:
        group = stats_by_city.get(code)
        if group is None or group.empty:
            wide = pd.DataFrame()
        else:
            wide = group.pivot_table(
                index="year", columns="indicator", values="value", aggfunc="first"
            ).sort_index()

        metrics = derive_metrics(
            wide,
            land_unit_price=price_map.get(code),
            land_price_change=change_map.get(code),
            land_area_median=area_map.get(code),
            access=distances.get(code),
            reference_year=reference_year,
        )
        metrics.pop("_years", None)
        metrics.pop("_extra_inputs", None)
        # hub_name は文字列なのでスコア計算に載せない（実数テーブルは数値だけ）
        metrics.pop("hub_name", None)
        metrics["municipality_code"] = code
        rows.append(metrics)

    return pd.DataFrame(rows).set_index("municipality_code")


def _land_price_change_map(price_history: pd.DataFrame) -> dict[str, float]:
    """市区町村ごとの住宅地単価の10年変化率（%）。

    取引件数が少ない年は中央値が跳ねるため、前後3年の移動平均で均してから比較する。
    """
    if price_history.empty:
        return {}

    result: dict[str, float] = {}
    for code, group in price_history.groupby("municipality_code"):
        series = (
            group.set_index("year")["land_unit_price"].sort_index().dropna()
        )
        if len(series) < 4:
            continue
        smoothed = series.rolling(window=3, min_periods=1, center=True).mean()
        latest_year = int(smoothed.index.max())
        base_candidates = smoothed[smoothed.index <= latest_year - 10]
        if base_candidates.empty:
            base_candidates = smoothed[smoothed.index < latest_year]
        if base_candidates.empty:
            continue
        base = float(base_candidates.iloc[-1])
        latest = float(smoothed.loc[smoothed.index.max()])
        if base > 0:
            result[code] = (latest - base) / base * 100.0
    return result


def project_child_population(
    stats: pd.DataFrame, birth_year: int
) -> list[dict[str, Any]]:
    """子どもの学齢期に、その地域の同年代が何人いそうかを推計する。

    手法（出生コホート法）
    ----------------------
    ある年の6〜11歳は、その6〜11年前に生まれた子どもたちである。
    そこで年次で取れる出生数を土台にし、国勢調査の実績から
        定着率 = 実際の6〜11歳人口 / その学年が生まれた6年間の出生数合計
    を求めて掛ける。定着率が1を超える地域は、生まれた数以上に
    子育て世帯が転入してきている地域を意味する。

    国勢調査の年齢別人口は5年間隔・2020年が最新だが、出生数は2023年まで
    年次で取れる。学齢期の推計にはこちらの方が実態に近い。
    """
    if stats.empty or "births" not in stats.columns:
        return []

    births = stats["births"].dropna()
    if births.empty:
        return []
    births.index = births.index.astype(int)

    last_birth_year = int(births.index.max())
    # 直近3年の平均で、未取得年の出生数を補う
    recent_mean = float(births.loc[births.index >= last_birth_year - 2].mean())

    def births_in(start: int, end: int) -> tuple[float, bool]:
        """[start, end] 年に生まれた数の合計と、推定を含むかどうか。"""
        total = 0.0
        estimated = False
        for year in range(start, end + 1):
            if year in births.index:
                total += float(births.loc[year])
            else:
                total += recent_mean
                estimated = True
        return total, estimated

    def settle_rate(
        pop_column: str, span: int, offset: int
    ) -> tuple[float, int] | None:
        """国勢調査の実績から定着率と、その根拠になった調査年を求める。

        offset は「調査年から何年前に生まれた学年か」の起点。
        例: 6〜11歳なら offset=11, span=6 → 調査年-11 〜 調査年-6 生まれ。

        過去の調査年を平均すると、2015年国勢調査のように不詳が多く値が沈む年に
        引きずられる（市川市では実勢0.95に対し0.79まで下がった）。
        将来を見るための率なので、最新の調査年の実績をそのまま使う。
        """
        if pop_column not in stats.columns:
            return None
        observed = stats[pop_column].dropna()
        for year in sorted((int(y) for y in observed.index), reverse=True):
            start, end = year - offset, year - offset + span - 1
            if start < int(births.index.min()) or end > last_birth_year:
                continue
            base, estimated = births_in(start, end)
            if estimated or base <= 0:
                continue
            return float(observed.loc[year] / base), year
        return None

    stages = [
        # (キー, ラベル, 年齢幅, 生まれ年の起点オフセット, 対象人口カラム, 到達年齢)
        ("nursery", "保育園・こども園", 6, 5, "pop_0_5", 0),
        ("elementary", "小学校", 6, 11, "pop_6_11", 6),
        ("junior", "中学校", 3, 14, "pop_12_14", 12),
    ]

    results: list[dict[str, Any]] = []
    for key, label, span, offset, pop_column, age in stages:
        estimate = settle_rate(pop_column, span, offset)
        if estimate is None:
            continue
        rate, rate_year = estimate

        target_year = birth_year + age
        birth_start = target_year - offset
        birth_end = birth_start + span - 1
        cohort, estimated = births_in(birth_start, birth_end)
        if cohort <= 0:
            continue

        basis = (
            f"{birth_start}〜{birth_end}年生まれ {round(cohort):,}人 × "
            f"定着率{rate:.2f}（{rate_year}年国勢調査）"
        )
        if estimated:
            basis += "／出生数の未公表年は直近3年平均で補完"

        results.append(
            {
                "stage": key,
                "label": label,
                "target_year": target_year,
                "age_range": f"{age}〜{age + span - 1}歳",
                "population": round(cohort * rate),
                "per_grade": round(cohort * rate / span),
                "settle_rate": round(rate, 3),
                "settle_rate_year": rate_year,
                "basis": basis,
                "is_projection": True,
            }
        )

    return results
