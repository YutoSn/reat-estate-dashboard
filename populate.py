"""データ取得からスコア算出までを一括で実行する。

使い方
------
    python populate.py            # すべて取得し直す
    python populate.py --stats    # e-Stat の統計だけ
    python populate.py --prices   # 不動産取引だけ
    python populate.py --scores   # 既存データからスコアだけ再計算

不動産取引は 8都県 × 20年 = 160リクエストあり15〜30分かかるため、
統計とスコアだけ回せるように分けている。
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from config import (
    CATCHMENT_RADIUS_KM,
    DUCKDB_FILE,
    MUNICIPALITY_GEO_FILE,
    TARGET_PREFECTURE_CODES,
    TARGET_YEARS,
    current_year,
)
from src.analysis.catchment import NEIGHBOR_INDICATORS
from src.analysis.geo import (
    haversine_km,
    municipality_points,
    neighbor_point_codes,
)
from src.analysis.metrics import build_metric_table
from src.analysis.scoring import composite_score, score_table, scores_to_long
from src.analysis.specialties import is_obstetric, is_pediatric
from src.db.duckdb_manager import DuckDBManager
from src.fetchers.estat_api import EStatAPI, parse_value, parse_year
from src.fetchers.medical_api import (
    ZOOM,
    MedicalFacilityAPI,
    normalize_feature,
    tiles_covering,
)
from src.fetchers.real_estate_api import RealEstateLibraryAPI
from src.indicators import DATASET_POPULATION, INDICATORS


# 住まい選びに使わない取引種別。保存対象から外してDBを軽くする。
EXCLUDED_TRADE_TYPES = {"農地", "林地"}

# 医療機関データ（国土数値情報 P04）の整備年。
# 統計テーブルに入れるときの「観測年」として使い、画面にもこの年で出す。
MEDICAL_DATA_YEAR = 2024


def _log(message: str) -> None:
    print(message, flush=True)


def populate_municipalities(db: DuckDBManager, api: EStatAPI) -> None:
    """e-Stat の地域マスタから、対象都道府県の市区町村一覧を作る。"""
    _log("市区町村マスタを取得中...")
    area_names = api.fetch_area_names(DATASET_POPULATION)

    candidates = []
    for code, name in area_names.items():
        if len(code) != 5 or not code.isdigit():
            continue
        if code[:2] not in TARGET_PREFECTURE_CODES:
            continue
        # 末尾が "000" の行は都道府県計や郡部の集計なので除外する
        if code.endswith("000"):
            continue

        parts = [p for p in name.split() if p]
        if len(parts) < 2:
            continue
        candidates.append((code, parts))

    # 政令指定都市は「市」と「区」の両方が返ってくる。区の側が残るように、
    # 子の区を持つ市レベルの行（例: 横浜市）は落とす。家を建てる場所を選ぶ
    # 用途では、区ごとに性格が大きく違うため区の粒度の方が使える。
    parent_names = {parts[1] for _, parts in candidates if len(parts) >= 3}

    rows = []
    for code, parts in candidates:
        municipality_name = "".join(parts[1:])
        # 「特別区部」は23区の合計であって自治体ではない
        if municipality_name.endswith("特別区部"):
            continue
        if len(parts) == 2 and parts[1] in parent_names:
            continue

        rows.append(
            {
                "municipality_code": code,
                "prefecture_code": code[:2],
                "prefecture_name": parts[0],
                "municipality_name": municipality_name,
                "full_name": " ".join(parts),
            }
        )

    df = pd.DataFrame(rows).drop_duplicates(subset="municipality_code")
    db.replace_municipalities(df)
    _log(f"  市区町村 {len(df)} 件を登録")


def populate_stats(db: DuckDBManager, api: EStatAPI) -> None:
    """指標カタログに沿って e-Stat の統計値を取得する。"""
    _log(f"e-Stat 統計を取得中（{len(INDICATORS)} 指標）...")

    # マスタに載っている自治体だけを残す（政令市の市レベル等の集計行を除く）
    target_codes = {row["municipality_code"] for row in db.get_cities_all()}
    # 隣接県は医療の圏内集計にだけ使うので、そのために要る指標だけ残す。
    # e-Stat は指標ごとに全国を返すため、追加のリクエストは発生しない。
    neighbor_codes = neighbor_point_codes()
    if neighbor_codes:
        _log(f"  隣接県 {len(neighbor_codes)} 自治体を圏内集計用に保存します")

    frames = []

    for index, indicator in enumerate(INDICATORS, start=1):
        try:
            records = api.fetch_indicator(indicator.dataset_id, indicator.code)
        except Exception as exc:  # 1指標の失敗で全体を止めない
            _log(f"  [{index}/{len(INDICATORS)}] {indicator.key}: 取得失敗 {exc}")
            continue

        keep_neighbors = indicator.key in NEIGHBOR_INDICATORS
        rows = []
        for record in records:
            code = str(record.get("@area", ""))
            if code not in target_codes:
                if not (keep_neighbors and code in neighbor_codes):
                    continue
            value = parse_value(record.get("$"))
            year = parse_year(record.get("@time"))
            if value is None or year is None:
                continue
            rows.append(
                {
                    "municipality_code": code,
                    "year": year,
                    "indicator": indicator.key,
                    "value": value,
                }
            )

        _log(
            f"  [{index}/{len(INDICATORS)}] {indicator.key} ({indicator.label}): "
            f"{len(rows)} 件"
        )
        if rows:
            frames.append(pd.DataFrame(rows))

    if not frames:
        _log("統計を1件も取得できなかったため中止します")
        return

    stats = pd.concat(frames, ignore_index=True)
    stats = stats.drop_duplicates(
        subset=["municipality_code", "year", "indicator"], keep="last"
    )
    # 取得できた指標だけを入れ替える。
    # 全消しにすると (1) 医療機関から作った指標まで消える (2) 1指標が取得失敗
    # しただけで既存データを失う、の2つが起きるため。
    fetched = sorted(stats["indicator"].unique())
    db.replace_stats_for_indicators(stats, fetched)
    _log(f"  統計値 {len(stats):,} 行を登録（{len(fetched)} 指標）")


def populate_land_prices(db: DuckDBManager, api: RealEstateLibraryAPI) -> None:
    """不動産取引価格を都道府県×年で取得する。"""
    years = [current_year() - offset for offset in range(TARGET_YEARS)]
    total_requests = len(TARGET_PREFECTURE_CODES) * len(years)
    _log(f"不動産取引を取得中（{total_requests} リクエスト）...")

    db.clear_land_prices()
    fetched = 0
    request_index = 0

    for pref_code in TARGET_PREFECTURE_CODES:
        pref_records = []
        for year in years:
            request_index += 1
            try:
                records = api.fetch_year(pref_code, year)
            except Exception as exc:
                _log(f"  [{request_index}/{total_requests}] {pref_code}/{year}: 失敗 {exc}")
                continue
            pref_records.extend(records)

        if not pref_records:
            continue

        df = pd.DataFrame(pref_records)
        # 対象都道府県外のコードが紛れることがあるため念のため絞る
        df = df[df["municipality_code"].str[:2] == pref_code]
        # 農地・林地は住まい選びには使わないので保存しない
        df = df[~df["type"].isin(EXCLUDED_TRADE_TYPES)]
        db.append_land_prices(df)
        fetched += len(df)
        _log(f"  {pref_code}: {len(df):,} 件を登録（累計 {fetched:,}）")

    _log(f"  不動産取引 {fetched:,} 行を登録")


def populate_medical_facilities(db: DuckDBManager, api: MedicalFacilityAPI) -> None:
    """医療機関を施設単位で取得し、最寄りの市区町村に割り当てて保存する。

    施設は座標で持っているが、圏内集計は市区町村ごとの供給量を足し上げる
    作りになっている（人口の分母が市区町村単位でしか取れないため）。
    そこで最寄りの代表点に寄せてから数える。
    """
    points = municipality_points()
    if not points:
        _log(
            f"  {MUNICIPALITY_GEO_FILE} が無いため医療機関を取得できません。\n"
            "  python scripts/build_municipality_geo.py で生成してください。"
        )
        return

    target_codes = {row["municipality_code"] for row in db.get_cities_all()}
    if not target_codes:
        _log("  市区町村マスタが空のため中止")
        return

    # 対象自治体の圏内にある施設だけ取れれば足りる
    target_coords = [points[code] for code in target_codes if code in points]
    tiles = tiles_covering(target_coords, CATCHMENT_RADIUS_KM)
    _log(f"医療機関を取得中（z={ZOOM} タイル {len(tiles):,} 枚）...")

    facilities: dict[str, dict] = {}
    empty_tiles = 0
    for index, features in api.fetch_tiles(tiles):
        if not features:
            empty_tiles += 1
        for feature in features:
            record = normalize_feature(feature)
            if record:
                facilities[record["facility_id"]] = record
        if index % 250 == 0 or index == len(tiles):
            _log(
                f"  [{index:,}/{len(tiles):,}] 施設 {len(facilities):,} 件"
                f"（空タイル {empty_tiles:,}）"
            )

    if not facilities:
        _log("  医療機関を1件も取得できませんでした")
        return

    df = pd.DataFrame(list(facilities.values()))

    # 最寄りの市区町村代表点に割り当てる
    codes, distances = _assign_nearest(df, points)
    df["municipality_code"] = codes
    df["distance_km"] = distances

    df["is_pediatric"] = [
        is_pediatric(subject, kind)
        for subject, kind in zip(df["medical_subject"], df["facility_type"])
    ]
    df["is_obstetric"] = [
        is_obstetric(subject, kind)
        for subject, kind in zip(df["medical_subject"], df["facility_type"])
    ]

    db.replace_medical_facilities(df)
    _log(
        f"  医療機関 {len(df):,} 件を登録"
        f"（小児科 {int(df['is_pediatric'].sum()):,} / "
        f"産科 {int(df['is_obstetric'].sum()):,}）"
    )
    _store_medical_counts(db)


# 距離行列を一度に作るとメモリを食うので、施設をこの件数ずつ処理する。
# 6万施設 × 770自治体 = 4600万要素（約370MB）になるため。
_ASSIGN_CHUNK = 4000
_EARTH_RADIUS_KM = 6371.0088


def _assign_nearest(
    df: pd.DataFrame, points: dict[str, tuple[float, float]]
) -> tuple[list[str], list[float]]:
    """各施設を最寄りの市区町村代表点に割り当てる。

    施設6万件×自治体770件を1件ずつ回すと4600万回の三角関数になって数分かかる。
    numpy でまとめて計算し、メモリのためにチャンクに分ける。
    """
    codes = list(points)
    municipality_lat = np.radians(np.array([points[c][0] for c in codes]))
    municipality_lon = np.radians(np.array([points[c][1] for c in codes]))
    cos_municipality = np.cos(municipality_lat)

    facility_lat = np.radians(df["latitude"].to_numpy(dtype=float))
    facility_lon = np.radians(df["longitude"].to_numpy(dtype=float))

    assigned_codes: list[str] = []
    assigned_distances: list[float] = []

    for start in range(0, len(facility_lat), _ASSIGN_CHUNK):
        lat = facility_lat[start:start + _ASSIGN_CHUNK][:, None]
        lon = facility_lon[start:start + _ASSIGN_CHUNK][:, None]

        delta_lat = municipality_lat[None, :] - lat
        delta_lon = municipality_lon[None, :] - lon
        inner = (
            np.sin(delta_lat / 2) ** 2
            + np.cos(lat) * cos_municipality[None, :] * np.sin(delta_lon / 2) ** 2
        )
        distance = 2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(inner))

        nearest = distance.argmin(axis=1)
        assigned_codes.extend(codes[i] for i in nearest)
        assigned_distances.extend(
            round(float(d), 2) for d in distance[np.arange(len(nearest)), nearest]
        )

    return assigned_codes, assigned_distances


def _store_medical_counts(db: DuckDBManager) -> None:
    """小児科・産科の施設数を、統計テーブルに指標として書き込む。

    圏内集計は municipality_stats の指標を読む作りなので、施設テーブルとは
    別にここへ入れておく。年は元データの整備年（国土数値情報の版）に合わせる。
    """
    counts = db.get_medical_counts_by_city()
    if counts.empty:
        return

    rows = []
    for _, row in counts.iterrows():
        for indicator in ("pediatric_clinics", "obstetric_clinics"):
            rows.append(
                {
                    "municipality_code": row["municipality_code"],
                    "year": MEDICAL_DATA_YEAR,
                    "indicator": indicator,
                    "value": float(row[indicator]),
                }
            )

    db.replace_stats_for_indicators(
        pd.DataFrame(rows), ["pediatric_clinics", "obstetric_clinics"]
    )
    _log(f"  施設数を統計に反映（{len(rows):,} 行）")


def compute_scores(db: DuckDBManager) -> None:
    """派生指標とスコアを計算して保存する。"""
    _log("スコアを計算中...")

    city_codes = [row["municipality_code"] for row in db.get_cities_all()]
    if not city_codes:
        _log("  市区町村マスタが空のため中止")
        return

    all_stats = db.get_all_stats()
    price_latest = db.get_latest_land_price_by_city(years=3)
    price_history = db.get_price_history_by_city()
    land_area = db.get_land_area_by_city(years=10)

    if not municipality_points():
        _log(
            f"  {MUNICIPALITY_GEO_FILE} が無いため利便性スコアは算出されません。\n"
            "  python scripts/build_municipality_geo.py で生成してください。"
        )

    metric_df = build_metric_table(
        all_stats,
        price_latest,
        price_history,
        city_codes,
        land_area=land_area,
        reference_year=current_year(),
    )
    scores = score_table(metric_df)
    if scores.empty:
        _log("  スコアを算出できませんでした")
        return

    scores["composite"] = composite_score(scores)

    # 派生指標そのものも保存し、UIで実数を出せるようにする
    metric_long = (
        metric_df.reset_index()
        .melt(id_vars="municipality_code", var_name="metric", value_name="value")
    )
    metric_long["value"] = pd.to_numeric(metric_long["value"], errors="coerce")
    metric_long = metric_long.dropna(subset=["value"])
    metric_long["metric"] = "raw_" + metric_long["metric"].astype(str)

    combined = pd.concat([scores_to_long(scores), metric_long], ignore_index=True)
    db.replace_scores(combined)
    _log(f"  スコア {len(combined):,} 行を登録（対象 {len(scores)} 市区町村）")


def main() -> int:
    parser = argparse.ArgumentParser(description="データ取得とスコア計算")
    parser.add_argument("--stats", action="store_true", help="e-Stat 統計のみ")
    parser.add_argument("--prices", action="store_true", help="不動産取引のみ")
    parser.add_argument("--medical", action="store_true", help="医療機関のみ")
    parser.add_argument("--scores", action="store_true", help="スコア再計算のみ")
    args = parser.parse_args()

    run_all = not (args.stats or args.prices or args.medical or args.scores)

    load_dotenv()
    estat_app_id = os.getenv("E_STAT_APP_ID")
    real_estate_key = os.getenv("REAL_ESTATE_LIBRARY_API_KEY")

    try:
        db = DuckDBManager(DUCKDB_FILE)
    except Exception as exc:
        # DuckDB は書き込み1プロセスまで。サーバーが掴んでいると開けない。
        if "already open" in str(exc):
            _log(
                f"{DUCKDB_FILE} を他のプロセスが開いています。\n"
                "uvicorn を停止してから実行し直してください。"
            )
            return 1
        raise

    if run_all or args.stats:
        if not estat_app_id:
            _log("E_STAT_APP_ID が未設定のため統計取得をスキップ")
        else:
            estat = EStatAPI(estat_app_id)
            populate_municipalities(db, estat)
            populate_stats(db, estat)

    if run_all or args.prices:
        if not real_estate_key:
            _log("REAL_ESTATE_LIBRARY_API_KEY が未設定のため取引取得をスキップ")
        else:
            populate_land_prices(db, RealEstateLibraryAPI(real_estate_key))

    if run_all or args.medical:
        if not real_estate_key:
            _log("REAL_ESTATE_LIBRARY_API_KEY が未設定のため医療機関取得をスキップ")
        else:
            populate_medical_facilities(db, MedicalFacilityAPI(real_estate_key))

    if run_all or args.scores or args.stats or args.prices or args.medical:
        compute_scores(db)

    _log("\n--- テーブル件数 ---")
    for table, count in db.table_counts().items():
        _log(f"  {table}: {count:,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
