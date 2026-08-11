"""市区町村の境界をまたいだ「行ける範囲」の供給量を集計する。

なぜ必要か
----------
医師数を自市内の人口で割ると、「自分の市には少ないが、隣の市の病院に
15分で行ける」という実態が落ちる。逆に、大学病院を1つ抱える小さな町は
その町の住民だけで割られて極端に高く出る（矢巾町は岩手医大があるため
自市内 215人/万人 だが、実際には岩手県全体を診ている）。

そこで供給も需要も圏内で合計してから割る。

    圏内密度 = Σ(圏内の医師数) / Σ(圏内の人口) × 10000

自市内も圏内に含む（距離0）。距離は代表点どうしの直線距離で、
道路網も山や川も見ていない（src/analysis/geo.py の但し書きと同じ）。

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
NEIGHBOR_INDICATORS = ("pop_total", "pop_census", "doctors", "hospitals")


class CatchmentPoint(NamedTuple):
    code: str
    latitude: float
    longitude: float
    population: float | None
    supply: dict[str, float]   # 指標キー -> 供給量（実数）
    has_stats: bool            # 統計が取れているか（座標だけの隣接自治体は False）


def build_points(
    codes: list[str],
    points: dict[str, tuple[float, float]],
    population: dict[str, float | None],
    supply: dict[str, dict[str, float | None]],
) -> list[CatchmentPoint]:
    """圏内集計に使える地点の一覧を作る。

    座標がある自治体はすべて地点になる。人口が取れていない自治体は
    需要にも供給にも入れないが、「そこに集計できない自治体がある」ことは
    分かるように has_stats=False で残す。
    """
    result = []
    for code in codes:
        if code not in points:
            continue
        latitude, longitude = points[code]
        pop = population.get(code)
        values = {
            key: value
            for key, value in (supply.get(code) or {}).items()
            if value is not None
        }
        result.append(
            CatchmentPoint(
                code=code,
                latitude=latitude,
                longitude=longitude,
                population=pop,
                supply=values,
                has_stats=pop is not None and pop > 0,
            )
        )
    return result


def catchment_table(
    target_codes: list[str],
    all_points: list[CatchmentPoint],
    supply_keys: list[str],
    radius_km: float = CATCHMENT_RADIUS_KM,
) -> pd.DataFrame:
    """対象自治体ごとの圏内密度を返す。

    列は `<key>_catchment`（人口1万人あたり）と、集計の透明性のための
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
        demand = sum(point.population for point in usable)

        row: dict[str, Any] = {
            "municipality_code": target.code,
            "catchment_municipalities": len(near),
            "catchment_missing": len(near) - len(usable),
        }
        for key in supply_keys:
            total = sum(point.supply.get(key, 0.0) for point in usable)
            row[f"{key}_catchment"] = total / demand * 10000 if demand else None
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("municipality_code")
