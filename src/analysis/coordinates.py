"""スマホから手に入る位置情報を緯度経度に直す。

なぜ必要か
----------
候補地点の登録で緯度と経度を別々の欄に手入力させると、桁を1つ落とす、
緯度と経度を入れ違える、といった間違いが必ず起きる。物件を見ているときに
手元にあるのはスマホのGoogleマップなので、そこから取れるものをそのまま
貼れる形にする。

スマホのGoogleマップから実際に取れるもの
----------------------------------------
アプリの共有メニューが出すのは短縮URLで、文字列の中に座標が入っていない。
「リンクをコピーしたのに座標が出ない」のはこれが理由。取れる順に:

    共有→リンクをコピー   https://maps.app.goo.gl/xxxxx   → 展開して座標を得る（通信あり）
    地点の詳細の Plus Code  WJ4F+GG さいたま市              → その場で計算できる（通信なし）
    ピンを長押し→座標      35.906296, 139.623752          → そのまま
    地名・駅名             大宮駅                          → 手元の索引で引く（通信なし）
    ブラウザ版のURL        .../maps/place/…/@…/data=!3d…!4d… → そのまま

通信が要るのは短縮URLの展開だけ。それ以外は手元で完結するので、
現地の電波が悪くても使える。短縮URLも、展開できなければ Plus Code を
使うよう案内して終わる（黙って近くの点を返さない）。

`@` と `!3d/!4d` の違い
-----------------------
`@` は**地図の中心**であって目的の地点ではない。地点のURLでは `!3d`（緯度）
`!4d`（経度）が目的の地点を指すので、両方あるときはそちらを優先する。
`.../place/大宮駅/@35.9051,139.6240,16z/...!3d35.906296!4d139.623752` のように
`@` は数百m単位でずれることがある。

読み取れなかったときに「近そうな点」を返さない
----------------------------------------------
住所しか無いときに市の代表点で代用すると、数km離れた座標が正しい顔で
返ってくる。半径2kmの周辺照会がそのまま狂うので、引けないものは
引けないと返す。
"""

import re

from src.analysis.place_index import PlaceIndex, PlaceNotFound, describe
from src.analysis.plus_code import PlusCodeError, decode, is_full, is_short, recover_nearest
from src.analysis.reverse_geocode import municipality_for

# 短縮URL。中に座標が無いので、展開しないと読めない。
SHORT_LINK = re.compile(r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps)/\S+", re.I)

# 地点そのものの座標。Googleマップの data= パラメータに入る。
PLACE_PAIR = re.compile(r"!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)")

# 地図の中心。URL の @ のあと。
CENTER_PAIR = re.compile(r"@(-?\d+\.\d+),\s*(-?\d+\.\d+)")

# q= / ll= / query= / daddr= に入る座標
PARAM_PAIR = re.compile(
    r"[?&](?:q|ll|query|daddr|destination)=(-?\d+\.\d+),\s*(-?\d+\.\d+)", re.I
)

# 素の「35.906296, 139.623752」。行全体が座標のときに限る。
PLAIN_PAIR = re.compile(r"^\s*(-?\d+\.?\d*)\s*[,、]\s*(-?\d+\.?\d*)\s*$")

# 度分秒。35°54'22.7"N 139°37'25.5"E
DMS = re.compile(
    r"(\d+)\s*°\s*(\d+)\s*['′]\s*([\d.]+)\s*[\"″]\s*([NSEW北南東西])",
    re.I,
)

# Plus Code。「WJ4F+GG さいたま市大宮区」のように後ろに地名が付く形も拾う。
# 区切りの前は2〜8文字、後ろは2文字以上。
PLUS_CODE = re.compile(r"\b([23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{2,3})\b", re.I)

# 日本の陸域からおおよそ外れたら、緯度経度の入れ違いを疑う。
JAPAN_LATITUDE = (20.0, 46.5)
JAPAN_LONGITUDE = (122.0, 154.0)

_places = PlaceIndex()


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


