"""座標から市区町村を引く。

なぜ必要か
----------
地図でピンを置いたあとに、都道府県と市区町村をプルダウンで選ばせるのは
二度手間になる。場所が決まればその市区町村も決まっているので、自動で入れる。

なぜ代表点への最近傍では駄目か
------------------------------
市区町村ごとに1点だけ持って最近傍を取ると、**市境の地点が隣の市に寄る**。
代表点は市の真ん中にあるので、境界沿いでは隣の市の中心のほうが近くなる。
家を建てる土地はむしろ市境の郊外に多く、いちばん外したくないところで外れる。

そこで町丁目の点（data/municipality_points.csv、107,758点）への最近傍を採る。
数百m間隔で分布するので、行政界のポリゴンを持たなくても実用上の精度が出る。

外れたときに黙って近い市を返さない
----------------------------------
最寄りの町丁目が REVERSE_GEOCODE_MAX_KM より遠ければ、対象の外か、
海上・山間で住所が無い場所。ここで近い市を当てると、**間違った市区町村が
静かに入り、そのまま保存される**。決められないときは決められないと返し、
プルダウンでの選択を残す。
"""

import csv
import os

import numpy as np

from config import REVERSE_GEOCODE_FILE, REVERSE_GEOCODE_MAX_KM

EARTH_RADIUS_KM = 6371.0088


class ReverseGeocoder:
    """町丁目の点への最近傍で市区町村を決める。読み込みは初回だけ。"""

    def __init__(self, path: str = None, max_km: float = None):
        self._path = path or REVERSE_GEOCODE_FILE
        self._max_km = REVERSE_GEOCODE_MAX_KM if max_km is None else max_km
        self._codes = None
        self._latitudes = None
        self._longitudes = None

    def _ensure_loaded(self) -> bool:
        """まだなら読む。ファイルが無ければ機能を切る（生成前でも起動はできる）。"""
        if self._codes is not None:
            return len(self._codes) > 0
        if not os.path.exists(self._path):
            self._codes = []
            return False

        codes, latitudes, longitudes = [], [], []
        with open(self._path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                codes.append(row["municipality_code"])
                latitudes.append(float(row["latitude"]))
                longitudes.append(float(row["longitude"]))

        self._codes = np.array(codes)
        # 10万点あるので、1件ごとに math.sin を呼ぶと目に見えて遅い。
        # ラジアンと余弦は読み込み時に1度だけ作っておく。
        self._latitudes = np.radians(np.array(latitudes))
        self._longitudes = np.radians(np.array(longitudes))
        self._cos_latitudes = np.cos(self._latitudes)
        return len(self._codes) > 0

    def lookup(self, latitude: float, longitude: float) -> dict | None:
        """その座標を含む市区町村。決められなければ None。"""
        if not self._ensure_loaded():
            return None

        phi = np.radians(latitude)
        lambda_ = np.radians(longitude)
        delta_phi = self._latitudes - phi
        delta_lambda = self._longitudes - lambda_
        inner = (
            np.sin(delta_phi / 2) ** 2
            + np.cos(phi) * self._cos_latitudes * np.sin(delta_lambda / 2) ** 2
        )
        distances = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(inner))

        nearest = int(np.argmin(distances))
        distance = float(distances[nearest])
        if distance > self._max_km:
            return None
        return {
            "municipality_code": str(self._codes[nearest]),
            "distance_km": round(distance, 3),
        }


_geocoder = ReverseGeocoder()


def municipality_for(latitude: float, longitude: float) -> dict | None:
    """座標から市区町村コードを引く。"""
    return _geocoder.lookup(latitude, longitude)
