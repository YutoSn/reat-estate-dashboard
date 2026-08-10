"""
e-Stat API v3.0 の汎用フェッチャー。

旧 population_api.py / education_api.py は
  - ページネーション（NEXT_KEY）を扱っておらず10万件を超えると黙って欠落する
  - 欠損値記号（"-", "***" 等）を float() に渡して例外で握りつぶしていた
という問題があったため、本モジュールに統合した。
"""

import time
from typing import Any, Iterator

import requests

BASE_URL = "http://api.e-stat.go.jp/rest/3.0/app/json"

# e-Stat が数値の代わりに返す欠損・秘匿記号
MISSING_TOKENS = {"", "-", "***", "*", "X", "x", "…", "－", "NA"}

# 1リクエストあたりの取得上限（APIの上限は10万件）
PAGE_LIMIT = 100_000


class EStatAPI:
    """e-Stat の統計データを指標単位で取得する。"""

    def __init__(self, app_id: str, request_interval: float = 0.4):
        if not app_id:
            raise ValueError("E_STAT_APP_ID が設定されていません")
        self.app_id = app_id
        self.request_interval = request_interval
        self._session = requests.Session()

    def fetch_indicator(self, dataset_id: str, code: str) -> list[dict[str, Any]]:
        """指定した統計表・カテゴリの全レコードをページネーションしながら取得する。"""
        records: list[dict[str, Any]] = []
        start_position: int | None = None

        while True:
            params: dict[str, Any] = {
                "appId": self.app_id,
                "statsDataId": dataset_id,
                "cdCat01": code,
                "limit": PAGE_LIMIT,
            }
            if start_position is not None:
                params["startPosition"] = start_position

            payload = self._get("getStatsData", params)
            stat_data = payload.get("GET_STATS_DATA", {})

            result = stat_data.get("RESULT", {})
            if result.get("STATUS") not in (0, None):
                raise RuntimeError(
                    f"e-Stat エラー ({dataset_id}/{code}): {result.get('ERROR_MSG')}"
                )

            statistical_data = stat_data.get("STATISTICAL_DATA")
            if not statistical_data:
                break

            result_inf = statistical_data.get("RESULT_INF", {})
            if not result_inf.get("TOTAL_NUMBER"):
                break

            values = statistical_data.get("DATA_INF", {}).get("VALUE", [])
            if isinstance(values, dict):
                values = [values]
            records.extend(values)

            next_key = result_inf.get("NEXT_KEY")
            if not next_key:
                break
            start_position = next_key

        return records

    def iter_indicators(
        self, indicators: list[tuple[str, str, str]]
    ) -> Iterator[tuple[str, list[dict[str, Any]]]]:
        """(key, dataset_id, code) のリストを順に取得して (key, records) を返す。"""
        for key, dataset_id, code in indicators:
            records = self.fetch_indicator(dataset_id, code)
            yield key, records

    def fetch_area_names(self, dataset_id: str) -> dict[str, str]:
        """統計表の地域コード -> 地域名（例 "13101" -> "東京都 千代田区"）を取得する。"""
        payload = self._get(
            "getMetaInfo", {"appId": self.app_id, "statsDataId": dataset_id}
        )
        class_objs = (
            payload["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]
        )
        area_obj = next(o for o in class_objs if o["@id"] == "area")
        classes = area_obj.get("CLASS", [])
        if isinstance(classes, dict):
            classes = [classes]
        return {c["@code"]: c.get("@name", "") for c in classes}

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._session.get(
            f"{BASE_URL}/{endpoint}", params=params, timeout=60
        )
        response.raise_for_status()
        # 連続呼び出しでの過負荷を避ける
        time.sleep(self.request_interval)
        return response.json()


def parse_value(raw: Any) -> float | None:
    """e-Stat の観測値を float に変換する。欠損・秘匿記号は None を返す。"""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if text in MISSING_TOKENS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_year(raw: Any) -> int | None:
    """@time（例 "2020100000"）から西暦年を取り出す。"""
    text = str(raw or "")[:4]
    return int(text) if text.isdigit() else None
