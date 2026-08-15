"""候補地点（検討中の物件）を JSON ファイルで持つ。

なぜ DuckDB ではないか
----------------------
`land_price.duckdb` はサーバーが read_only で開いている。populate.py を
動かしながら参照するための前提で、ここは崩せない。候補地点は画面から
追加・編集するので書き込みが要り、同じファイルには入れられない。

読み書き用の DuckDB をもう1つ開く案もあった。採らなかったのは、

* サーバーに書き込み接続が増えると、read_only で通していた前提が濁る
* バイナリなので差分が読めない。候補地点は「いつ何を見て何を思ったか」が
  溜まる場所なので、履歴が追える形のほうが用途に合う
* リポジトリにコミットすれば、再デプロイやマシン移行をまたいで残る。
  DuckDB ファイルは .gitignore の対象で（land_price.duckdb だけが例外）、
  コミット運用に乗せにくい

書き込みの壊れ方
----------------
保存は一時ファイルに書いてから `os.replace` で差し替える。途中で落ちても
元のファイルが半端な状態にならないようにするため。1人で使う道具なので
排他制御は入れていない。複数プロセスから同時に書けば後勝ちになる。
"""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from config import CANDIDATES_FILE, SITE_MODEL

# 保存する項目。ここに無いキーは受け取っても捨てる。
# 画面の入力欄が増えたときに、意図しない値がそのまま入るのを防ぐ。
TEXT_FIELDS = ("name", "address", "municipality_code", "district", "url", "notes")
NUMBER_FIELDS = ("price", "land_area", "building_area")


class ValidationError(ValueError):
    """入力が保存できる形になっていない。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_statuses() -> set[str]:
    return {s["key"] for s in SITE_MODEL["statuses"]}


def _coerce_number(value: Any, label: str) -> float | None:
    """空欄は None のまま通す。物件によっては面積が分からないことがある。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label}は数値で入れてください")
    if number < 0:
        raise ValidationError(f"{label}に負の数は入れられません")
    return number


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    """入力を保存できる形に整える。壊れていれば ValidationError。"""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationError("呼び名を入れてください")

    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("緯度と経度を数値で入れてください")

    # 緯度経度の取り違え（35.68 と 139.76 を逆に入れる）は起こりやすいので、
    # 対象都県のおおよその範囲から外れていたら弾く。
    lat_min, lat_max = SITE_MODEL["latitude_range"]
    lon_min, lon_max = SITE_MODEL["longitude_range"]
    if not lat_min <= latitude <= lat_max:
        raise ValidationError(f"緯度が対象範囲（{lat_min}〜{lat_max}）の外です")
    if not lon_min <= longitude <= lon_max:
        raise ValidationError(f"経度が対象範囲（{lon_min}〜{lon_max}）の外です")

    # 市区町村は登録時に選ばせる。代表点への最近傍で決めない。
    # 代表点は1市区町村1点しかなく、市境の物件は隣の市に寄るため
    # （駅の所在地判定が町丁目107,758点を要したのと同じ理由）。
    municipality_code = str(payload.get("municipality_code") or "").strip()
    if not municipality_code:
        raise ValidationError("市区町村を選んでください")

    status = str(payload.get("status") or SITE_MODEL["default_status"])
    if status not in _valid_statuses():
        raise ValidationError(f"status が不正です: {status}")

    record: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "status": status,
    }
    for field in TEXT_FIELDS:
        record[field] = str(payload.get(field) or "").strip()
    record["name"] = name
    record["municipality_code"] = municipality_code
    for field in NUMBER_FIELDS:
        record[field] = _coerce_number(payload.get(field), field)
    return record


class CandidateStore:
    """候補地点の読み書き。"""

    def __init__(self, path: str = CANDIDATES_FILE):
        self.path = path

    def load(self) -> list[dict[str, Any]]:
        """保存済みの候補地点。ファイルが無ければ空。

        壊れた JSON は例外にせず空で返す。手で編集して壊したときに
        アプリ全体が起動しなくなるより、画面が空になるほうが直しやすい。
        """
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return []
        return data.get("sites", []) if isinstance(data, dict) else []

    def _save(self, sites: list[dict[str, Any]]) -> None:
        """一時ファイルに書いてから差し替える。途中で落ちても壊れないように。"""
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {"sites": sites}
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(handle.name, self.path)
        except BaseException:
            if os.path.exists(handle.name):
                os.unlink(handle.name)
            raise

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = validate(payload)
        record["id"] = uuid.uuid4().hex[:12]
        record["created_at"] = _now()
        record["updated_at"] = record["created_at"]
        sites = self.load()
        sites.append(record)
        self._save(sites)
        return record

    def update(self, site_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """既存の地点を差し替える。見つからなければ None。"""
        sites = self.load()
        for index, site in enumerate(sites):
            if site.get("id") != site_id:
                continue
            # 部分更新（メモだけ書き換える等）を許すため、既存値に重ねてから通す
            merged = {**site, **payload}
            record = validate(merged)
            record["id"] = site_id
            record["created_at"] = site.get("created_at") or _now()
            record["updated_at"] = _now()
            sites[index] = record
            self._save(sites)
            return record
        return None

    def remove(self, site_id: str) -> bool:
        sites = self.load()
        remaining = [s for s in sites if s.get("id") != site_id]
        if len(remaining) == len(sites):
            return False
        self._save(remaining)
        return True
