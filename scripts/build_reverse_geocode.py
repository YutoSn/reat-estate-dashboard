"""座標から市区町村を引くための町丁目インデックスを書き出す。

なぜ必要か
----------
地図でピンを置いたとき、市区町村を人に選ばせるのは二度手間になる。
場所が決まればその市区町村も決まっているのだから、自動で入るべき。

なぜ代表点への最近傍では駄目か
------------------------------
市区町村ごとに1点だけ持って最近傍を取ると、**市境の物件が隣の市に寄る**。
代表点は市の真ん中にあるので、境界沿いでは隣の市の中心のほうが近くなる。
家を建てる土地はむしろ市境の郊外に多いので、いちばん外したくないところで
外れる。

そこで住所オープンデータの**町丁目の点すべて**を持ち、いちばん近い町丁目が
属する市区町村を採る。町丁目は数百m間隔で分布するので、行政界のポリゴンを
持たなくても実用上の精度が出る。駅の所在地判定
（scripts/build_station_index.py）と同じ考え方で、そちらで実績がある。

行政界のポリゴン（国土数値情報 N03）を使えばもっと正確だが、この環境からは
取得できず、ポリゴン内外判定のために依存も増える。町丁目の点で足りる。

    python scripts/build_reverse_geocode.py

出典: https://github.com/geolonia/japanese-addresses （CC BY 4.0）
"""

import csv
import io
import pathlib
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    NEIGHBOR_PREFECTURE_CODES,
    REVERSE_GEOCODE_FILE,
    TARGET_PREFECTURE_CODES,
)

ADDRESS_URL = (
    "https://raw.githubusercontent.com/geolonia/japanese-addresses/"
    "master/data/latest.csv"
)

# 小数5桁でおよそ1m。番地を当てるわけではないのでこれで足りる。
# 桁を落とすとファイルが小さくなるが、市境の判定が粗くなる。
COORDINATE_DIGITS = 5


def _download(url: str, attempts: int = 4) -> str:
    """50MBほどあるので、途中で切れたら取り直す。

    urllib だと IncompleteRead で落ちることがある（実際に落ちた）。
    ここで諦めると生成物が中途半端に書かれるので、読み切れたときだけ返す。
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            return response.content.decode("utf-8")
        except Exception as error:  # 通信の失敗はすべて同じ扱いでよい
            last_error = error
            print(f"  取得に失敗（{attempt}/{attempts}）: {error}")
            time.sleep(2**attempt)
    raise RuntimeError(f"住所データを取得できませんでした: {last_error}")


def build() -> None:
    keep = set(TARGET_PREFECTURE_CODES) | set(NEIGHBOR_PREFECTURE_CODES)

    print(f"住所データを取得: {ADDRESS_URL}")
    raw = _download(ADDRESS_URL)

    rows = []
    seen = set()
    for row in csv.DictReader(io.StringIO(raw)):
        if row["都道府県コード"] not in keep:
            continue
        if not row["緯度"] or not row["経度"]:
            continue
        latitude = round(float(row["緯度"]), COORDINATE_DIGITS)
        longitude = round(float(row["経度"]), COORDINATE_DIGITS)
        # 同じ座標の重複（小字違いなど）は落とす。判定結果は変わらない。
        key = (latitude, longitude)
        if key in seen:
            continue
        seen.add(key)
        rows.append((row["市区町村コード"], latitude, longitude))

    rows.sort()
    path = pathlib.Path(REVERSE_GEOCODE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["municipality_code", "latitude", "longitude"])
        writer.writerows(rows)

    codes = {row[0] for row in rows}
    size_mb = path.stat().st_size / 1e6
    print(f"{path}: {len(rows):,}点 / {len(codes)}市区町村 / {size_mb:.2f}MB")


if __name__ == "__main__":
    build()
