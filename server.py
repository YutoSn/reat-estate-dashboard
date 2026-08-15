"""家を建てる場所を選ぶためのダッシュボード API。"""

import functools
import os
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import (
    BALANCE_MODEL,
    BUDGET_MODEL,
    LOAN_MODEL,
    CATCHMENT_RADIUS_KM,
    DUCKDB_FILE,
    REGIONAL_HUBS,
    SITE_MODEL,
    STATS_HISTORY_YEARS,
    TARGET_PREFECTURE_CODES,
    TOKYO_CENTER,
    current_year,
    stage_years,
)
from src.analysis.geo import access_for, municipality_points
from src.analysis.metrics import (
    CATCHMENT_SPECS,
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
from src.db.candidate_store import CandidateStore, ValidationError
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

# 候補地点だけは書き込みが要るので、DuckDB とは別のJSONファイルに持つ
# （理由は src/db/candidate_store.py の冒頭）。
candidates = CandidateStore()

# 圏内で集計している指標。内訳（圏内の自治体数）を画面に添えるのに使う。
CATCHMENT_METRIC_KEYS = tuple(
    f"{spec.supply_key}_catchment" for spec in CATCHMENT_SPECS
)


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


def _stats_trend_records(stats: pd.DataFrame) -> list[dict[str, Any]]:
    """統計の推移を、表示年数ぶんだけ切り出して返す。"""
    if stats.empty:
        return []
    cutoff = current_year() - STATS_HISTORY_YEARS
    trend = stats[stats.index >= cutoff]
    records = []
    for year, row in trend.iterrows():
        record = {"year": int(year)}
        record.update({k: _clean(v) for k, v in row.items()})
        records.append(record)
    return records


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
        "site_model": SITE_MODEL,
        # ローン試算の前提。予算判定と同じ値を使うのでここが唯一の定義。
        "loan_model": LOAN_MODEL,
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

    trend_records = _stats_trend_records(stats)

    scores = _scores_for(city_code)

    # 圏内の集計は全市区町村をまたぐ計算なので、1市区町村を見る derive_metrics では
    # 出せない。populate 時に保存した実数から補う。
    for spec in METRIC_SPECS:
        if metrics.get(spec.key) is None:
            metrics[spec.key] = scores.get(f"raw_{spec.key}")
    # 圏内の内訳（スコアには使わないが、集計の透明性のために画面に出す）
    for key in ("catchment_municipalities", "catchment_missing"):
        metrics[key] = scores.get(f"raw_{key}")

    covered = metrics["catchment_municipalities"]
    missing = metrics["catchment_missing"]
    if covered is not None:
        entries = [
            {"label": f"{CATCHMENT_RADIUS_KM}km圏内の自治体数",
             "value": covered, "unit": "自治体", "year": None},
        ]
        if missing:
            entries.append(
                {"label": "うち統計が未取得（圏内から除外）",
                 "value": missing, "unit": "自治体", "year": None}
            )
        for key in CATCHMENT_METRIC_KEYS:
            extra_inputs.setdefault(key, []).extend(entries)

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


@app.get("/api/municipality/{city_code}/pediatrics")
def get_pediatric_facilities(
    city_code: str,
    radius_km: float = Query(CATCHMENT_RADIUS_KM, gt=0, le=50),
    limit: int = Query(40, ge=1, le=200),
):
    """市区町村の代表点から近い順に、小児科を標榜する医療機関を返す。

    密度の数字だけだと「本当に近くにあるのか」が分からないので、
    実際の施設名と距離を出せるようにしている。
    """
    point = municipality_points().get(city_code)
    if point is None:
        raise HTTPException(status_code=404, detail="代表点がありません")

    latitude, longitude = point
    facilities = db.get_facilities_near(
        latitude, longitude, radius_km, specialty="pediatric"
    )
    records = _records(facilities.head(limit))
    for record in records:
        if record.get("distance_km") is not None:
            record["distance_km"] = round(record["distance_km"], 1)
    return {
        "city_code": city_code,
        "radius_km": radius_km,
        "total": int(len(facilities)),
        "facilities": records,
    }


@app.get("/api/district_trend")
def get_district_trend(city_code: str, district_name: str):
    """特定の地区の価格推移。"""
    return {
        "city_code": city_code,
        "district_name": district_name,
        "trend": _price_records(db.get_price_trend(city_code, district_name)),
    }


# ---------------------------------------------------------------- 候補地点
# 市区町村まで絞ったあとは「その地点から何が何km」が知りたくなる。
# 代表点からの距離ではなく、物件そのものの座標から測る。


def _round_km(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """距離はkmのまま小数1桁に丸める。徒歩何分には換算しない。

    このリポジトリは一貫して所要時間に換算しない（src/analysis/geo.py 参照）。
    直線距離を分に直すと、坂も踏切も信号も無かったことになるため。
    """
    for record in records:
        if record.get("distance_km") is not None:
            record["distance_km"] = round(record["distance_km"], 2)
    return records


@app.get("/api/site/nearby")
def get_site_nearby(
    lat: float = Query(..., description="緯度"),
    lon: float = Query(..., description="経度"),
    radius_km: float = Query(SITE_MODEL["radius_km"], gt=0,
                             le=SITE_MODEL["radius_max"]),
    city_code: str | None = None,
    district: str | None = None,
):
    """指定座標の周辺にある駅・医療機関と、その地域の土地単価。

    city_code は自動判定しない。市区町村の代表点は1市区町村1点しかなく、
    市境の物件は隣の市に寄ってしまう。登録時に選ばせた値を受け取る。
    """
    limit = SITE_MODEL["list_limit"]

    stations = db.get_stations_near(lat, lon, radius_km)
    pediatric = db.get_facilities_near(lat, lon, radius_km, specialty="pediatric")
    obstetric = db.get_facilities_near(lat, lon, radius_km, specialty="obstetric")
    hospitals = db.get_facilities_near(
        lat, lon, radius_km, specialty=None, facility_types=["病院"]
    )

    land: dict[str, Any] = {"city_code": city_code, "district": district}
    if city_code:
        latest = db.get_latest_land_price_by_city(years=3)
        row = latest[latest["municipality_code"] == city_code]
        if not row.empty and row.iloc[0]["deals"] >= MIN_PRICE_DEALS:
            land["city_unit_price"] = _clean(row.iloc[0]["land_unit_price"])
            land["city_deals"] = _clean(row.iloc[0]["deals"])
        # 地区は座標からは決められない（取引データに座標が無い）。
        # 登録時に選んでもらった地区名があるときだけ、その地区の単価を出す。
        if district:
            summary = db.get_district_summary(city_code, min_deals=1)
            hit = summary[summary["district_name"] == district]
            if not hit.empty:
                land["district_unit_price"] = _clean(hit.iloc[0]["land_unit_price"])
                land["district_deals"] = _clean(hit.iloc[0]["deals"])

    return {
        "latitude": lat,
        "longitude": lon,
        "radius_km": radius_km,
        # 距離はすべて直線距離。画面にもそう書く。
        "distance_basis": "直線距離",
        "stations": _round_km(_records(stations.head(limit))),
        "pediatric": {
            "total": int(len(pediatric)),
            "facilities": _round_km(_records(pediatric.head(limit))),
        },
        "obstetric": {
            "total": int(len(obstetric)),
            "facilities": _round_km(_records(obstetric.head(limit))),
        },
        "hospitals": {
            "total": int(len(hospitals)),
            "facilities": _round_km(_records(hospitals.head(limit))),
        },
        "land": land,
    }


@app.get("/api/sites")
def list_sites():
    """登録済みの候補地点。"""
    return {"sites": candidates.load()}


@app.post("/api/sites")
def create_site(payload: dict[str, Any] = Body(...)):
    try:
        return candidates.add(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/sites/{site_id}")
def update_site(site_id: str, payload: dict[str, Any] = Body(...)):
    try:
        record = candidates.update(site_id, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if record is None:
        raise HTTPException(status_code=404, detail="候補地点が見つかりません")
    return record


@app.delete("/api/sites/{site_id}")
def delete_site(site_id: str):
    if not candidates.remove(site_id):
        raise HTTPException(status_code=404, detail="候補地点が見つかりません")
    return {"deleted": site_id}


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
                # 推移は選んだ市区町村ぶんを1枚に重ねて描くので、ここでまとめて返す
                "price_trend": _price_records(db.get_price_trend(code)),
                "stats_trend": _stats_trend_records(stats),
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
