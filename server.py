"""家を建てる場所を選ぶためのダッシュボード API。"""

import functools
import os
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import (
    BALANCE_MODEL,
    BUDGET_MODEL,
    DUCKDB_FILE,
    REGIONAL_HUBS,
    STATS_HISTORY_YEARS,
    TARGET_PREFECTURE_CODES,
    TOKYO_CENTER,
    current_year,
    stage_years,
)
from src.analysis.geo import access_for
from src.analysis.metrics import (
    MIN_PRICE_DEALS,
    derive_metrics,
    latest_value,
    project_child_population,
)
from src.analysis.scoring import (
    DIMENSIONS,
    METRIC_SPECS,
    metric_catalog,
    metric_ranks,
    score_breakdown,
)
from src.db.duckdb_manager import DuckDBManager
from src.indicators import INDICATOR_BY_KEY, STALE_INDICATORS

load_dotenv()
API_KEY = os.getenv("REAL_ESTATE_LIBRARY_API_KEY")

app = FastAPI(title="住まい選びダッシュボード")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# サーバーは参照しかしないので読み取り専用で開く。
# 書き込み用に開くと populate.py と同時に動かせず、複数ワーカーでも競合する。
db = DuckDBManager(DUCKDB_FILE, read_only=True)


def _clean(value: Any) -> Any:
    """NaN や numpy 型を JSON に載る形へ落とす。"""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return [
        {key: _clean(value) for key, value in row.items()}
        for row in df.to_dict("records")
    ]


def _price_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """価格推移に、集計途中の年かどうかの印をつける。

    国交省の取引データは四半期ごとに追加されるため、進行中の年は件数が
    数分の一しかない。そのまま折れ線にすると年末に向けて急落したように
    見えるので、フロント側で区別できるようにしておく。
    """
    records = _records(df)
    this_year = current_year()
    for record in records:
        record["is_partial"] = record.get("year") == this_year
    return records


# --------------------------------------------------------------- メタ情報
@app.get("/api/meta")
def get_meta():
    """指標カタログ・観点の定義・子どもの成長タイムライン。"""
    return {
        "dimensions": [
            {"key": key, **value} for key, value in DIMENSIONS.items()
        ],
        "metrics": metric_catalog(),
        "stages": stage_years(),
        "indicators": [
            {
                "key": ind.key,
                "label": ind.label,
                "unit": ind.unit,
                "group": ind.group,
                "is_stale": ind.key in STALE_INDICATORS,
            }
            for ind in INDICATOR_BY_KEY.values()
        ],
        # 世帯年収から予算を出すときの前提。フロントはここを唯一の定義として使う。
        "budget_model": BUDGET_MODEL,
        "balance_model": BALANCE_MODEL,
        "access": {
            "tokyo_center": TOKYO_CENTER[0],
            "hubs": [name for name, _, _ in REGIONAL_HUBS],
        },
        "current_year": current_year(),
    }


@app.get("/api/prefectures")
def get_prefectures():
    prefectures = db.get_prefectures()
    if prefectures:
        return prefectures
    # マスタ未投入時のフォールバック
    return [{"code": code, "name": code} for code in TARGET_PREFECTURE_CODES]


@app.get("/api/cities/{pref_code}")
def get_cities(pref_code: str):
    return db.get_cities(pref_code)


@app.get("/api/districts/{city_code}")
def get_districts(city_code: str):
    return db.get_districts(city_code)


# ------------------------------------------------------------ 市区町村詳細
@app.get("/api/municipality/{city_code}")
def get_municipality(city_code: str):
    """1市区町村のプロフィール一式。"""
    info = db.get_municipality(city_code)
    if info is None:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")

    stats = db.get_stats(city_code)
    price_trend = db.get_price_trend(city_code)

    price_latest = db.get_latest_land_price_by_city(years=3)
    unit_price = None
    deals = None
    if not price_latest.empty:
        row = price_latest[price_latest["municipality_code"] == city_code]
        if not row.empty:
            unit_price = _clean(row.iloc[0]["land_unit_price"])
            deals = _clean(row.iloc[0]["deals"])

    # 土地面積の中央値は予算計算の土台になるので、スコア側と同じ件数条件で採る
    land_area = db.get_land_area_by_city(years=10)
    area_median = None
    if not land_area.empty:
        row = land_area[
            (land_area["municipality_code"] == city_code)
            & (land_area["deals"] >= MIN_PRICE_DEALS)
        ]
        if not row.empty:
            area_median = _clean(row.iloc[0]["land_area_median"])

    metrics = derive_metrics(
        stats,
        land_unit_price=unit_price,
        land_area_median=area_median,
        land_deals=deals,
        access=access_for(city_code),
        reference_year=current_year(),
    )
    observation_years = metrics.pop("_years", {})
    extra_inputs = metrics.pop("_extra_inputs", {})

    # 統計の推移（表示年数を絞る）
    cutoff = current_year() - STATS_HISTORY_YEARS
    trend = stats[stats.index >= cutoff] if not stats.empty else pd.DataFrame()
    trend_records = []
    if not trend.empty:
        for year, row in trend.iterrows():
            record = {"year": int(year)}
            record.update({k: _clean(v) for k, v in row.items()})
            trend_records.append(record)

    scores = _scores_for(city_code)

    # 各指標の計算に使った統計値を、観測年つきでそのまま返す。
    # 「住環境が低いのはなぜか」を、指標 → 元の統計値までたどれるようにするため。
    input_keys = {key for spec in METRIC_SPECS for key in spec.inputs}
    input_values = {
        key: latest_value(stats, key, reference_year=current_year())
        for key in input_keys
    }

    return {
        "municipality": {k: _clean(v) for k, v in info.items()},
        "metrics": {k: _clean(v) for k, v in metrics.items()},
        "observation_years": observation_years,
        "scores": scores,
        "score_breakdown": score_breakdown(
            metrics, scores, input_values, _metric_ranks(), city_code,
            extra_inputs=extra_inputs,
        ),
        "stats_trend": trend_records,
        "price_trend": _price_records(price_trend),
        "child_projection": project_child_population(
            stats, birth_year=_birth_year()
        ),
        "stages": stage_years(_birth_year()),
    }


