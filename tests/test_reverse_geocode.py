"""座標→市区町村の逆引きのテスト。

pytest 無しでも `python tests/test_reverse_geocode.py` で走る。

見ているのは主に「決められないときに決めないこと」。近い市を当ててしまうと、
間違った市区町村が静かに入って、そのまま保存される。
"""

import csv
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import REVERSE_GEOCODE_FILE, REVERSE_GEOCODE_MAX_KM  # noqa: E402
from src.analysis.reverse_geocode import ReverseGeocoder, municipality_for  # noqa: E402

HAS_INDEX = os.path.exists(REVERSE_GEOCODE_FILE)

# 実在の地点と、そこが属する市区町村コード。
KNOWN_POINTS = [
    (35.906296, 139.623752, "11103", "大宮駅"),
    (35.681236, 139.767125, "13101", "東京駅"),
    (35.465786, 139.622313, "14103", "横浜駅"),
    (36.082446, 140.110540, "08220", "つくば駅"),
    (35.801770, 139.717510, "11203", "川口駅"),
]


class TestKnownPoints:
    def test_known_points(self):
        if not HAS_INDEX:
            return
        for latitude, longitude, expected, label in KNOWN_POINTS:
            got = municipality_for(latitude, longitude)
            assert got is not None, f"{label} が引けない"
            assert got["municipality_code"] == expected, (
                f"{label}: {got['municipality_code']} != {expected}"
            )

    def test_distance_is_small_for_urban_points(self):
        # 市街地なら最寄りの町丁目はすぐ近くにある。遠ければ索引がおかしい。
        if not HAS_INDEX:
            return
        got = municipality_for(35.681236, 139.767125)
        assert got["distance_km"] < 0.5, got


class TestRefusesToGuess:
    def test_far_from_any_address_returns_none(self):
        # 太平洋の真ん中。近い市を当ててはいけない。
        if not HAS_INDEX:
            return
        assert municipality_for(35.0, 141.5) is None

    def test_outside_covered_prefectures(self):
        # 大阪は対象17都県の外。索引に無いので決められない。
        if not HAS_INDEX:
            return
        assert municipality_for(34.702485, 135.495951) is None

    def test_threshold_is_respected(self):
        # 閾値を極端に小さくすれば、市街地の点でも決めなくなること。
        if not HAS_INDEX:
            return
        strict = ReverseGeocoder(max_km=0.0001)
        assert strict.lookup(35.681236, 139.767125) is None


class TestMissingIndex:
    def test_no_file_disables_the_feature(self):
        # 索引を生成する前でもサーバーが起動できること（例外にしない）。
        absent = ReverseGeocoder(path="data/does-not-exist.csv")
        assert absent.lookup(35.68, 139.76) is None


class TestIndexShape:
    def test_index_covers_target_prefectures(self):
        if not HAS_INDEX:
            return
        from config import TARGET_PREFECTURE_CODES

        with open(REVERSE_GEOCODE_FILE, encoding="utf-8") as handle:
            prefectures = {row["municipality_code"][:2] for row in csv.DictReader(handle)}
        missing = set(TARGET_PREFECTURE_CODES) - prefectures
        assert not missing, f"対象都県が索引に無い: {missing}"

    def test_threshold_is_sane(self):
        # 大きすぎると対象外の地点にも市区町村が付いてしまう。
        assert 1.0 <= REVERSE_GEOCODE_MAX_KM <= 10.0


def _run_all() -> int:
    if not HAS_INDEX:
        print(f"※ {REVERSE_GEOCODE_FILE} が無いので、内容の検証は省略しています")
        print("  python scripts/build_reverse_geocode.py で生成できます")
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
