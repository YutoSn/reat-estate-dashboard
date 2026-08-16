"""Plus Code（Open Location Code）を座標に直す。

なぜ自前で持つか
----------------
スマホのGoogleマップは、地点の詳細に Plus Code を出す。これは長押しで座標を
出すより見つけやすく、共有リンクと違って**文字列そのものに位置が入っている**。
つまり外部への問い合わせなしに座標へ戻せる。候補地点の登録で一番あてになる
入力経路なので、通信の要らない解き方をここに持つ。

pip の openlocationcode を入れてもよいが、必要なのは復号だけで100行に満たない。
その代わり、実装を勘で書かないために **Google公式のテストベクタ**
（tests/data/open_location_code/）を丸ごと通す。仕様を覚えている自信ではなく、
公式データが通ることを根拠にする。

スマホから来る2つの形
---------------------
    フル      8Q7XWJ4F+GG          単体で世界のどこかに決まる
    短縮      WJ4F+GG さいたま市    近くの地名とセットでないと決まらない

短縮形は先頭が削られている。削られた分は「参照地点の同じ桁」で補い、
補った結果が参照地点から一番近い候補になるようずらす（recoverNearest）。
Googleマップのアプリが出すのはたいていこの短縮形で、後ろに地名が付く。
"""

# 公式仕様の定数。名前は参照実装に合わせてある。
ALPHABET = "23456789CFGHJMPQRVWX"
BASE = len(ALPHABET)
SEPARATOR = "+"
SEPARATOR_POSITION = 8
PADDING = "0"

PAIR_CODE_LENGTH = 10
MAX_DIGIT_COUNT = 15

LATITUDE_MAX = 90
LONGITUDE_MAX = 180

