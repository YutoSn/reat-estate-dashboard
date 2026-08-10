"""市区町村の代表点から、都心と広域中心までの距離を出す。

測っているのは **直線距離** であって所要時間ではない。
鉄道の路線網も快速の停車も反映していないので、同じ距離でも
路線が通っている街とそうでない街の差は出ない。

それでも入れているのは、対象8都県の中で「都心に通える範囲か」を
最初に切り分ける力が距離にはあるため。所要時間の公的なオープンデータは
市区町村単位で継続的に取れるものが無く、代替が用意できない。
画面にも距離（km）としてそのまま出し、時間に換算した見せ方はしない。
"""

import csv
import functools
import math
import os

from config import MUNICIPALITY_GEO_FILE, REGIONAL_HUBS, TOKYO_CENTER

EARTH_RADIUS_KM = 6371.0088


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """2点間の大圏距離（km）。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    inner = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(inner))


@functools.cache
def municipality_points() -> dict[str, tuple[float, float]]:
    """市区町村コード -> (緯度, 経度)。CSVが無ければ空で返す。"""
    if not os.path.exists(MUNICIPALITY_GEO_FILE):
        return {}

    points: dict[str, tuple[float, float]] = {}
    with open(MUNICIPALITY_GEO_FILE, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                points[row["municipality_code"]] = (
                    float(row["latitude"]),
                    float(row["longitude"]),
                )
            except (TypeError, ValueError, KeyError):
                continue
    return points


@functools.cache
def access_distances() -> dict[str, dict[str, float | str]]:
    """市区町村ごとの、東京都心と最寄り広域中心までの距離。"""
    _, tokyo_lat, tokyo_lon = TOKYO_CENTER

    result: dict[str, dict[str, float | str]] = {}
    for code, (lat, lon) in municipality_points().items():
        nearest_name, nearest_km = min(
            (
                (name, haversine_km(lat, lon, hub_lat, hub_lon))
                for name, hub_lat, hub_lon in REGIONAL_HUBS
            ),
            key=lambda pair: pair[1],
        )
        result[code] = {
            "tokyo_distance_km": round(
                haversine_km(lat, lon, tokyo_lat, tokyo_lon), 1
            ),
            "hub_distance_km": round(nearest_km, 1),
            "hub_name": nearest_name,
        }
    return result


def access_for(city_code: str) -> dict[str, float | str]:
    """1市区町村分のアクセス距離。座標が無ければ空の辞書。"""
    return access_distances().get(city_code, {})