@app.get("/api/municipality/{city_code}/districts")
def get_district_summary(city_code: str, min_deals: int = Query(5, ge=1)):
    """市区町村内の地区別の住宅地単価ランキング。"""
    return _records(db.get_district_summary(city_code, min_deals=min_deals))


@app.get("/api/district_trend")
def get_district_trend(city_code: str, district_name: str):
    """特定の地区の価格推移。"""
    return {
        "city_code": city_code,
        "district_name": district_name,
        "trend": _price_records(db.get_price_trend(city_code, district_name)),
    }


# ------------------------------------------------------------------ 比較
@app.get("/api/ranking")
def get_ranking(
    pref_code: str | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    """スコアの一覧。重み付けはフロント側で再計算するため素点を返す。"""
    scores = db.get_scores()
    if scores.empty:
        return []

    wide = scores.pivot_table(
        index="municipality_code", columns="metric", values="value", aggfunc="first"
    )
    names = (
        scores[["municipality_code", "municipality_name", "prefecture_code",
                "prefecture_name"]]
        .drop_duplicates(subset="municipality_code")
        .set_index("municipality_code")
    )
    merged = names.join(wide)

    if pref_code:
        merged = merged[merged["prefecture_code"] == pref_code]

    if "composite" in merged.columns:
        merged = merged.sort_values("composite", ascending=False)

    merged = merged.head(limit).reset_index()
    return _records(merged)


@app.get("/api/compare")
def compare(codes: str = Query(..., description="カンマ区切りの市区町村コード")):
    """複数市区町村を横並びで比較する。"""
    city_codes = [c.strip() for c in codes.split(",") if c.strip()][:8]
    if not city_codes:
        raise HTTPException(status_code=400, detail="コードを指定してください")

    scores = db.get_scores()
    results = []
    for code in city_codes:
        info = db.get_municipality(code)
        if info is None:
            continue
        stats = db.get_stats(code)
        results.append(
            {
                "municipality": {k: _clean(v) for k, v in info.items()},
                "scores": _scores_for(code, scores),
                "child_projection": project_child_population(
                    stats, birth_year=_birth_year()
                ),
                "price_trend": _price_records(db.get_price_trend(code)),
            }
        )
    return results


# ------------------------------------------------------------ 地図タイル
@app.get("/api/tiles/{z}/{x}/{y}")
def get_mlit_tiles(z: int, x: int, y: int):
    """国交省 不動産情報ライブラリ XPT001 のタイルプロキシ。"""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API Key not configured")

    try:
        res = requests.get(
            "https://www.reinfolib.mlit.go.jp/ex-api/external/XPT001",
            params={
                "z": z, "x": x, "y": y,
                "from": "20231", "to": "20234",
                "response_format": "pbf",
            },
            headers={"Ocp-Apim-Subscription-Key": API_KEY},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if res.status_code == 404:
        return Response(content=b"", media_type="application/x-protobuf")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:200])
    return Response(content=res.content, media_type="application/x-protobuf")


# ------------------------------------------------------------------ 内部
@functools.lru_cache(maxsize=1)
def _metric_ranks() -> dict[str, Any]:
    """指標ごとの順位表。DBは読み取り専用で中身が変わらないので一度だけ作る。"""
    return metric_ranks(db.get_scores())


def _birth_year() -> int:
    from config import CHILD_BIRTH_YEAR

    return CHILD_BIRTH_YEAR


def _scores_for(
    city_code: str, scores: pd.DataFrame | None = None
) -> dict[str, Any]:
    frame = db.get_scores() if scores is None else scores
    if frame.empty:
        return {}
    subset = frame[frame["municipality_code"] == city_code]
    return {
        row["metric"]: _clean(row["value"])
        for _, row in subset.iterrows()
    }


# フロントエンドのビルド成果物を配信（開発時は Vite が別ポートで動く）
if os.path.isdir("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