# 5桁ぶんの対（=10文字）で 1/8000 度まで刻める。
PAIR_PRECISION = BASE**3  # 8000
PAIR_FIRST_PLACE_VALUE = BASE ** (PAIR_CODE_LENGTH // 2 - 1)  # 8000

# 10文字を超えたぶんは格子。1文字が縦5×横4の升目を指す。
GRID_ROWS = 5
GRID_COLUMNS = 4
GRID_CODE_LENGTH = MAX_DIGIT_COUNT - PAIR_CODE_LENGTH  # 5
GRID_LAT_FIRST_PLACE_VALUE = GRID_ROWS ** (GRID_CODE_LENGTH - 1)
GRID_LNG_FIRST_PLACE_VALUE = GRID_COLUMNS ** (GRID_CODE_LENGTH - 1)
FINAL_LAT_PRECISION = PAIR_PRECISION * GRID_ROWS**GRID_CODE_LENGTH
FINAL_LNG_PRECISION = PAIR_PRECISION * GRID_COLUMNS**GRID_CODE_LENGTH


class PlusCodeError(ValueError):
    """Plus Code として読めない、または情報が足りない。"""


def is_valid(code: str) -> bool:
    """公式の validity 判定。区切りと詰め文字の位置に細かい決まりがある。"""
    if not isinstance(code, str) or code.count(SEPARATOR) != 1:
        return False
    # 区切りだけの "+" は場所を持たない。
    if len(code) == 1:
        return False

    index = code.find(SEPARATOR)
    if index > SEPARATOR_POSITION or index % 2 == 1:
        return False

    if PADDING in code:
        # 詰め文字は「粗いフルコード」専用。短縮形には付けられない。
        if index < SEPARATOR_POSITION:
            return False
        if code.startswith(PADDING):
            return False
        # 1か所にまとまっていて、偶数個で、区切りの直前で終わること。
        run_start = code.find(PADDING)
        run_end = code.rfind(PADDING) + 1
        run = code[run_start:run_end]
        if run.strip(PADDING) or len(run) % 2 == 1 or len(run) > SEPARATOR_POSITION - 2:
            return False
        if not code.endswith(SEPARATOR):
            return False

    # 区切りのあとは無し、もしくは2文字以上。1文字だけは中途半端で許さない。
    if len(code) - index - 1 == 1:
        return False

    return all(
        character.upper() in ALPHABET or character in (SEPARATOR, PADDING)
        for character in code
    )


def is_short(code: str) -> bool:
    """先頭が削られている（=参照地点が要る）か。"""
    if not is_valid(code):
        return False
    index = code.find(SEPARATOR)
    return 0 <= index < SEPARATOR_POSITION


def is_full(code: str) -> bool:
    """単体で場所が決まるか。"""
    if not is_valid(code) or is_short(code):
        return False

    # 先頭の1文字は緯度、2文字目は経度の一番大きい桁。範囲外を弾く。
    first_latitude = ALPHABET.index(code[0].upper()) * BASE
    if first_latitude >= LATITUDE_MAX * 2:
        return False
    if len(code) > 1:
        first_longitude = ALPHABET.index(code[1].upper()) * BASE
        if first_longitude >= LONGITUDE_MAX * 2:
            return False
    return True


def _clean(code: str) -> str:
    """区切りと詰め文字を落として、桁だけの並びにする。"""
    return code.replace(SEPARATOR, "").rstrip(PADDING).upper()


def decode(code: str) -> dict[str, float]:
    """フルコードを矩形として返す。中心も一緒に返す。

    整数で足してから最後に割る。度のまま掛け算を重ねると下の桁が
    ずれ、公式テストベクタの厳密比較に落ちるため。
    """
    if not is_full(code):
        raise PlusCodeError(f"フルコードではありません: {code}")

    digits = _clean(code)

    # 対の部分（最大10文字）。単位は 1/8000 度。
    latitude = -LATITUDE_MAX * PAIR_PRECISION
    longitude = -LONGITUDE_MAX * PAIR_PRECISION
    pair_digits = min(len(digits), PAIR_CODE_LENGTH)
    place_value = PAIR_FIRST_PLACE_VALUE
    for index in range(0, pair_digits, 2):
        latitude += ALPHABET.index(digits[index]) * place_value
        longitude += ALPHABET.index(digits[index + 1]) * place_value
        if index < pair_digits - 2:
            place_value //= BASE
    latitude_low = latitude / PAIR_PRECISION
    longitude_low = longitude / PAIR_PRECISION
    latitude_size = place_value / PAIR_PRECISION
    longitude_size = place_value / PAIR_PRECISION

    # 格子の部分（11文字目以降）。刻みが縦横で違うので別々に持つ。
    if len(digits) > PAIR_CODE_LENGTH:
        row_value = 0
        column_value = 0
        row_place = GRID_LAT_FIRST_PLACE_VALUE
        column_place = GRID_LNG_FIRST_PLACE_VALUE
        grid_digits = min(len(digits), MAX_DIGIT_COUNT)
        for index in range(PAIR_CODE_LENGTH, grid_digits):
            digit = ALPHABET.index(digits[index])
            row_value += (digit // GRID_COLUMNS) * row_place
            column_value += (digit % GRID_COLUMNS) * column_place
            if index < grid_digits - 1:
                row_place //= GRID_ROWS
                column_place //= GRID_COLUMNS
        latitude_low += row_value / FINAL_LAT_PRECISION
        longitude_low += column_value / FINAL_LNG_PRECISION
        latitude_size = row_place / FINAL_LAT_PRECISION
        longitude_size = column_place / FINAL_LNG_PRECISION

    latitude_high = min(latitude_low + latitude_size, LATITUDE_MAX)
    longitude_high = min(longitude_low + longitude_size, LONGITUDE_MAX)
    return {
        "latitude_low": latitude_low,
        "longitude_low": longitude_low,
        "latitude_high": latitude_high,
        "longitude_high": longitude_high,
        "latitude": (latitude_low + latitude_high) / 2,
        "longitude": (longitude_low + longitude_high) / 2,
        "code_length": min(len(digits), MAX_DIGIT_COUNT),
    }


def encode(latitude: float, longitude: float, code_length: int = PAIR_CODE_LENGTH) -> str:
    """座標をコードにする。短縮形を戻すときの先頭合わせに要る。"""
    if code_length < 2 or (code_length < PAIR_CODE_LENGTH and code_length % 2 == 1):
        raise PlusCodeError(f"桁数が不正です: {code_length}")
    code_length = min(code_length, MAX_DIGIT_COUNT)

    latitude = min(max(latitude, -LATITUDE_MAX), LATITUDE_MAX)
    # 東経180度は西経180度と同じ場所。剰余で書くと 180 が 180 のまま残るので回す。
    while longitude < -LONGITUDE_MAX:
        longitude += 360
    while longitude >= LONGITUDE_MAX:
        longitude -= 360

    # 北緯90度ちょうどは升目の外に出るので、1升ぶん南に寄せる。
    if latitude == LATITUDE_MAX:
        latitude -= _precision_for(code_length) / 2

    latitude_value = int(round((latitude + LATITUDE_MAX) * FINAL_LAT_PRECISION, 6))
    longitude_value = int(round((longitude + LONGITUDE_MAX) * FINAL_LNG_PRECISION, 6))
    latitude_value = min(latitude_value, 2 * LATITUDE_MAX * FINAL_LAT_PRECISION - 1)

    characters = [""] * MAX_DIGIT_COUNT
    for index in range(GRID_CODE_LENGTH - 1, -1, -1):
        digit = (latitude_value % GRID_ROWS) * GRID_COLUMNS + (longitude_value % GRID_COLUMNS)
        characters[PAIR_CODE_LENGTH + index] = ALPHABET[digit]
        latitude_value //= GRID_ROWS
        longitude_value //= GRID_COLUMNS
    for index in range(PAIR_CODE_LENGTH // 2 - 1, -1, -1):
        characters[index * 2] = ALPHABET[latitude_value % BASE]
        characters[index * 2 + 1] = ALPHABET[longitude_value % BASE]
        latitude_value //= BASE
        longitude_value //= BASE

    code = "".join(characters)
    if code_length < SEPARATOR_POSITION:
        return code[:code_length] + PADDING * (SEPARATOR_POSITION - code_length) + SEPARATOR
    return code[:SEPARATOR_POSITION] + SEPARATOR + code[SEPARATOR_POSITION:code_length]


def _precision_for(code_length: int) -> float:
    """その桁数での升目の大きさ（緯度方向）。"""
    if code_length <= PAIR_CODE_LENGTH:
        return BASE ** (code_length // -2 + 2)
    return BASE**-3 / GRID_ROWS ** (code_length - PAIR_CODE_LENGTH)


def recover_nearest(code: str, reference_latitude: float, reference_longitude: float) -> str:
    """短縮コードに参照地点の先頭を足して、一番近い候補を選ぶ。

    足しただけだと升目の境目で隣を指すことがある。参照地点から見て
    半升より遠い側に出てしまったら、1升ぶん戻す。
    """
    if not is_short(code):
        if is_full(code):
            return code.upper()
        raise PlusCodeError(f"Plus Code として読めません: {code}")

    code = code.upper()
    reference_latitude = min(max(reference_latitude, -LATITUDE_MAX), LATITUDE_MAX)

    padding_length = SEPARATOR_POSITION - code.find(SEPARATOR)
    resolution = BASE ** (2 - (padding_length / 2))
    half = resolution / 2.0

    prefix = encode(reference_latitude, reference_longitude)[:padding_length]
    area = decode(prefix + code)
    latitude = area["latitude"]
    longitude = area["longitude"]

    if reference_latitude + half < latitude and latitude - resolution >= -LATITUDE_MAX:
        latitude -= resolution
    elif reference_latitude - half > latitude and latitude + resolution <= LATITUDE_MAX:
        latitude += resolution

    if reference_longitude + half < longitude:
        longitude -= resolution
    elif reference_longitude - half > longitude:
        longitude += resolution

    return encode(latitude, longitude, area["code_length"])
