"""不動産情報ライブラリ XKT010（医療機関）の取得と正規化。

国土数値情報の医療機関データを、施設単位（点）で返すタイルAPI。
座標が付いているので、市区町村の枠に縛られず「そこから何km以内に
小児科が何か所あるか」を数えられる。

タイル方式でズームは z=13 しか受け付けない（z=12以下は400、z=16以上も400）。
そのため対象402自治体の15km圏を覆うだけで約5,000タイルになる。
年1回程度しか更新されないデータなので、取得は populate.py --medical に分けている。
"""

import math
import time
from typing import Any, Iterator

import requests

BASE_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external/XKT010"

# APIが受け付ける唯一の広域ズーム。これより粗いタイルは指定できない。
ZOOM = 13


def tile_xy(latitude: float, longitude: float, zoom: int = ZOOM) -> tuple[int, int]:
    """緯度経度を Web メルカトルのタイル座標に変換する。"""
    n = 2 ** zoom
    x = int((longitude + 180.0) / 360.0 * n)
    y = int(
        (1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * n
    )
    return x, y


def tiles_covering(
    points: list[tuple[float, float]], radius_km: float, zoom: int = ZOOM
) -> list[tuple[int, int]]:
    """各地点の半径 radius_km を覆うタイルの集合（重複除去済み）。"""
    needed: set[tuple[int, int]] = set()
    for latitude, longitude in points:
        d_lat = radius_km / 111.0
        # 高緯度ほど経度1度は短くなる
        d_lon = radius_km / (111.0 * max(math.cos(math.radians(latitude)), 0.1))
        x1, y1 = tile_xy(latitude + d_lat, longitude - d_lon, zoom)
        x2, y2 = tile_xy(latitude - d_lat, longitude + d_lon, zoom)
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                needed.add((x, y))
    return sorted(needed)


class MedicalFacilityAPI:
    """医療機関の点データをタイル単位で取得する。"""

    def __init__(self, api_key: str, request_interval: float = 0.15):
        if not api_key:
            raise ValueError("REAL_ESTATE_LIBRARY_API_KEY が設定されていません")
        self.api_key = api_key
        self.request_interval = request_interval
        self._session = requests.Session()
        self._session.headers.update({"Ocp-Apim-Subscription-Key": api_key})

    def fetch_tile(
        self, x: int, y: int, zoom: int = ZOOM, retries: int = 2
    ) -> list[dict[str, Any]]:
        """1タイル分の施設を返す。取得できなければ空リスト。"""
        for attempt in range(retries + 1):
            try:
                response = self._session.get(
                    BASE_URL,
                    params={
                        "response_format": "geojson",
                        "z": zoom,
                        "x": x,
                        "y": y,
                    },
                    timeout=60,
                )
            except requests.RequestException:
                if attempt == retries:
                    return []
                time.sleep(1.5 * (attempt + 1))
                continue

            time.sleep(self.request_interval)

            if response.status_code == 200:
                try:
                    return response.json().get("features", []) or []
                except ValueError:
                    return []
            # 429/5xx は間を置いて再試行する。400台のその他は諦める。
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == retries:
                    return []
                time.sleep(2.0 * (attempt + 1))
                continue
            return []
        return []

    def fetch_tiles(
        self, tiles: list[tuple[int, int]], zoom: int = ZOOM
    ) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        """タイルを順に取得し、(通し番号, 施設リスト) を返す。"""
        for index, (x, y) in enumerate(tiles, start=1):
            yield index, self.fetch_tile(x, y, zoom)


def _to_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _to_int(raw: Any) -> int | None:
    value = _to_float(raw)
    return int(value) if value is not None else None


def normalize_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    """GeoJSON の1フィーチャを DB スキーマに合わせて正規化する。"""
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []

    if len(coordinates) < 2:
        return None
    longitude, latitude = _to_float(coordinates[0]), _to_float(coordinates[1])
    if latitude is None or longitude is None:
        return None

    facility_id = properties.get("_id")
    if not facility_id:
        return None

    return {
        "facility_id": str(facility_id),
        "name": properties.get("P04_002_ja") or None,
        "facility_type": properties.get("P04_001_name_ja") or None,
        "address": properties.get("P04_003_ja") or None,
        "medical_subject": properties.get("medical_subject_ja")
        or properties.get("P04_004")
        or None,
        "latitude": latitude,
        "longitude": longitude,
        "beds": _to_int(properties.get("P04_008")),
    }
