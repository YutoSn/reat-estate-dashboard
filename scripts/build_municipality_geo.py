"""市区町村の代表点（緯度経度）を data/municipality_geo.csv に書き出す。

都心へのアクセスを測るには市区町村の位置が要る。e-Stat も不動産情報ライブラリも
座標を返さないため、住所オープンデータ（geolonia/japanese-addresses）の
大字町丁目の座標から市区町村ごとの代表点を求めている。

代表点には平均ではなく **中央値** を使う。町丁目の点は市街地に密に、
山林側に疎に分布するので、中央値を取ると「実際に人が住んでいるあたり」に寄る。
行政区域の幾何重心だと、面積の大半が山地の市（例: 宮古市）で
人の住まない山の中を指してしまう。

出力は402行の小さなCSVなのでリポジトリに含めている。再生成するとき:

    python scripts/build_municipality_geo.py

ネットワークから約50MBのCSVを取得するため、通常の populate.py からは呼ばない。
"""

import csv
import io
import pathlib
import statistics
import sys
import urllib.request

# scripts/ から実行すると sys.path はこのディレクトリになるので、リポジトリ直下を足す
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from config import DUCKDB_FILE  # noqa: E402

SOURCE_URL = (
    "https://raw.githubusercontent.com/geolonia/japanese-addresses/"
    "master/data/latest.csv"
)
OUTPUT_PATH = "data/municipality_geo.csv"

# 住所データに町丁目が1件も無い自治体を手当てする。
# 利島村は大字を持たない（住所が「東京都利島村」で完結する）ため収録されない。
MANUAL_POINTS = {
    "13362": (34.523100, 139.281600),  # 利島村役場
}

# 日本の国土の範囲。壊れた座標を落とすための緩いガード。
LAT_RANGE = (20.0, 46.0)
LON_RANGE = (122.0, 154.0)


def _log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    db = duckdb.connect(DUCKDB_FILE, read_only=True)
    targets = {
        code: (pref, name)
        for code, pref, name in db.execute(
            "SELECT municipality_code, prefecture_name, municipality_name"
            " FROM municipalities ORDER BY municipality_code"
        ).fetchall()
    }
    db.close()
    if not targets:
        _log("市区町村マスタが空です。先に populate.py --stats を実行してください。")
        return 1

    _log(f"住所データを取得中: {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=300) as response:
        payload = response.read().decode("utf-8")
    _log(f"  {len(payload) / 1_000_000:.0f} MB")

    points: dict[str, list[tuple[float, float]]] = {}
    for row in csv.DictReader(io.StringIO(payload)):
        code = row["市区町村コード"]
        if code not in targets:
            continue
        try:
            lat, lon = float(row["緯度"]), float(row["経度"])
        except (TypeError, ValueError):
            continue
        if not (LAT_RANGE[0] < lat < LAT_RANGE[1]):
            continue
        if not (LON_RANGE[0] < lon < LON_RANGE[1]):
            continue
        points.setdefault(code, []).append((lat, lon))

    rows = []
    for code, (prefecture, name) in targets.items():
        if code in points:
            group = points[code]
            latitude = round(statistics.median(p[0] for p in group), 6)
            longitude = round(statistics.median(p[1] for p in group), 6)
            source = "geolonia"
        elif code in MANUAL_POINTS:
            latitude, longitude = MANUAL_POINTS[code]
            source = "manual"
        else:
            _log(f"  座標を決められません: {code} {name}")
            continue
        rows.append((code, prefecture, name, latitude, longitude, source))

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["municipality_code", "prefecture_name", "municipality_name",
             "latitude", "longitude", "source"]
        )
        writer.writerows(rows)

    _log(f"{OUTPUT_PATH} に {len(rows)} / {len(targets)} 件を書き出しました")
    return 0 if len(rows) == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
