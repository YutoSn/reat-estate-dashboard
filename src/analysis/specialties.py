"""医療機関の「診療科目」文字列から、標榜している科を判定する。

国土数値情報（不動産情報ライブラリ XKT010）の診療科目は、施設によって
表記がまったく揃っていない。

    診療所   「内科　小児科　アレルギー科」   … 正式名
    病院     「内　外　小　泌　眼　耳　整」   … 一文字略称
    歯科     「歯科　小児歯科　矯正歯科」     … 小児"歯科"

そのため部分一致で数えると事故る。実データ10,983施設で数えたところ

    小児歯科 1,882 件 > 小児科 862 件

で、`"小児" in text` のような判定では小児科が3倍以上に水増しされる。
ここではトークンに分割したうえで**完全一致**でのみ判定する。
"""

import re

# 区切りは全角/半角スペース。中黒で連結された表記（例「小児歯科・歯科口腔外科」）は
# 分割しない。分割すると「小児歯科・…」が「小児歯科」と「歯科口腔外科」に割れ、
# 歯科側の件数が実態より増えるため。
_SPLIT = re.compile(r"[\s　]+")


def tokenize(subject: str | None) -> list[str]:
    """診療科目の文字列をトークンに分ける。"""
    if not subject:
        return []
    return [t for t in _SPLIT.split(subject.strip()) if t]


# --- 小児科 -----------------------------------------------------------------
# 「小」は病院の略称表記で小児科を指す（小児歯科は「小歯」、小児外科は「小外」と
# 書き分けられている）。小児外科・小児皮膚科などの専門科は、乳幼児を日常的に
# 診てもらう先ではないので小児科には含めない。
PEDIATRIC_TOKENS = frozenset({"小児科", "小", "小児", "小児内科"})

# --- 産科 -------------------------------------------------------------------
# 婦人科だけの施設は出産を扱わないので分けて数える。
OBSTETRIC_TOKENS = frozenset({"産婦人科", "産科", "産婦", "産", "産．婦", "産.婦"})
GYNECOLOGY_TOKENS = frozenset({"婦人科", "婦", "婦人"})

# --- 内科（かかりつけの土台） ----------------------------------------------
INTERNAL_TOKENS = frozenset({"内科", "内", "一般内科"})


def has_specialty(subject: str | None, tokens: frozenset[str]) -> bool:
    """診療科目の文字列に、指定した科がトークンとして含まれるか。"""
    return any(token in tokens for token in tokenize(subject))


# 歯科診療所は、どう書かれていても小児科の受け皿ではない。
# 一部の歯科医院は「小児歯科」を『歯科　小児』のように分けて書くため、
# トークン単位で見ても単独の「小児」が現れる。実データでは単独「小児」を
# 持つ施設の約半数（70/141件）が歯科診療所だった。種別で先に落とすのが確実。
DENTAL_FACILITY_TYPE = "歯科診療所"


def is_pediatric(subject: str | None, facility_type: str | None = None) -> bool:
    if facility_type == DENTAL_FACILITY_TYPE:
        return False
    return has_specialty(subject, PEDIATRIC_TOKENS)


def is_obstetric(subject: str | None, facility_type: str | None = None) -> bool:
    if facility_type == DENTAL_FACILITY_TYPE:
        return False
    return has_specialty(subject, OBSTETRIC_TOKENS)


def is_internal(subject: str | None, facility_type: str | None = None) -> bool:
    if facility_type == DENTAL_FACILITY_TYPE:
        return False
    return has_specialty(subject, INTERNAL_TOKENS)


# 歯科診療所は P04_001_name_ja で分かるが、種別が「診療所」でも歯科しか
# 標榜していない施設があるため、判定用に持っておく。
DENTAL_TOKENS = frozenset(
    {"歯科", "歯", "小児歯科", "小歯", "矯正歯科", "矯歯", "歯科口腔外科", "歯口外"}
)


def is_dental_only(subject: str | None) -> bool:
    """歯科系の科しか標榜していないか。"""
    tokens = tokenize(subject)
    if not tokens:
        return False
    return all(
        token in DENTAL_TOKENS or token.endswith("歯科") or token.startswith("歯")
        for token in tokens
    )
