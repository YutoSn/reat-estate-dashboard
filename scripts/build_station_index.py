"""駅の位置・乗降客数・所属市区町村を data/stations.csv に書き出す。

なぜ市区町村を自前で判定するか
------------------------------
不動産情報ライブラリ XKT015（国土数値情報 S12 駅別乗降客数）は、駅名・事業者・
路線・年ごとの乗降客数と座標を返すが、**行政区域コードを持っていない**。
「この市に駅があるか」を出すには自分で割り当てる必要がある。

代表点（市区町村ごとに1点）への最近傍で割り当てると、市境の駅が隣の市に
寄ってしまう。そこで住所オープンデータの**町丁目の点すべて**を使い、
いちばん近い町丁目が属する市区町村を駅の所在地とする。町丁目は数百m間隔で
分布するので、行政界のポリゴンを持たなくても実用上の精度が出る。

乗降客数のフィールド
--------------------
S12_009 から S12_057 まで、4フィールド1年の組で13年分並んでいる。
末尾の S12_057 が最新（令和5年度）。同じ駅でも路線ごとにレコードが分かれ、
同一事業者では1レコードにだけ実数が入り残りは0になる（二重計上を避けるため）。
事業者が違えば別々に計上されるので、駅の総利用者数は単純合計でよい。

    python scripts/build_station_index.py
"""

import csv
import io
import math
import os
import pathlib
import sys
import urllib.request

import numpy as np
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    NEIGHBOR_PREFECTURE_CODES,
    TARGET_PREFECTURE_CODES,
)
from src.analysis.geo import municipality_points  # noqa: E402

ADDRESS_URL = (
    "https://raw.githubusercontent.com/geolonia/japanese-addresses/"
    "master/data/latest.csv"
)
STATION_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external/XKT015"
OUTPUT_PATH = "data/stations.csv"

# XKT015 は z=11 でも広い範囲を返すので、駅を集めるにはこれで足りる
ZOOM = 11
# 「最寄り駅」を出すために、市域の外にある駅も拾えるだけ広めに覆う
COVER_RADIUS_KM = 25

# 最新年の乗降客数が入るフィールド
LATEST_PASSENGER_FIELD = "S12_057"

EARTH_RADIUS_KM = 6371.0088
# 距離行列を作るときの分割数。町丁目は数万点あるのでまとめて持つとメモリが足りない
CHUNK = 200


def _log(message: str) -> None:
    print(message, flush=True)


