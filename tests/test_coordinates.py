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


class TestShortLink:
    """スマホの共有メニューが出す短縮URL。

    展開には Google への通信が要るので、テストでは fetch を差し替える。
    実際に通信させると、CI や機内モードでの実行が落ちるうえ、
    Google側の応答次第でテストの結果が変わってしまう。
    """

    def test_expands_to_place_coordinates(self):
        # 展開先が地点URLなら、@ ではなく !3d/!4d を読むこと。
        expanded = (
            "https://www.google.com/maps/place/%E5%A4%A7%E5%AE%AE%E9%A7%85/"
            "@35.9051,139.6240,16z/data=!3m1!4b1!4m6!3d35.906296!4d139.623752"
        )
        got = parse_location(
            "https://maps.app.goo.gl/abcdefg12345", fetch=lambda url: expanded
        )
        assert abs(got["latitude"] - 35.906296) < 1e-6
        assert abs(got["longitude"] - 139.623752) < 1e-6
        assert "共有リンク" in got["source"]

    def test_short_link_inside_shared_text(self):
        # 共有はたいてい「大宮駅 https://maps.app.goo.gl/xxx」の形で貼られる。
        got = parse_location(
            "大宮駅\nhttps://maps.app.goo.gl/abcdefg12345",
            fetch=lambda url: "https://www.google.com/maps/@35.906296,139.623752,17z",
        )
        assert abs(got["latitude"] - 35.906296) < 1e-6

    def test_unreachable_link_suggests_plus_code(self):
        # 圏外や遮断で展開できないときは、通信の要らない Plus Code に誘導する。
        try:
            parse_location("https://maps.app.goo.gl/abcdefg12345", fetch=lambda url: None)
        except LocationError as exc:
            assert "Plus Code" in str(exc)
            return
        raise AssertionError("展開できなかったのに通ってしまった")

    def test_expanded_without_coordinates(self):
        # 展開できても座標が無い行き先（同意ページなど）があり得る。
        try:
            parse_location(
                "https://goo.gl/maps/abcdefg",
                fetch=lambda url: "https://consent.google.com/m?continue=x",
            )
        except LocationError as exc:
            assert "Plus Code" in str(exc)
            return
        raise AssertionError("座標が無いのに通ってしまった")


class TestPlusCode:
    """スマホのGoogleマップが地点の詳細に出す Plus Code。

    通信が要らないので、共有リンクが使えない場面での本命の入力経路になる。
    コード自体の正しさは tests/test_plus_code.py が公式ベクタで見ているので、
    ここでは「貼り付けられた文字列から拾えるか」だけを見る。
    """

    def test_full_code(self):
        got = parse_location("8Q7XWJ4F+GG")
        assert abs(got["latitude"] - 35.906) < 0.01, got
        assert abs(got["longitude"] - 139.624) < 0.01, got
        assert got["source"] == "Plus Code"

    def test_short_code_with_place_name(self):
        # アプリが出すのはこの形。「WJ4F+GG さいたま市大宮区」
        got = parse_location("WJ4F+GG さいたま市大宮区")
        assert abs(got["latitude"] - 35.906) < 0.01, got
        assert abs(got["longitude"] - 139.624) < 0.01, got

    def test_short_code_with_station_name(self):
        got = parse_location("WJ4F+GG 大宮駅")
        assert abs(got["latitude"] - 35.906) < 0.01, got

    def test_short_code_lowercase(self):
        got = parse_location("wj4f+gg さいたま市大宮区")
        assert abs(got["latitude"] - 35.906) < 0.01, got

    def test_short_code_without_place_name_is_rejected(self):
        # 参照地点が無いと場所が決まらない。近くの市で代用しない。
        try:
            parse_location("WJ4F+GG")
        except LocationError as exc:
            assert "地名" in str(exc)
            return
        raise AssertionError("参照地点なしで通ってしまった")

    def test_short_code_with_unknown_place_is_rejected(self):
        try:
            parse_location("WJ4F+GG ぜんぜんない市")
        except LocationError as exc:
            assert "分かりません" in str(exc)
            return
        raise AssertionError("引けない地名で通ってしまった")


class TestPlaceName:
    """地名・駅名。手元の索引だけで引く。"""

    def test_station(self):
        got = parse_location("大宮駅")
        assert abs(got["latitude"] - 35.906) < 0.01, got
        assert "大宮駅" in got["source"]

    def test_station_without_suffix(self):
        got = parse_location("大宮")
        assert abs(got["latitude"] - 35.906) < 0.01, got

    def test_municipality_is_flagged_as_approximate(self):
        # 市区町村は代表点。物件の位置ではないと分かるようにする。
        got = parse_location("さいたま市大宮区")
        assert "代表点" in got["source"]
        assert got.get("detail") and "数km" in got["detail"]

    def test_offers_alternatives(self):
        # 同名・類似名があるので、選び直せるように候補を返す。
        got = parse_location("大宮")
        assert got.get("alternatives"), got

    def test_address_is_not_guessed(self):
        # 番地まで当てるデータが無い。近い市の代表点で代用しない。
        try:
            parse_location("埼玉県さいたま市大宮区桜木町1-7-5")
        except LocationError as exc:
            assert "Plus Code" in str(exc)
            return
        raise AssertionError("住所が通ってしまった")

    def test_coordinates_win_over_place_names(self):
        # URL の中にたまたま駅名が入っていても、座標を優先すること。
        got = parse_location("https://www.google.com/maps/place/大宮駅/@35.7,139.7,17z")
        assert abs(got["latitude"] - 35.7) < 1e-6, got


class TestSwappedCoordinates:
    def test_warns_when_outside_japan(self):
        # 緯度と経度を入れ違えた典型。黙って通すと周辺照会が0件になるだけ。
        got = parse_location("139.623752, 35.906296")
        assert got.get("warning"), got

    def test_no_warning_for_japan(self):
        got = parse_location("35.906296, 139.623752")
        assert not got.get("warning"), got


class TestRejected:
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
