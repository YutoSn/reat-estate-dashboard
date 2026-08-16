"""Plus Code の実装を Google公式のテストベクタで検証する。

なぜベクタを取り込んでいるか
----------------------------
仕様を覚えている範囲で書くと、格子部分の刻み（縦5・横4）や短縮形の
戻し方のような細かいところが静かに間違う。間違っても数十m〜数kmずれる
だけなので、目視では気づけない。tests/data/open_location_code/ に
公式の CSV をそのまま置き、全行を突き合わせる。

    出典: https://github.com/google/open-location-code (test_data/)
    取得: 2026-08 / Apache-2.0

CSV を更新したくなったら上記から取り直す。ネットワークが要るのは
取り直すときだけで、テスト自体はオフラインで走る。
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.plus_code import (  # noqa: E402
    PlusCodeError,
    decode,
    encode,
    is_full,
    is_short,
    is_valid,
    recover_nearest,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "open_location_code")


def _rows(name: str) -> list[list[str]]:
    """公式CSVはコメント行と空行を含むので落とす。"""
    path = os.path.join(DATA_DIR, name)
    with open(path, encoding="utf-8") as handle:
        return [
            row
            for row in csv.reader(handle)
            if row and not row[0].startswith("#") and row[0].strip()
        ]


def test_official_decoding_vectors():
    """decoding.csv の全行。矩形の四隅が一致すること。"""
    rows = _rows("decoding.csv")
    assert len(rows) > 100, f"ベクタが少なすぎる: {len(rows)}"
    for code, length, lat_lo, lng_lo, lat_hi, lng_hi in rows:
        area = decode(code)
        assert area["code_length"] == int(length), code
        # 公式CSVは小数10桁まで。浮動小数の丸め差だけ許す。
        assert abs(area["latitude_low"] - float(lat_lo)) < 1e-9, f"{code} latLo"
        assert abs(area["longitude_low"] - float(lng_lo)) < 1e-9, f"{code} lngLo"
        assert abs(area["latitude_high"] - float(lat_hi)) < 1e-9, f"{code} latHi"
        assert abs(area["longitude_high"] - float(lng_hi)) < 1e-9, f"{code} lngHi"


def test_official_encoding_vectors():
    """encoding.csv の全行。座標からコードに戻せること。"""
    rows = _rows("encoding.csv")
    assert len(rows) > 100, f"ベクタが少なすぎる: {len(rows)}"
    for latitude, longitude, _lat_int, _lng_int, length, expected in rows:
        assert encode(float(latitude), float(longitude), int(length)) == expected, (
            f"{latitude},{longitude} @{length}"
        )


def test_official_validity_vectors():
    """validityTests.csv の全行。妥当性判定が一致すること。"""
    rows = _rows("validityTests.csv")
    assert len(rows) > 20, f"ベクタが少なすぎる: {len(rows)}"
    for code, valid, short, full in rows:
        assert is_valid(code) == (valid == "true"), f"is_valid({code})"
        assert is_short(code) == (short == "true"), f"is_short({code})"
        assert is_full(code) == (full == "true"), f"is_full({code})"


def test_official_short_code_vectors():
    """shortCodeTests.csv の復元側（R と B）。短縮形を参照地点で戻せること。"""
    rows = _rows("shortCodeTests.csv")
    assert len(rows) > 10, f"ベクタが少なすぎる: {len(rows)}"
    checked = 0
    for full, latitude, longitude, short, test_type in rows:
        if test_type not in ("R", "B"):
            continue
        assert recover_nearest(short, float(latitude), float(longitude)) == full, short
        checked += 1
    assert checked > 10, f"復元ベクタが少なすぎる: {checked}"


def test_japanese_place_round_trip():
    """日本の座標で往復すること。西経・南緯の符号取り違えを拾う。"""
    latitude, longitude = 35.906296, 139.623752  # 大宮駅あたり
    code = encode(latitude, longitude, 11)
    area = decode(code)
    assert abs(area["latitude"] - latitude) < 0.0002, code
    assert abs(area["longitude"] - longitude) < 0.0002, code


def test_short_code_with_japanese_reference():
    """スマホが出す「WJ4F+GG さいたま市」の形を、市の代表点から戻せること。"""
    latitude, longitude = 35.906296, 139.623752
    full = encode(latitude, longitude, 10)
    short = full[4:]  # 先頭4文字が落ちた形
    # さいたま市の代表点（数km離れている）を参照にしても同じ升目に戻る。
    recovered = recover_nearest(short, 35.8617, 139.6455)
    assert recovered == full, f"{short} -> {recovered}"


def test_full_code_is_returned_as_is():
    """フルコードを渡したら参照地点は無視して素通しすること。"""
    full = encode(35.906296, 139.623752, 10)
    assert recover_nearest(full, 0.0, 0.0) == full


def test_lowercase_is_accepted():
    """コピペで小文字になっていても読めること。"""
    full = encode(35.906296, 139.623752, 10)
    assert decode(full.lower())["latitude"] == decode(full)["latitude"]


def test_rejects_non_code():
    """住所のような文字列は明示的に落とすこと。"""
    for text in ("埼玉県さいたま市", "35.9,139.6", "", "++", "8Q7XWJQ2"):
        assert not is_full(text), text


def test_decode_rejects_short_code():
    """短縮形をそのまま decode に渡したら、黙って別の場所を返さないこと。"""
    try:
        decode("WJ4F+GG")
    except PlusCodeError:
        return
    raise AssertionError("短縮コードが decode を素通りした")


def _run_all():
    """pytest 無しでも走らせる。"""
    failures = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print(f"  ok  {name}")
            except AssertionError as error:
                failures += 1
                print(f"  NG  {name}: {error}")
    print(f"\n{'失敗あり' if failures else 'すべて成功'} ({failures} 件失敗)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
