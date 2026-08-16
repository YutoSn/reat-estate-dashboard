"""Googleマップからコピーした文字列から緯度経度を取り出す。

なぜ必要か
----------
候補地点の登録で緯度と経度を別々の欄に手入力させると、桁を1つ落とす、
緯度と経度を入れ違える、といった間違いが必ず起きる。物件を見ているときに
手元にあるのは Googleマップの画面なので、そこからコピーしたものを
そのまま貼れる形にする。

コピーされてくる形が1つではない
--------------------------------
同じ「位置情報のコピー」でも、どこからコピーしたかで形が変わる。

    右クリック → 座標をクリック   35.906296, 139.623752
    ブラウザのURL               .../maps/@35.906296,139.623752,17z
    地点のURL                   .../maps/place/大宮駅/@35.90,139.62,17z/data=!3d35.906296!4d139.623752
    共有 → リンクをコピー        https://maps.app.goo.gl/xxxxx
    DMS表示                     35°54'22.7"N 139°37'25.5"E

`@` の座標は**地図の中心**であって目的の地点ではない。地点のURLでは
`!3d`（緯度）`!4d`（経度）のほうが目的の地点を指すので、両方あるときは
そちらを優先する。実際 `.../place/大宮駅/@35.9051,139.6240,16z/...!3d35.906296!4d139.623752`
のように、`@` は数百m単位でずれることがある。

短縮URL（maps.app.goo.gl）は展開しないと座標が入っていない。展開には
Googleへの通信が要り、このアプリはどの機能でも外部への実行時アクセスを
持たない方針なので、解決せずに「フルURLか座標を貼ってほしい」と返す。
"""

import re

# 短縮URL。中に座標が無いので、これを見つけたら理由を返して終わる。
SHORT_LINK = re.compile(r"(maps\.app\.goo\.gl|goo\.gl/maps)", re.I)

# 地点そのものの座標。Googleマップの data= パラメータに入る。
PLACE_PAIR = re.compile(r"!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)")

# 地図の中心。URL の @ のあと。
CENTER_PAIR = re.compile(r"@(-?\d+\.\d+),\s*(-?\d+\.\d+)")

# q= / ll= / query= / daddr= に入る座標
PARAM_PAIR = re.compile(
    r"[?&](?:q|ll|query|daddr|destination)=(-?\d+\.\d+),\s*(-?\d+\.\d+)", re.I
)

# 素の「35.906296, 139.623752」。前後に余計な文字が無いものだけを拾う。
# URLの一部を誤って拾わないよう、行全体が座標のときに限る。
PLAIN_PAIR = re.compile(r"^\s*(-?\d+\.?\d*)\s*[,、]\s*(-?\d+\.?\d*)\s*$")

# 度分秒。35°54'22.7"N 139°37'25.5"E
DMS = re.compile(
    r"(\d+)\s*°\s*(\d+)\s*['′]\s*([\d.]+)\s*[\"″]\s*([NSEW北南東西])",
    re.I,
)


class LocationError(ValueError):
    """貼り付けられた文字列から座標を取り出せない。"""


def _dms_to_degrees(degrees: str, minutes: str, seconds: str, hemisphere: str) -> float:
    value = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    return -value if hemisphere.upper() in ("S", "W") or hemisphere in ("南", "西") else value


def _parse_dms(text: str) -> tuple[float, float] | None:
    """度分秒の対を返す。南北→東西の順で書かれている前提。"""
    matches = DMS.findall(text)
    if len(matches) < 2:
        return None
    values = {}
    for degrees, minutes, seconds, hemisphere in matches[:2]:
        axis = "lat" if hemisphere.upper() in ("N", "S") or hemisphere in ("北", "南") else "lon"
        values[axis] = _dms_to_degrees(degrees, minutes, seconds, hemisphere)
    if "lat" not in values or "lon" not in values:
        return None
    return values["lat"], values["lon"]


def parse_location(text: str | None) -> dict[str, object]:
    """貼り付けられた文字列から緯度経度を取り出す。

    戻り値には、どの形として読んだか（source）も入れる。画面で
    「地図の中心を読んだ」のか「地点そのものを読んだ」のかが分かると、
    ずれていたときに気づけるため。
    """
    if not text or not text.strip():
        raise LocationError("位置情報を貼り付けてください")
    raw = text.strip()

    if SHORT_LINK.search(raw):
        raise LocationError(
            "短縮URLには座標が入っていません。"
            "リンクを開いてブラウザのURLをコピーするか、"
            "地図を右クリックして出る座標を貼り付けてください"
        )

    # 地点そのもの > 地図の中心 の順に見る（@ は中心なのでずれることがある）
    for pattern, source in (
        (PLACE_PAIR, "地点の座標"),
        (PARAM_PAIR, "URLの座標"),
        (CENTER_PAIR, "地図の中心"),
    ):
        found = pattern.search(raw)
        if found:
            return {
                "latitude": float(found.group(1)),
                "longitude": float(found.group(2)),
                "source": source,
            }

    dms = _parse_dms(raw)
    if dms:
        return {"latitude": dms[0], "longitude": dms[1], "source": "度分秒"}

    plain = PLAIN_PAIR.match(raw)
    if plain:
        return {
            "latitude": float(plain.group(1)),
            "longitude": float(plain.group(2)),
            "source": "座標",
        }

    raise LocationError(
        "座標を読み取れませんでした。"
        "Googleマップで地図を右クリックして出る「35.906296, 139.623752」の形か、"
        "地図のURLを貼り付けてください"
    )
