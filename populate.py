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

import pandas as pd
from dotenv import load_dotenv

from config import DUCKDB_FILE, TARGET_PREFECTURE_CODES, TARGET_YEARS, current_year
from src.analysis.metrics import build_metric_table
from src.analysis.scoring import composite_score, score_table, scores_to_long
from src.db.duckdb_manager import DuckDBManager
from src.fetchers.estat_api import EStatAPI, parse_value, parse_year
from src.fetchers.real_estate_api import RealEstateLibraryAPI
from src.indicators import DATASET_POPULATION, INDICATORS


# 住まい選びに使わない取引種別。保存対象から外してDBを軽くする。
EXCLUDED_TRADE_TYPES = {"農地", "林地"}


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
    valid_codes = {row["municipality_code"] for row in db.get_cities_all()}
    frames = []

    for index, indicator in enumerate(INDICATORS, start=1):
        try:
            records = api.fetch_indicator(indicator.dataset_id, indicator.code)
        except Exception as exc:  # 1指標の失敗で全体を止めない
            _log(f"  [{index}/{len(INDICATORS)}] {indicator.key}: 取得失敗 {exc}")
            continue

        rows = []
        for record in records:
            code = str(record.get("@area", ""))
            if code not in valid_codes:
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
    db.replace_stats(stats)
    _log(f"  統計値 {len(stats):,} 行を登録")


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

    metric_df = build_metric_table(
        all_stats,
        price_latest,
        price_history,
        city_codes,
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
    parser.add_argument("--scores", action="store_true", help="スコア再計算のみ")
    args = parser.parse_args()

    run_all = not (args.stats or args.prices or args.scores)

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

    if run_all or args.scores or args.stats or args.prices:
        compute_scores(db)

    _log("\n--- テーブル件数 ---")
    for table, count in db.table_counts().items():
        _log(f"  {table}: {count:,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
