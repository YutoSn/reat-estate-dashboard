"""DuckDB へのデータ格納と、アプリ向けの集計クエリ。

設計方針
--------
* 統計値は long 形式（municipality_code, year, indicator, value）で持つ。
  指標を追加してもスキーマ変更が要らず、欠損もそのまま表現できる。
* 不動産取引は種別（宅地(土地) / 宅地(土地と建物) / 中古マンション等）を必ず保持する。
  種別を混ぜて「取引価格÷面積」を取ると、マンションの専有単価と土地単価が
  混ざって地価として意味をなさないため。
* 面積のマスク値（9999/8888 等の「2000㎡以上」を意味する丸め値）には
  フラグを立て、単価系の集計から除外する。
"""

from typing import Any

import duckdb
import pandas as pd

# 国交省APIが「一定面積以上」を丸めて返すマスク値
MASKED_AREA_VALUES = (2000.0, 5000.0, 8888.0, 9999.0)

# 住宅用の純粋な土地取引だけを指す条件
RESIDENTIAL_LAND_FILTER = "type = '宅地(土地)' AND region = '住宅地'"


class DuckDBManager:
    """アプリが使うすべての永続データを扱う。

    接続はインスタンスごとに1本だけ張り、クエリのたびに ``cursor()`` を作る。
    リクエストごとに ``duckdb.connect`` すると、同じファイルを複数の接続が
    掴んで ``IO Error: File is already open`` になるため。
    読み取り専用で開けば複数プロセスからの同時参照もできる。
    """

    def __init__(self, db_path: str, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self._conn = duckdb.connect(db_path, read_only=read_only)
        if not read_only:
            self._init_db()

    def _query(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        """読み取りクエリ。スレッドごとに独立したカーソルで実行する。"""
        cursor = self._conn.cursor()
        try:
            return cursor.execute(sql, params or []).df()
        finally:
            cursor.close()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ 初期化
    def _init_db(self) -> None:
        conn = self._conn
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS municipalities (
                municipality_code VARCHAR PRIMARY KEY,
                prefecture_code   VARCHAR,
                prefecture_name   VARCHAR,
                municipality_name VARCHAR,
                full_name         VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS municipality_stats (
                municipality_code VARCHAR,
                year              INTEGER,
                indicator         VARCHAR,
                value             DOUBLE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS land_prices (
                trade_year        INTEGER,
                quarter           INTEGER,
                period            VARCHAR,
                type              VARCHAR,
                region            VARCHAR,
                municipality_code VARCHAR,
                prefecture        VARCHAR,
                municipality      VARCHAR,
                district_name     VARCHAR,
                district_code     VARCHAR,
                trade_price       DOUBLE,
                unit_price        DOUBLE,
                price_per_tsubo   DOUBLE,
                area              DOUBLE,
                area_is_masked    BOOLEAN,
                total_floor_area  DOUBLE,
                building_year     INTEGER,
                structure         VARCHAR,
                use_purpose       VARCHAR,
                purpose           VARCHAR,
                city_planning     VARCHAR,
                coverage_ratio    DOUBLE,
                floor_area_ratio  DOUBLE,
                frontage          DOUBLE,
                land_shape        VARCHAR,
                renovation        VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS municipality_scores (
                municipality_code VARCHAR,
                metric            VARCHAR,
                value             DOUBLE
            )
            """
        )

    # ------------------------------------------------------------------ 書き込み
    def replace_municipalities(self, df: pd.DataFrame) -> None:
        self._conn.execute("DELETE FROM municipalities")
        self._conn.register("df_municipalities", df)
        self._conn.execute(
            "INSERT INTO municipalities SELECT municipality_code, prefecture_code,"
            " prefecture_name, municipality_name, full_name FROM df_municipalities"
        )

    def replace_stats(self, df: pd.DataFrame) -> None:
        self._conn.execute("DELETE FROM municipality_stats")
        self._conn.register("df_stats", df)
        self._conn.execute(
            "INSERT INTO municipality_stats SELECT municipality_code, year,"
            " indicator, value FROM df_stats"
        )

    def replace_land_prices(self, df: pd.DataFrame) -> None:
        self._conn.execute("DELETE FROM land_prices")
        self._append_land_prices(self._conn, df)

    def append_land_prices(self, df: pd.DataFrame) -> None:
        self._append_land_prices(self._conn, df)

    def clear_land_prices(self) -> None:
        self._conn.execute("DELETE FROM land_prices")

    @staticmethod
    def _append_land_prices(conn, df: pd.DataFrame) -> None:
        columns = [
            "trade_year", "quarter", "period", "type", "region",
            "municipality_code", "prefecture", "municipality", "district_name",
            "district_code", "trade_price", "unit_price", "price_per_tsubo",
            "area", "area_is_masked", "total_floor_area", "building_year",
            "structure", "use_purpose", "purpose", "city_planning",
            "coverage_ratio", "floor_area_ratio", "frontage", "land_shape",
            "renovation",
        ]
        conn.register("df_land", df[columns])
        conn.execute(f"INSERT INTO land_prices SELECT {', '.join(columns)} FROM df_land")

    def replace_scores(self, df: pd.DataFrame) -> None:
        self._conn.execute("DELETE FROM municipality_scores")
        self._conn.register("df_scores", df)
        self._conn.execute(
            "INSERT INTO municipality_scores SELECT municipality_code, metric,"
            " value FROM df_scores"
        )

    # ------------------------------------------------------------------ 読み出し
    def get_prefectures(self) -> list[dict[str, str]]:
        query = """
            SELECT DISTINCT prefecture_code AS code, prefecture_name AS name
            FROM municipalities
            WHERE prefecture_name IS NOT NULL
            ORDER BY prefecture_code
        """
        return self._query(query).to_dict("records")

    def get_cities(self, pref_code: str) -> list[dict[str, str]]:
        query = """
            SELECT municipality_code, municipality_name AS municipality
            FROM municipalities
            WHERE prefecture_code = ?
            ORDER BY municipality_code
        """
        return self._query(query, [pref_code]).to_dict("records")

    def get_cities_all(self) -> list[dict[str, str]]:
        """対象全都県の市区町村一覧。"""
        query = """
            SELECT municipality_code, municipality_name AS municipality,
                   prefecture_code, prefecture_name
            FROM municipalities
            ORDER BY municipality_code
        """
        return self._query(query).to_dict("records")

    def get_districts(self, city_code: str) -> list[dict[str, Any]]:
        """地区一覧。住宅地の土地取引が多い順に、件数付きで返す。"""
        query = f"""
            SELECT
                district_name,
                COUNT(*) FILTER (WHERE {RESIDENTIAL_LAND_FILTER}) AS land_deals,
                COUNT(*) AS total_deals
            FROM land_prices
            WHERE municipality_code = ? AND district_name IS NOT NULL
              AND district_name <> ''
            GROUP BY district_name
            ORDER BY land_deals DESC, total_deals DESC, district_name
        """
        return self._query(query, [city_code]).to_dict("records")

    def get_stats(self, city_code: str) -> pd.DataFrame:
        """指定市区町村の統計値を year×indicator のワイド表で返す。"""
        query = """
            SELECT year, indicator, value
            FROM municipality_stats
            WHERE municipality_code = ?
        """
        df = self._query(query, [city_code])
        if df.empty:
            return pd.DataFrame()
        return df.pivot_table(
            index="year", columns="indicator", values="value", aggfunc="first"
        ).sort_index()

    def get_stats_for_many(self, city_codes: list[str]) -> pd.DataFrame:
        """複数市区町村の統計値を long 形式で返す（スコア計算用）。"""
        if not city_codes:
            return pd.DataFrame(
                columns=["municipality_code", "year", "indicator", "value"]
            )
        placeholders = ", ".join("?" for _ in city_codes)
        query = f"""
            SELECT municipality_code, year, indicator, value
            FROM municipality_stats
            WHERE municipality_code IN ({placeholders})
        """
        return self._query(query, city_codes)

    def get_all_stats(self) -> pd.DataFrame:
        query = """
            SELECT municipality_code, year, indicator, value
            FROM municipality_stats
        """
        return self._query(query)

    # ------------------------------------------------------- 不動産価格の集計
    def get_price_trend(
        self, city_code: str, district_name: str | None = None
    ) -> pd.DataFrame:
        """住宅地の土地単価と戸建価格の推移。

        単価は外れ値に強い中央値を使う。極端に高額な一件（例: 170億円の取引）で
        平均が跳ねるのを避けるため。
        """
        district_clause = ""
        params: list[Any] = [city_code]
        if district_name:
            district_clause = "AND district_name = ?"
            params.append(district_name)

        query = f"""
            WITH base AS (
                SELECT * FROM land_prices
                WHERE municipality_code = ? {district_clause}
            )
            SELECT
                trade_year AS year,
                MEDIAN(unit_price) FILTER (
                    WHERE {RESIDENTIAL_LAND_FILTER} AND NOT area_is_masked
                      AND unit_price IS NOT NULL
                ) AS land_unit_price,
                COUNT(*) FILTER (
                    WHERE {RESIDENTIAL_LAND_FILTER} AND NOT area_is_masked
                      AND unit_price IS NOT NULL
                ) AS land_deals,
                MEDIAN(trade_price) FILTER (
                    WHERE type = '宅地(土地と建物)' AND region = '住宅地'
                      AND NOT area_is_masked
                ) AS house_price,
                COUNT(*) FILTER (
                    WHERE type = '宅地(土地と建物)' AND region = '住宅地'
                      AND NOT area_is_masked
                ) AS house_deals,
                MEDIAN(area) FILTER (
                    WHERE {RESIDENTIAL_LAND_FILTER} AND NOT area_is_masked
                ) AS land_area,
                MEDIAN(trade_price) FILTER (WHERE type = '中古マンション等') AS condo_price,
                COUNT(*) FILTER (WHERE type = '中古マンション等') AS condo_deals
            FROM base
            GROUP BY trade_year
            ORDER BY trade_year
        """
        return self._query(query, params)

    def get_latest_land_price_by_city(self, years: int = 3) -> pd.DataFrame:
        """市区町村ごとの直近数年の住宅地単価中央値（比較・スコア用）。"""
        query = f"""
            WITH latest AS (SELECT MAX(trade_year) AS y FROM land_prices)
            SELECT
                municipality_code,
                MEDIAN(unit_price) AS land_unit_price,
                COUNT(*) AS deals
            FROM land_prices, latest
            WHERE {RESIDENTIAL_LAND_FILTER}
              AND NOT area_is_masked
              AND unit_price IS NOT NULL
              AND trade_year > latest.y - ?
            GROUP BY municipality_code
        """
        return self._query(query, [years])

    def get_land_area_by_city(self, years: int = 10) -> pd.DataFrame:
        """市区町村ごとの住宅地の取引面積の中央値。

        「この地域で家を建てるなら何㎡の土地を買うことになるか」の目安として、
        世帯年収から必要額を出すときに使う。単価と違って面積は年ごとの振れが
        小さいので、直近10年をまとめて中央値を取る。
        """
        query = f"""
            WITH latest AS (SELECT MAX(trade_year) AS y FROM land_prices)
            SELECT
                municipality_code,
                MEDIAN(area) AS land_area_median,
                COUNT(*) AS deals
            FROM land_prices, latest
            WHERE {RESIDENTIAL_LAND_FILTER}
              AND NOT area_is_masked
              AND area IS NOT NULL
              AND trade_year > latest.y - ?
            GROUP BY municipality_code
        """
        return self._query(query, [years])

    def get_price_history_by_city(self) -> pd.DataFrame:
        """全市区町村×年の住宅地単価中央値（変化率の算出用）。"""
        query = f"""
            SELECT
                municipality_code,
                trade_year AS year,
                MEDIAN(unit_price) AS land_unit_price,
                COUNT(*) AS deals
            FROM land_prices
            WHERE {RESIDENTIAL_LAND_FILTER}
              AND NOT area_is_masked
              AND unit_price IS NOT NULL
            GROUP BY municipality_code, trade_year
        """
        return self._query(query)

    def get_district_summary(self, city_code: str, min_deals: int = 5) -> pd.DataFrame:
        """市区町村内の地区別サマリ（直近10年の住宅地単価と件数）。"""
        query = f"""
            WITH latest AS (SELECT MAX(trade_year) AS y FROM land_prices)
            SELECT
                district_name,
                MEDIAN(unit_price) AS land_unit_price,
                COUNT(*) AS deals,
                MEDIAN(area) AS median_area
            FROM land_prices, latest
            WHERE municipality_code = ?
              AND {RESIDENTIAL_LAND_FILTER}
              AND NOT area_is_masked
              AND unit_price IS NOT NULL
              AND trade_year > latest.y - 10
            GROUP BY district_name
            HAVING COUNT(*) >= ?
            ORDER BY land_unit_price DESC
        """
        return self._query(query, [city_code, min_deals])

    def get_scores(self) -> pd.DataFrame:
        query = """
            SELECT s.municipality_code, s.metric, s.value,
                   m.municipality_name, m.prefecture_code, m.prefecture_name
            FROM municipality_scores s
            LEFT JOIN municipalities m USING (municipality_code)
        """
        return self._query(query)

    def get_municipality(self, city_code: str) -> dict[str, Any] | None:
        query = "SELECT * FROM municipalities WHERE municipality_code = ?"
        df = self._query(query, [city_code])
        return df.to_dict("records")[0] if not df.empty else None

    def get_covered_city_codes(self) -> list[str]:
        """不動産取引データが存在する市区町村コード一覧。"""
        query = "SELECT DISTINCT municipality_code FROM land_prices ORDER BY 1"
        return self._query(query)["municipality_code"].tolist()

    def table_counts(self) -> dict[str, int]:
        tables = [
            "municipalities", "municipality_stats", "land_prices",
            "municipality_scores",
        ]
        return {
            table: int(self._query(f"SELECT COUNT(*) AS n FROM {table}")["n"][0])
            for table in tables
        }
