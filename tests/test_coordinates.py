"""Googleマップからコピーされてくる文字列のテスト。

pytest が無くても `python tests/test_coordinates.py` で走る。

ケースは実際にコピーできる形をそのまま並べている。とくに
「@ は地図の中心で、目的の地点は !3d/!4d」という区別は、
テストで固めておかないと直したときに気づけない。
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.coordinates import LocationError, parse_location  # noqa: E402

# 大宮駅。どの形でもここに落ちるのが正しい。
LAT, LON = 35.906296, 139.623752


def _close(actual: float, expected: float, tolerance: float = 0.0005) -> bool:
    return abs(actual - expected) <= tolerance


class TestPlainCoordinates:
    def test_right_click_copy(self):
        # 地図を右クリックして座標をクリックしたときの形
        got = parse_location("35.906296, 139.623752")
        assert _close(got["latitude"], LAT) and _close(got["longitude"], LON)

    def test_without_space(self):
        got = parse_location("35.906296,139.623752")
        assert _close(got["latitude"], LAT)

    def test_ideographic_comma(self):
        # 日本語環境でコピーすると読点になることがある
        got = parse_location("35.906296、139.623752")
        assert _close(got["longitude"], LON)

    def test_surrounding_whitespace(self):
        got = parse_location("  35.906296, 139.623752 \n")
        assert _close(got["latitude"], LAT)


class TestUrls:
    def test_browser_url_center(self):
        got = parse_location(
            "https://www.google.com/maps/@35.906296,139.623752,17z"
        )
        assert _close(got["latitude"], LAT)
        assert got["source"] == "地図の中心"

    def test_place_url_prefers_place_over_center(self):
        # @ は地図の中心なので数百mずれる。!3d/!4d が目的の地点。
        got = parse_location(
            "https://www.google.com/maps/place/大宮駅/@35.9051,139.6240,16z/"
            "data=!3m1!4b1!4m6!3m5!1s0x1!8m2!3d35.906296!4d139.623752"
        )
        assert _close(got["latitude"], LAT)
        assert _close(got["longitude"], LON)
        assert got["source"] == "地点の座標"

    def test_query_parameter(self):
        got = parse_location("https://maps.google.com/?q=35.906296,139.623752")
        assert _close(got["latitude"], LAT)

    def test_ll_parameter(self):
        got = parse_location("https://maps.google.com/?ll=35.906296,139.623752&z=17")
        assert _close(got["longitude"], LON)

    def test_negative_coordinates(self):
        # 南半球・西半球。範囲の検証は候補地点の登録側でやるのでここでは通す。
        got = parse_location("https://www.google.com/maps/@-33.868820,151.209290,17z")
        assert _close(got["latitude"], -33.86882)


class TestDms:
    def test_dms_pair(self):
        got = parse_location("35°54'22.7\"N 139°37'25.5\"E")
        assert _close(got["latitude"], LAT)
        assert _close(got["longitude"], LON)
        assert got["source"] == "度分秒"

    def test_dms_southern_hemisphere(self):
        got = parse_location("33°52'7.9\"S 151°12'33.4\"E")
        assert got["latitude"] < 0


class TestRejected:
    def test_short_link_explains_why(self):
        # 短縮URLは展開しないと座標が入っていない。展開にはGoogleへの通信が要る。
        try:
            parse_location("https://maps.app.goo.gl/abcdefg12345")
        except LocationError as exc:
            assert "短縮URL" in str(exc)
            return
        raise AssertionError("短縮URLが通ってしまった")

    def test_goo_gl_maps_short_link(self):
        try:
            parse_location("https://goo.gl/maps/abcdefg")
        except LocationError:
            return
        raise AssertionError("短縮URLが通ってしまった")

    def test_empty(self):
        try:
            parse_location("")
        except LocationError:
            return
        raise AssertionError("空文字が通ってしまった")

    def test_plain_address_is_rejected(self):
        # 住所を貼られても座標は分からない（ジオコーディングはしない方針）
        try:
            parse_location("埼玉県さいたま市大宮区桜木町1-7-5")
        except LocationError as exc:
            assert "読み取れません" in str(exc)
            return
        raise AssertionError("住所が座標として通ってしまった")

    def test_single_number_is_rejected(self):
        try:
            parse_location("35.906296")
        except LocationError:
            return
        raise AssertionError("片方だけの数値が通ってしまった")


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
