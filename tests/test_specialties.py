"""診療科目の判定ルールの回帰テスト。

実データで見つかった表記ゆれを、そのままケースにしてある。
判定を緩めると小児歯科が小児科に混ざるので、ここが落ちたら要注意。

    python -m pytest tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.specialties import (  # noqa: E402
    is_obstetric,
    is_pediatric,
    tokenize,
)


class TestTokenize:
    def test_splits_on_full_width_space(self):
        assert tokenize("内科　小児科　アレルギー科") == [
            "内科", "小児科", "アレルギー科",
        ]

    def test_splits_on_ascii_space(self):
        assert tokenize("内科 小児科") == ["内科", "小児科"]

    def test_empty(self):
        assert tokenize("") == []
        assert tokenize(None) == []

    def test_keeps_nakaguro_joined_terms(self):
        # 中黒で連結された表記を割ると、歯科側の件数が実態より増える
        assert tokenize("小児歯科・歯科口腔外科") == ["小児歯科・歯科口腔外科"]


class TestPediatric:
    def test_full_name(self):
        assert is_pediatric("内科　小児科　皮膚科", "診療所")

    def test_hospital_abbreviation(self):
        # 病院は一文字略称。「小」は小児科を指す
        assert is_pediatric("内　外　小　泌　眼　耳　整", "病院")

    def test_shortened_form(self):
        assert is_pediatric("小児", "診療所")
        assert is_pediatric("内科　小児", "診療所")

    def test_rejects_pediatric_dentistry(self):
        # 最も危険な誤判定。部分一致だとここで落ちる
        assert not is_pediatric("歯科　小児歯科　矯正歯科", "歯科診療所")
        assert not is_pediatric("小歯", "歯科診療所")

    def test_rejects_split_dental_notation(self):
        # 一部の歯科医院は「小児歯科」を『歯科　小児』と分けて書く。
        # トークン単位でも単独の「小児」が現れるので、種別で落とすしかない
        assert not is_pediatric("歯科　歯科　小児　歯科　口腔外科", "歯科診療所")
        assert not is_pediatric("歯科　歯科　小児", "歯科診療所")

    def test_rejects_pediatric_subspecialties(self):
        # 小児外科・小児皮膚科は乳幼児を日常的に診てもらう先ではない
        assert not is_pediatric("外科　小児外科", "病院")
        assert not is_pediatric("皮膚科　小児皮膚科　アレルギー科", "診療所")
        assert not is_pediatric("神経内科　小児神経内科", "診療所")
        assert not is_pediatric("小児眼科", "診療所")
        assert not is_pediatric("小アレ", "診療所")

    def test_rejects_ambiguous_compound(self):
        # 「小児科歯科」は分割されないので完全一致に掛からない
        assert not is_pediatric("小児科歯科", "歯科診療所")

    def test_large_hospital_with_both(self):
        # 小児科と小児歯科の両方を持つ大病院は、正しく小児科として数える
        subject = (
            "内科　小児科　外科　歯科　矯正歯科　小児歯科　歯科口腔外科"
        )
        assert is_pediatric(subject, "病院")

    def test_empty_subject(self):
        assert not is_pediatric("", "診療所")
        assert not is_pediatric(None, "診療所")


class TestObstetric:
    def test_full_names(self):
        assert is_obstetric("産婦人科", "診療所")
        assert is_obstetric("内科　皮膚科　産婦人科", "診療所")
        assert is_obstetric("婦人科　産科　内科", "診療所")

    def test_abbreviations(self):
        assert is_obstetric("産　婦　小　内", "診療所")
        assert is_obstetric("内　外　小　泌　産婦　精", "病院")

    def test_rejects_gynecology_only(self):
        # 婦人科だけの施設は出産を扱わない
        assert not is_obstetric("婦人科", "診療所")
        assert not is_obstetric("内科　婦人科　皮膚科", "診療所")
        assert not is_obstetric("婦", "病院")

    def test_rejects_dental(self):
        assert not is_obstetric("歯科　小児歯科", "歯科診療所")


def _run_all() -> int:
    """pytest が無くても `python tests/test_specialties.py` で走らせる。"""
    import traceback

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
