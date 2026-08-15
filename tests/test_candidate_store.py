"""候補地点の保存・検証のテスト。

pytest が無くても `python tests/test_candidate_store.py` で走る
（tests/test_specialties.py に倣う）。

実際に間違えやすい入力をそのままケースにしている。とくに緯度経度の
取り違えは、地図から座標を写すときに必ず一度はやる。
"""

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db.candidate_store import (  # noqa: E402
    CandidateStore,
    ValidationError,
    validate,
)

BASE = {
    "name": "大宮区A物件",
    "latitude": 35.906296,
    "longitude": 139.623752,
    "municipality_code": "11103",
}


def _store() -> CandidateStore:
    handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    handle.close()
    os.unlink(handle.name)
    return CandidateStore(handle.name)


class TestValidate:
    def test_minimum_input_passes(self):
        record = validate(BASE)
        assert record["name"] == "大宮区A物件"
        assert record["municipality_code"] == "11103"

    def test_name_is_required(self):
        try:
            validate({**BASE, "name": "   "})
        except ValidationError:
            return
        raise AssertionError("空の呼び名が通ってしまった")

    def test_municipality_is_required(self):
        # 代表点への最近傍で自動判定しない方針なので、未指定は弾く
        payload = {k: v for k, v in BASE.items() if k != "municipality_code"}
        try:
            validate(payload)
        except ValidationError:
            return
        raise AssertionError("市区町村なしが通ってしまった")

    def test_swapped_coordinates_are_rejected(self):
        # 35.9 と 139.6 を入れ違えるのは地図から写すときの定番の間違い
        try:
            validate({**BASE, "latitude": 139.623752, "longitude": 35.906296})
        except ValidationError as exc:
            assert "緯度" in str(exc)
            return
        raise AssertionError("緯度経度の取り違えが通ってしまった")

    def test_non_numeric_coordinates_are_rejected(self):
        try:
            validate({**BASE, "latitude": "だいたいこのへん"})
        except ValidationError:
            return
        raise AssertionError("数値でない緯度が通ってしまった")

    def test_blank_numbers_stay_none(self):
        # 建物面積は土地だけの物件では空になる。0 に潰すと坪単価が壊れる
        record = validate({**BASE, "building_area": "", "price": None})
        assert record["building_area"] is None
        assert record["price"] is None

    def test_negative_price_is_rejected(self):
        try:
            validate({**BASE, "price": -100})
        except ValidationError:
            return
        raise AssertionError("負の価格が通ってしまった")

    def test_unknown_status_is_rejected(self):
        try:
            validate({**BASE, "status": "まだ決めてない"})
        except ValidationError:
            return
        raise AssertionError("未知の status が通ってしまった")

    def test_unknown_fields_are_dropped(self):
        record = validate({**BASE, "owner_phone": "090-0000-0000"})
        assert "owner_phone" not in record


class TestStore:
    def test_missing_file_reads_as_empty(self):
        assert _store().load() == []

    def test_add_then_load(self):
        store = _store()
        saved = store.add({**BASE, "price": 4800})
        assert saved["id"]
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0]["price"] == 4800.0

    def test_update_keeps_untouched_fields(self):
        # メモだけ書き換える操作で、価格が消えては困る
        store = _store()
        saved = store.add({**BASE, "price": 4800, "land_area": 125})
        updated = store.update(saved["id"], {"notes": "南側に3階建て"})
        assert updated["notes"] == "南側に3階建て"
        assert updated["price"] == 4800.0
        assert updated["land_area"] == 125.0
        assert updated["created_at"] == saved["created_at"]

    def test_update_missing_id_returns_none(self):
        assert _store().update("ないid", {"notes": "x"}) is None

    def test_remove(self):
        store = _store()
        saved = store.add(BASE)
        assert store.remove(saved["id"]) is True
        assert store.load() == []
        assert store.remove(saved["id"]) is False

    def test_broken_json_reads_as_empty(self):
        # 手で編集して壊したときに、アプリ全体が起動しなくなるより空のほうがよい
        store = _store()
        os.makedirs(os.path.dirname(store.path) or ".", exist_ok=True)
        with open(store.path, "w", encoding="utf-8") as handle:
            handle.write("{壊れている")
        assert store.load() == []

    def test_ids_are_unique(self):
        store = _store()
        ids = {store.add({**BASE, "name": f"物件{i}"})["id"] for i in range(20)}
        assert len(ids) == 20


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
