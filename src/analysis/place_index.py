"""地名・駅名から座標を引く。通信は使わない。

なぜ自前の索引か
----------------
スマホから貼れる位置情報は座標ばかりではない。「大宮駅」「さいたま市大宮区」
のような**地名そのもの**が一番打ちやすい。ジオコーダを外部に呼びに行くと、
物件を見ている現地の電波状況に結果が左右されるし、このアプリは実行時に
外部へ出ない作りなので、手元のデータだけで引く。

材料は既にリポジトリにある2つ。

    data/stations.csv          駅名と座標（4500件）      → 数十m の精度
    data/municipality_geo.csv  市区町村の代表点（770件） → 市の真ん中でしかない

駅は「その駅の場所」を指すので候補地点の登録に使える。市区町村の代表点は
**市の中心であって物件の場所ではない**。同じ扱いにすると数kmずれたまま
半径2kmの周辺照会を回すことになるので、どちらで引いたかを必ず返し、
画面でも見分けが付くようにする。

住所（丁目・番地）は引けない
----------------------------
番地まで当てるには別の住所マスタが要る。無いものを近い市の代表点で
代用すると、それらしい座標が返ってきて誤りに気づけない。住所しか無い
ときは素直に引けないと返し、Plus Code か座標を使ってもらう。
"""

import csv
import os
import unicodedata
from statistics import median

from config import MUNICIPALITY_GEO_FILE, STATIONS_FILE

# 同名の駅・地名があるので、候補は複数返して選んでもらう。
MAX_CANDIDATES = 8

# 駅は数十m、市区町村は代表点。呼び出し側が精度を説明できるようにしておく。
KIND_STATION = "駅"
KIND_MUNICIPALITY = "市区町村"


class PlaceNotFound(LookupError):
    """その名前では引けない。"""


def normalize(text: str) -> str:
    """全角・半角、空白、カッコの揺れを吸収する。

    スマホからのコピペは全角スペースや異体字が混ざる。NFKC でそろえてから
    比較しないと「大宮　駅」が引けない。
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).strip().lower()
    for character in (" ", "　", "\t", "(", ")", "（", "）", "・"):
        folded = folded.replace(character, "")
    return folded


def _strip_station_suffix(name: str) -> str:
    """「大宮駅」で引かれたときのために末尾の「駅」を落とした形も持つ。"""
    return name[:-1] if name.endswith("駅") and len(name) > 1 else name


class PlaceIndex:
    """名前 → 座標の索引。読み込みは初回だけ。"""

    def __init__(self, stations_file: str = None, geo_file: str = None):
        self._entries: list[dict] = []
        self._loaded = False
        self._stations_file = stations_file or STATIONS_FILE
        self._geo_file = geo_file or MUNICIPALITY_GEO_FILE

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        # 駅の所属市区町村名を引くために、市区町村を先に入れてから駅を足す。
        self._entries = self._load_municipalities()
        self._entries.extend(self._load_stations())
        self._loaded = True

    def _load_municipalities(self) -> list[dict]:
        if not os.path.exists(self._geo_file):
            return []
        entries = []
        with open(self._geo_file, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = row["municipality_name"]
                entries.append(
                    {
                        "name": name,
                        "kind": KIND_MUNICIPALITY,
                        "municipality_code": row["municipality_code"],
                        "municipality_name": name,
                        "prefecture_name": row["prefecture_name"],
                        "latitude": float(row["latitude"]),
                        "longitude": float(row["longitude"]),
                        # 「埼玉県さいたま市大宮区」と県名込みで貼られても引けるように。
                        "aliases": [name, row["prefecture_name"] + name],
                    }
                )
        return entries

    def _load_stations(self) -> list[dict]:
        """同じ駅が路線ごとに複数行あるので、駅ごとにまとめる。

        路線ごとの座標はホームの位置で数十mずれる。平均だと乗り入れの多い駅で
        外れ値に引かれるため中央値を採る（市区町村の代表点と同じ考え方）。
        """
        if not os.path.exists(self._stations_file):
            return []

        municipality_names = {
            entry["municipality_code"]: entry
            for entry in self._entries
            if entry["kind"] == KIND_MUNICIPALITY
        }

        grouped: dict[tuple[str, str], list[dict]] = {}
        with open(self._stations_file, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["station_name"], row["municipality_code"])
                grouped.setdefault(key, []).append(row)

        entries = []
        for (name, code), rows in grouped.items():
            municipality = municipality_names.get(code, {})
            entries.append(
                {
                    "name": name + "駅",
                    "kind": KIND_STATION,
                    "municipality_code": code,
                    "municipality_name": municipality.get("municipality_name", ""),
                    "prefecture_name": municipality.get("prefecture_name", ""),
                    "latitude": median(float(row["latitude"]) for row in rows),
                    "longitude": median(float(row["longitude"]) for row in rows),
                    "lines": sorted({row["line"] for row in rows if row["line"]}),
                    "aliases": [name, name + "駅"],
                }
            )
        return entries

    def search(self, query: str, limit: int = MAX_CANDIDATES) -> list[dict]:
        """名前で引いて、確からしい順に候補を返す。

        完全一致 → 前方一致 → 部分一致 の順。同じ強さなら、場所が細かい
        駅を市区町村より前に出す（「大宮」で市の代表点が先に出ると、
        数km離れた点をそれと気づかず使ってしまう）。
        """
        self._ensure_loaded()
        needle = normalize(_strip_station_suffix(query or ""))
        if not needle:
            return []

        scored = []
        for entry in self._entries:
            best = None
            for alias in entry["aliases"]:
                folded = normalize(alias)
                if not folded:
                    continue
                if folded == needle:
                    rank = 0
                elif folded.startswith(needle):
                    rank = 1
                elif needle in folded:
                    rank = 2
                else:
                    continue
                best = rank if best is None else min(best, rank)
            if best is not None:
                # 駅を先に出すため、同順位内では 0 を足す（市区町村は 1）。
                kind_rank = 0 if entry["kind"] == KIND_STATION else 1
                scored.append(((best, kind_rank, len(entry["name"])), entry))

        scored.sort(key=lambda pair: pair[0])
        return [entry for _, entry in scored[:limit]]

    def best(self, query: str) -> dict:
        """一番それらしい1件。無ければ PlaceNotFound。"""
        found = self.search(query, limit=1)
        if not found:
            raise PlaceNotFound(query)
        return found[0]

    def nearest_municipality(self, latitude: float, longitude: float) -> dict | None:
        """座標に一番近い市区町村の代表点。Plus Code 短縮形の参照に使う。"""
        self._ensure_loaded()
        candidates = [e for e in self._entries if e["kind"] == KIND_MUNICIPALITY]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda e: (e["latitude"] - latitude) ** 2 + (e["longitude"] - longitude) ** 2,
        )


def describe(entry: dict) -> str:
    """画面に出す一行。どのくらいの精度かが分かる書き方にする。"""
    where = entry.get("municipality_name") or ""
    prefecture = entry.get("prefecture_name") or ""
    if entry["kind"] == KIND_STATION:
        return f"{entry['name']}（{prefecture}{where}）"
    return f"{prefecture}{entry['name']} の代表点"
