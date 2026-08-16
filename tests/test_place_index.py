"""地名索引のテスト。pytest 無しでも `python tests/test_place_index.py` で走る。

見ているのは「引けること」より「引けないときに黙って近い点を返さないこと」。
番地まで当てられないのに市の代表点を返すと、数kmずれた座標が正しい顔で
返ってきて、半径2kmの周辺照会がそのまま狂う。
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.place_index import (  # noqa: E402
    KIND_MUNICIPALITY,
    KIND_STATION,
    PlaceIndex,
    PlaceNotFound,
    describe,
    normalize,
)

index = PlaceIndex()


class TestNormalize:
    def test_full_width_and_spaces(self):
        # スマホからのコピペは全角スペースや全角英数が混ざる。
        assert normalize("大宮　駅") == normalize("大宮駅")
        assert normalize("ＡＢＣ") == normalize("abc")

    def test_parentheses_dropped(self):
        assert normalize("大宮（さいたま）") == normalize("大宮さいたま")


class TestStations:
    def test_exact_station(self):
        found = index.best("大宮駅")
        assert found["kind"] == KIND_STATION
        assert abs(found["latitude"] - 35.906) < 0.01, found

    def test_suffix_optional(self):
        assert index.best("大宮")["name"] == index.best("大宮駅")["name"]

    def test_station_carries_municipality(self):
        # 駅の所属市区町村が空だと画面で「大宮駅（）」になる。
        found = index.best("大宮駅")
        assert found["municipality_name"], found
        assert found["prefecture_name"], found

    def test_same_station_is_merged_across_lines(self):
        # 路線ごとに行があるので、まとめないと同じ駅が何件も出る。
        names = [entry["name"] for entry in index.search("東京駅", limit=5)]
        assert names.count("東京駅") == 1, names

    def test_stations_rank_above_municipalities(self):
        # 市の代表点が先に出ると、数km離れた点をそれと気づかず使ってしまう。
        assert index.best("川口")["kind"] == KIND_STATION


class TestMunicipalities:
    def test_ward(self):
        found = index.best("さいたま市大宮区")
        assert found["kind"] == KIND_MUNICIPALITY
        assert found["municipality_code"] == "11103", found

    def test_with_prefecture_prefix(self):
        assert index.best("埼玉県さいたま市大宮区")["municipality_code"] == "11103"

    def test_describe_flags_representative_point(self):
        # 代表点であることが画面の文言から分かること。
        assert "代表点" in describe(index.best("さいたま市大宮区"))


class TestMisses:
    def test_address_is_not_matched(self):
        # 番地まで当てるデータが無い。近い市で代用しない。
        assert index.search("埼玉県さいたま市大宮区桜木町1-7-5") == []

    def test_unknown_name_raises(self):
        try:
            index.best("ぜんぜんない市")
        except PlaceNotFound:
            return
        raise AssertionError("引けない名前が通ってしまった")

    def test_empty_query(self):
        assert index.search("") == []
        assert index.search("   ") == []


class TestNearest:
    def test_nearest_municipality(self):
        found = index.nearest_municipality(35.906, 139.623)
        assert found["municipality_code"] == "11103", found


def _run_all() -> int:
    passed = failed = 0
    for name, obj in list(globals().items()):
        if not (isinstance(obj, type) and name.startswith("Test")):
            continue
        instance = obj()
        for method in dir(instance):
            if not method.startswith("test_"):
                continue
            try:
                getattr(instance, method)()
                passed += 1
            except Exception:
                failed += 1
                print(f"FAIL {name}.{method}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