def _result(latitude: float, longitude: float, source: str, **extra) -> dict:
    result = {"latitude": latitude, "longitude": longitude, "source": source}
    # 場所が決まればその市区町村も決まっている。人に選び直させない。
    # 決められないときは入れない（間違った市区町村が静かに保存されるより、
    # プルダウンが空のままのほうがよい）。
    found = municipality_for(latitude, longitude)
    if found:
        result["municipality_code"] = found["municipality_code"]
    # 日本の外に出たら、緯度経度が逆に貼られた可能性を添える。黙って通すと
    # 周辺照会が0件になるだけで、原因が分からない。
    if not (
        JAPAN_LATITUDE[0] <= latitude <= JAPAN_LATITUDE[1]
        and JAPAN_LONGITUDE[0] <= longitude <= JAPAN_LONGITUDE[1]
    ):
        result["warning"] = (
            "日本の範囲から外れています。緯度と経度が入れ違っていないか確認してください"
        )
    result.update(extra)
    return result


def _parse_plus_code(raw: str) -> dict | None:
    """Plus Code を探して座標にする。

    短縮形は先頭が削られているので、後ろに書かれた地名を参照地点にする。
    地名が無い、または引けないときは、参照地点が決められないので諦める
    （見当で近くの市を当てると、隣の升目を指しても気づけない）。
    """
    found = PLUS_CODE.search(raw)
    if not found:
        return None
    code = found.group(1).upper()

    if is_full(code):
        area = decode(code)
        return _result(area["latitude"], area["longitude"], "Plus Code")

    if not is_short(code):
        return None

    # コードの前後に残った文字を地名とみなす（「WJ4F+GG さいたま市大宮区」）。
    remainder = (raw[: found.start(1)] + " " + raw[found.end(1) :]).strip()
    if not remainder:
        raise LocationError(
            "Plus Code が短縮形です。"
            f"「{code} さいたま市大宮区」のように、"
            "Googleマップに一緒に表示されている地名も含めて貼り付けてください"
        )

    try:
        reference = _places.best(remainder)
    except PlaceNotFound:
        raise LocationError(
            f"Plus Code に付いている「{remainder}」の場所が分かりませんでした。"
            "市区町村名か駅名に直すか、フルの Plus Code を貼り付けてください"
        ) from None

    try:
        full = recover_nearest(code, reference["latitude"], reference["longitude"])
    except PlusCodeError as error:
        raise LocationError(f"Plus Code を読み取れませんでした: {error}") from None

    area = decode(full)
    return _result(
        area["latitude"],
        area["longitude"],
        "Plus Code",
        detail=f"{describe(reference)} を基準に復元",
    )


def _parse_coordinates(raw: str) -> dict | None:
    """URL・座標・度分秒から座標を取り出す。地名や Plus Code は見ない。"""
    # 地点そのもの > URLの座標 > 地図の中心 の順（@ は中心なのでずれる）
    for pattern, source in (
        (PLACE_PAIR, "地点の座標"),
        (PARAM_PAIR, "URLの座標"),
        (CENTER_PAIR, "地図の中心"),
    ):
        found = pattern.search(raw)
        if found:
            return _result(float(found.group(1)), float(found.group(2)), source)

    dms = _parse_dms(raw)
    if dms:
        return _result(dms[0], dms[1], "度分秒")

    plain = PLAIN_PAIR.match(raw)
    if plain:
        return _result(float(plain.group(1)), float(plain.group(2)), "座標")

    return None


def _parse_place_name(raw: str) -> dict | None:
    """地名・駅名で引く。市区町村は代表点なので、そうと分かる形で返す。"""
    candidates = _places.search(raw)
    if not candidates:
        return None
    best = candidates[0]
    others = [
        {
            "label": describe(entry),
            "latitude": entry["latitude"],
            "longitude": entry["longitude"],
            # 候補を選び直したときも市区町村が追随するように持たせる。
            "municipality_code": entry["municipality_code"],
        }
        for entry in candidates[1:]
    ]
    return _result(
        best["latitude"],
        best["longitude"],
        describe(best),
        detail=(
            "市区町村の代表点です。物件の位置とは数km離れることがあります"
            if best["kind"] != "駅"
            else None
        ),
        alternatives=others,
    )