def tile_xy(latitude: float, longitude: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    return (
        int((longitude + 180.0) / 360.0 * n),
        int((1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * n),
    )


def tiles_covering(points: list[tuple[float, float]], radius_km: float) -> list:
    needed = set()
    for latitude, longitude in points:
        d_lat = radius_km / 111.0
        d_lon = radius_km / (111.0 * max(math.cos(math.radians(latitude)), 0.1))
        x1, y1 = tile_xy(latitude + d_lat, longitude - d_lon, ZOOM)
        x2, y2 = tile_xy(latitude - d_lat, longitude + d_lon, ZOOM)
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                needed.add((x, y))
    return sorted(needed)


def station_centre(geometry: dict) -> tuple[float, float] | None:
    """駅はホームの線分で返るので、その中点を駅の位置とする。"""
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "LineString":
        if not coordinates:
            return None
        lats = [c[1] for c in coordinates]
        lons = [c[0] for c in coordinates]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    if geometry.get("type") == "Point" and len(coordinates) >= 2:
        return coordinates[1], coordinates[0]
    return None


def fetch_stations(api_key: str) -> list[dict]:
    points = list(municipality_points().values())
    if not points:
        raise SystemExit(
            "data/municipality_geo.csv がありません。"
            "先に scripts/build_municipality_geo.py を実行してください。"
        )

    tiles = tiles_covering(points, COVER_RADIUS_KM)
    _log(f"駅を取得中（z={ZOOM} タイル {len(tiles):,} 枚）...")

    session = requests.Session()
    session.headers.update({"Ocp-Apim-Subscription-Key": api_key})

    records: dict[str, dict] = {}
    for index, (x, y) in enumerate(tiles, start=1):
        try:
            response = session.get(
                STATION_URL,
                params={"response_format": "geojson", "z": ZOOM, "x": x, "y": y},
                timeout=60,
            )
        except requests.RequestException:
            continue
        if response.status_code != 200:
            continue
        for feature in response.json().get("features", []):
            properties = feature.get("properties") or {}
            centre = station_centre(feature.get("geometry") or {})
            if centre is None:
                continue
            passengers = properties.get(LATEST_PASSENGER_FIELD)
            records[properties["_id"]] = {
                "station_name": properties.get("S12_001_ja") or "",
                "operator": properties.get("S12_002_ja") or "",
                "line": properties.get("S12_003_ja") or "",
                "latitude": round(centre[0], 6),
                "longitude": round(centre[1], 6),
                "passengers": int(passengers) if isinstance(passengers, (int, float)) else 0,
            }
        if index % 100 == 0 or index == len(tiles):
            _log(f"  [{index:,}/{len(tiles):,}] 駅レコード {len(records):,} 件")

    return list(records.values())


def load_address_points() -> tuple[np.ndarray, list[str]]:
    """町丁目の座標と、その市区町村コードを読み込む。"""
    _log(f"住所データを取得中: {ADDRESS_URL}")
    with urllib.request.urlopen(ADDRESS_URL, timeout=300) as response:
        payload = response.read().decode("utf-8")
    _log(f"  {len(payload) / 1_000_000:.0f} MB")

    wanted = set(TARGET_PREFECTURE_CODES) | set(NEIGHBOR_PREFECTURE_CODES)
    coordinates: list[tuple[float, float]] = []
    codes: list[str] = []
    for row in csv.DictReader(io.StringIO(payload)):
        code = row["市区町村コード"]
        if code[:2] not in wanted:
            continue
        try:
            latitude, longitude = float(row["緯度"]), float(row["経度"])
        except (TypeError, ValueError):
            continue
        coordinates.append((latitude, longitude))
        codes.append(code)

    _log(f"  町丁目 {len(codes):,} 点")
    return np.radians(np.array(coordinates)), codes


def assign_municipalities(
    stations: list[dict], address_points: np.ndarray, address_codes: list[str]
) -> None:
    """各駅を、いちばん近い町丁目が属する市区町村に割り当てる。"""
    station_lat = np.radians(np.array([s["latitude"] for s in stations]))
    station_lon = np.radians(np.array([s["longitude"] for s in stations]))
    point_lat = address_points[:, 0]
    point_lon = address_points[:, 1]
    cos_point = np.cos(point_lat)

    for start in range(0, len(stations), CHUNK):
        lat = station_lat[start:start + CHUNK][:, None]
        lon = station_lon[start:start + CHUNK][:, None]
        delta_lat = point_lat[None, :] - lat
        delta_lon = point_lon[None, :] - lon
        inner = (
            np.sin(delta_lat / 2) ** 2
            + np.cos(lat) * cos_point[None, :] * np.sin(delta_lon / 2) ** 2
        )
        nearest = inner.argmin(axis=1)
        distance = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(
            inner[np.arange(len(nearest)), nearest]
        ))
        for offset, (index, km) in enumerate(zip(nearest, distance)):
            station = stations[start + offset]
            station["municipality_code"] = address_codes[index]
            station["address_distance_km"] = round(float(km), 3)


def main() -> int:
    load_dotenv()
    api_key = os.getenv("REAL_ESTATE_LIBRARY_API_KEY")
    if not api_key:
        _log("REAL_ESTATE_LIBRARY_API_KEY が設定されていません")
        return 1

    stations = fetch_stations(api_key)
    if not stations:
        _log("駅を1件も取得できませんでした")
        return 1

    address_points, address_codes = load_address_points()
    assign_municipalities(stations, address_points, address_codes)

    stations.sort(
        key=lambda s: (s["municipality_code"], s["station_name"], s["operator"])
    )
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "municipality_code", "station_name", "operator", "line",
                "latitude", "longitude", "passengers", "address_distance_km",
            ],
        )
        writer.writeheader()
        writer.writerows(stations)

    in_target = sum(
        1 for s in stations if s["municipality_code"][:2] in TARGET_PREFECTURE_CODES
    )
    _log(
        f"{OUTPUT_PATH} に {len(stations):,} レコード"
        f"（うち対象8都県 {in_target:,}）を書き出しました"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
