"""国土交通省 不動産情報ライブラリ XIT001（不動産取引価格情報）の取得と正規化。

旧実装は TradePrice / Area / MunicipalityCode など数フィールドしか保存せず、
取引種別（Type）を落としていた。そのため「宅地(土地)」「宅地(土地と建物)」
「中古マンション等」が混ざったまま 取引価格÷面積 を単価として扱っており、
マンションの専有単価と土地単価が合算される状態になっていた。

ここでは種別・地域区分・APIが直接返す㎡単価（UnitPrice）を保持する。
"""

import time
from typing import Any

import requests

BASE_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external"

# APIが「一定面積以上」をまとめて返す丸め値。単価計算に使うと単価が潰れる。
MASKED_AREA_VALUES = {2000.0, 5000.0, 8888.0, 9999.0}


class RealEstateLibraryAPI:
    """不動産取引価格情報を都道府県×年で取得する。"""

    def __init__(self, api_key: str, request_interval: float = 0.3):
        if not api_key:
            raise ValueError("REAL_ESTATE_LIBRARY_API_KEY が設定されていません")
        self.api_key = api_key
        self.request_interval = request_interval
        self._session = requests.Session()
        self._session.headers.update({"Ocp-Apim-Subscription-Key": api_key})

    def fetch_year(self, pref_code: str, year: int) -> list[dict[str, Any]]:
        """指定した都道府県・年の取引を取得して正規化済みレコードで返す。"""
        response = self._session.get(
            f"{BASE_URL}/XIT001",
            params={"year": str(year), "area": pref_code},
            timeout=120,
        )
        response.raise_for_status()
        time.sleep(self.request_interval)

        payload = response.json()
        raw_records = payload.get("data") or []
        return [normalize_record(record) for record in raw_records]


def _to_float(raw: Any) -> float | None:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(raw: Any) -> int | None:
    value = _to_float(raw)
    return int(value) if value is not None else None


def _parse_building_year(raw: Any) -> int | None:
    """"1982年" -> 1982。"戦前" は年が特定できないため None。"""
    text = str(raw or "").strip()
    if not text or text == "戦前":
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    return year if 1800 <= year <= 2100 else None


def _parse_period(raw: Any) -> tuple[int | None, int | None]:
    """"2023年第2四半期" -> (2023, 2)。"""
    text = str(raw or "")
    year: int | None = None
    quarter: int | None = None

    if "年" in text:
        head = text.split("年", 1)[0]
        if head.isdigit():
            year = int(head)
    if "第" in text and "四半期" in text:
        mid = text.split("第", 1)[1].split("四半期", 1)[0]
        if mid.isdigit():
            quarter = int(mid)
    return year, quarter


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """XIT001 の1レコードを DB スキーマに合わせて正規化する。"""
    trade_year, quarter = _parse_period(record.get("Period"))
    area = _to_float(record.get("Area"))

    return {
        "trade_year": trade_year,
        "quarter": quarter,
        "period": record.get("Period") or None,
        "type": record.get("Type") or None,
        "region": record.get("Region") or None,
        "municipality_code": str(record.get("MunicipalityCode") or "").zfill(5),
        "prefecture": record.get("Prefecture") or None,
        "municipality": record.get("Municipality") or None,
        "district_name": record.get("DistrictName") or None,
        "district_code": record.get("DistrictCode") or None,
        "trade_price": _to_float(record.get("TradePrice")),
        "unit_price": _to_float(record.get("UnitPrice")),
        "price_per_tsubo": _to_float(record.get("PricePerUnit")),
        "area": area,
        "area_is_masked": area in MASKED_AREA_VALUES if area is not None else False,
        "total_floor_area": _to_float(record.get("TotalFloorArea")),
        "building_year": _parse_building_year(record.get("BuildingYear")),
        "structure": record.get("Structure") or None,
        "use_purpose": record.get("Use") or None,
        "purpose": record.get("Purpose") or None,
        "city_planning": record.get("CityPlanning") or None,
        "coverage_ratio": _to_float(record.get("CoverageRatio")),
        "floor_area_ratio": _to_float(record.get("FloorAreaRatio")),
        "frontage": _to_float(record.get("Frontage")),
        "land_shape": record.get("LandShape") or None,
        "renovation": record.get("Renovation") or None,
    }