def expand_short_link(url: str, fetch=None) -> str:
    """短縮URLを展開して、行き先のURLを返す。

    ここだけは外部（Google）への通信が要る。スマホの共有リンクは
    これを解かないと座標が取れず、「リンクを貼っても駄目」という
    一番よくある詰まり方の原因になるので、例外的に許す。

    fetch を差し替えられるようにしてあるのは、テストで実際に
    Googleへ出て行かないようにするため。
    """
    if fetch is None:
        fetch = _default_fetch
    destination = fetch(url)
    if not destination:
        raise LocationError(
            "短縮URLを展開できませんでした。"
            "リンクを一度ブラウザで開いてそのURLを貼り付けるか、"
            "地点の Plus Code（例: WJ4F+GG さいたま市大宮区）を貼り付けてください"
        )
    return destination


def _default_fetch(url: str) -> str | None:
    """リダイレクト先だけを見る。本文は要らないので取りに行かない。"""
    import requests

    try:
        response = requests.head(url, allow_redirects=True, timeout=8)
        # HEAD を受けない場合があるので、そのときだけ GET で追う。
        if response.status_code >= 400 or not response.url or response.url == url:
            response = requests.get(url, allow_redirects=True, timeout=8, stream=True)
            response.close()
        return response.url
    except Exception:
        # 圏外・遮断・タイムアウトはすべて「展開できなかった」に畳む。
        # 呼び出し側は Plus Code を案内すればよく、原因の別は要らない。
        return None


def parse_location(text: str | None, fetch=None) -> dict[str, object]:
    """貼り付けられた文字列から座標を取り出す。

    戻り値には、どの形として読んだか（source）も入れる。「地図の中心を
    読んだ」のか「地点そのものを読んだ」のかが分かると、ずれていたときに
    気づけるため。

    見る順番には理由がある。Plus Code を座標より先に見るのは、
    「WJ4F+GG さいたま市」に数字が含まれないので取り違えないから。
    地名は最後に見る。URLや座標の中の文字列がたまたま駅名に当たると、
    まったく違う場所を返してしまうため。
    """
    if not text or not text.strip():
        raise LocationError("位置情報を貼り付けてください")
    raw = text.strip()

    # 短縮URLは、展開してから同じ手順にかける。
    short = SHORT_LINK.search(raw)
    if short:
        expanded = expand_short_link(short.group(0), fetch=fetch)
        found = _parse_coordinates(expanded)
        if found:
            found["source"] = f"共有リンク（{found['source']}）"
            return found
        raise LocationError(
            "短縮URLは開けましたが、その先に座標が入っていませんでした。"
            "地点の Plus Code（例: WJ4F+GG さいたま市大宮区）を貼り付けてください"
        )

    plus = _parse_plus_code(raw)
    if plus:
        return plus

    found = _parse_coordinates(raw)
    if found:
        return found

    place = _parse_place_name(raw)
    if place:
        return place

    raise LocationError(
        "位置を読み取れませんでした。次のいずれかを貼り付けてください: "
        "Plus Code（例: WJ4F+GG さいたま市大宮区）、"
        "座標（例: 35.906296, 139.623752）、駅名（例: 大宮駅）、"
        "Googleマップの共有リンク"
    )


def search_places(query: str, limit: int = 8) -> list[dict]:
    """地名の候補だけを返す。検索欄の候補表示用。"""
    return [
        {
            "label": describe(entry),
            "name": entry["name"],
            "kind": entry["kind"],
            "municipality_code": entry["municipality_code"],
            "latitude": entry["latitude"],
            "longitude": entry["longitude"],
        }
        for entry in _places.search(query, limit=limit)
    ]
