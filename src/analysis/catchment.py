"""市区町村の境界をまたいだ「行ける範囲」の供給量を集計する。

なぜ必要か
----------
医師数を自市内の人口で割ると、「自分の市には少ないが、隣の市の病院に
15分で行ける」という実態が落ちる。逆に、大学病院を1つ抱える小さな町は
その町の住民だけで割られて極端に高く出る（矢巾町は岩手医大があるため
自市内 215人/万人 だが、実際には岩手県全体を診ている）。

そこで供給も需要も圏内で合計してから割る。

    圏内密度 = Σ(圏内の供給) / Σ(圏内の需要) × 10000

自市内も圏内に含む（距離0）。距離は代表点どうしの直線距離で、
道路網も山や川も見ていない（src/analysis/geo.py の但し書きと同じ）。

需要は指標ごとに変える
----------------------
小児科を総人口で割ると、高齢者が多く子どもが少ない街ほど「手厚い」と
出てしまう。子どもを診てもらう先を探しているのだから、分母は子どもの数で
なければ意味がない。そこで供給ごとに分母の指標を指定できるようにしている。

圏外の扱い
----------
対象8都県の外に接する自治体は、隣の県の医療機関を数えられないため
過小評価になる。隣接県の統計を取得していればそれを含めて計算し、
取得していなければ「圏内に集計できない自治体がある」ことを印として返す。
数字を黙って出すと、県境の自治体だけ理由なく低く見えるため。
"""

from typing import Any, NamedTuple

import pandas as pd

from config import CATCHMENT_RADIUS_KM
from src.analysis.geo import haversine_km


# 隣接県から保存する指標。圏内の分母（人口）と分子（供給）に要るものだけ。
# 45指標すべてを368自治体ぶん持つとDBが太るので絞る。
# e-Stat は指標ごとに全国を返すので、追加のリクエストは発生しない。
NEIGHBOR_INDICATORS = ("pop_total", "pop_census", "pop_0_14", "doctors", "hospitals")

# 圏内に自治体が含まれるかを判定する基準の需要指標。
# 総人口が取れていない自治体は、そもそも圏内集計に使えない。
PRIMARY_DEMAND = "pop_total"


class SupplySpec(NamedTuple):
    """圏内密度をどう作るかの指定。"""

    supply_key: str   # 分子になる指標
    demand_key: str   # 分母になる指標
    scale: float = 10000.0
    # 分母がこれ未満なら密度を出さない。
    # 七ヶ宿町の15km圏は子ども90人しかおらず、小児科が1施設あるかないかで
    # 「子ども1万人あたり」の値が100以上動く。桁が合わない数字を順位付けに
    # 混ぜると、離島や山間の町がそれだけで上位を占めてしまう。
    min_demand: float = 0.0


class CatchmentPoint(NamedTuple):
    code: str
    latitude: float
    longitude: float
    demands: dict[str, float]        # 需要指標 -> 値
    supply: dict[str, float]         # 供給指標 -> 値
    has_stats: bool                  # 基準の需要が取れているか


def build_points(
    codes: list[str],
    points: dict[str, tuple[float, float]],
    demands: dict[str, dict[str, float | None]],
    supply: dict[str, dict[str, float | None]],
) -> list[CatchmentPoint]:
    """圏内集計に使える地点の一覧を作る。

    座標がある自治体はすべて地点になる。基準の需要（総人口）が取れていない
    自治体は集計に入れないが、「そこに集計できない自治体がある」ことは
    分かるように has_stats=False で残す。
    """
    result = []
    for code in codes:
        if code not in points:
            continue
        latitude, longitude = points[code]
        demand_values = {
            key: value
            for key, value in (demands.get(code) or {}).items()
            if value is not None
        }
        supply_values = {
            key: value
            for key, value in (supply.get(code) or {}).items()
            if value is not None
        }
        primary = demand_values.get(PRIMARY_DEMAND)
        result.append(
            CatchmentPoint(
                code=code,
                latitude=latitude,
                longitude=longitude,
                demands=demand_values,
                supply=supply_values,
                has_stats=primary is not None and primary > 0,
            )
        )
    return result


def catchment_table(
    target_codes: list[str],
    all_points: list[CatchmentPoint],
    supply_specs: list[SupplySpec],
    radius_km: float = CATCHMENT_RADIUS_KM,
) -> pd.DataFrame:
    """対象自治体ごとの圏内密度を返す。

    列は `<supply_key>_catchment` と、集計の透明性のための
    `catchment_municipalities`（圏内の自治体数）、
    `catchment_missing`（圏内で統計が取れていない自治体数）。
    """
    rows = []
    for target in all_points:
        if target.code not in target_codes:
            continue

        near = [
            point for point in all_points
            if haversine_km(
                target.latitude, target.longitude, point.latitude, point.longitude
            ) <= radius_km
        ]
        usable = [point for point in near if point.has_stats]

        row: dict[str, Any] = {
            "municipality_code": target.code,
            "catchment_municipalities": len(near),
            "catchment_missing": len(near) - len(usable),
        }
        for spec in supply_specs:
            # 分母が取れている自治体だけで、分子と分母の両方を足す。
            # 片方だけ足すと比率がずれるため。
            contributors = [
                point for point in usable if spec.demand_key in point.demands
            ]
            demand = sum(point.demands[spec.demand_key] for point in contributors)
            total = sum(
                point.supply.get(spec.supply_key, 0.0) for point in contributors
            )
            usable_demand = demand and demand >= spec.min_demand
            row[f"{spec.supply_key}_catchment"] = (
                total / demand * spec.scale if usable_demand else None
            )
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("municipality_code")
