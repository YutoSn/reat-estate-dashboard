import duckdb
import pandas as pd
from typing import List, Dict, Any

class DuckDBManager:
    """DuckDBを用いたデータ管理・分析クラス"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        """テーブルの初期化"""
        with duckdb.connect(self.db_path) as conn:
            # 不動産価格用テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS land_prices (
                    query_year INTEGER,
                    period VARCHAR,
                    municipality_code VARCHAR,
                    municipality VARCHAR,
                    district_name VARCHAR,
                    trade_price DOUBLE,
                    area DOUBLE,
                    building_year VARCHAR,
                    use_purpose VARCHAR
                )
            """)
            
            # 人口推移用テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS populations (
                    year INTEGER,
                    municipality_code VARCHAR,
                    pop_total DOUBLE,
                    pop_0_14 DOUBLE,
                    pop_15_64 DOUBLE,
                    pop_65_over DOUBLE
                )
            """)
            
            # 教育・子育て統計用テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS education_stats (
                    year INTEGER,
                    municipality_code VARCHAR,
                    nurseries DOUBLE,
                    elementary_schools DOUBLE,
                    elementary_teachers DOUBLE,
                    junior_high_schools DOUBLE,
                    kindergartens DOUBLE,
                    pediatricians DOUBLE,
                    libraries DOUBLE
                )
            """)

    def insert_land_prices(self, data: List[Dict[str, Any]]):
        """不動産価格データを挿入"""
        if not data:
            return
            
        df = pd.DataFrame(data)
        
        cols = ['query_year', 'Period', 'MunicipalityCode', 'Municipality', 'DistrictName', 'TradePrice', 'Area', 'BuildingYear', 'Use']
        for col in cols:
            if col not in df.columns:
                df[col] = None
                
        df['MunicipalityCode'] = df['MunicipalityCode'].astype(str).str.zfill(5)
                
        df = df[cols].copy()
        df.columns = ['query_year', 'period', 'municipality_code', 'municipality', 'district_name', 'trade_price', 'area', 'building_year', 'use_purpose']
        
        df['trade_price'] = pd.to_numeric(df['trade_price'], errors='coerce')
        df['area'] = pd.to_numeric(df['area'], errors='coerce')
        
        with duckdb.connect(self.db_path) as conn:
            conn.execute("INSERT INTO land_prices SELECT * FROM df")
            
    def insert_populations(self, data: List[Dict[str, Any]]):
        """人口データを挿入"""
        if not data:
            return
            
        records = []
        for item in data:
            try:
                year_str = str(item.get('@time', ''))[:4]
                year = int(year_str) if year_str.isdigit() else None
                
                area_code = str(item.get('@area', '')).zfill(5)
                population = float(item.get('$', 0))
                category = item.get('_category', 'A2301')
                
                records.append({
                    'year': year,
                    'municipality_code': area_code,
                    'population': population,
                    'category': category
                })
            except Exception as e:
                continue
                
        df = pd.DataFrame(records)
        
        # Pivot the dataframe to have categories as columns
        df_pivot = df.pivot_table(
            index=['year', 'municipality_code'], 
            columns='category', 
            values='population',
            aggfunc='first'
        ).reset_index()
        
        # Rename columns to match the new schema
        col_mapping = {
            'A2301': 'pop_total',
            'A1301': 'pop_0_14',
            'A1302': 'pop_15_64',
            'A1303': 'pop_65_over'
        }
        df_pivot = df_pivot.rename(columns=col_mapping)
        
        # Ensure all columns exist
        for col in ['pop_total', 'pop_0_14', 'pop_15_64', 'pop_65_over']:
            if col not in df_pivot.columns:
                df_pivot[col] = None
                
        df_pivot = df_pivot[['year', 'municipality_code', 'pop_total', 'pop_0_14', 'pop_15_64', 'pop_65_over']].copy()
        
        with duckdb.connect(self.db_path) as conn:
            conn.execute("INSERT INTO populations SELECT * FROM df_pivot")

    def insert_education_stats(self, data: List[Dict[str, Any]]):
        """教育統計データを挿入"""
        if not data:
            return
            
        records = []
        for item in data:
            try:
                year_str = str(item.get('@time', ''))[:4]
                year = int(year_str) if year_str.isdigit() else None
                
                area_code = str(item.get('@area', '')).zfill(5)
                value = float(item.get('$', 0))
                category = item.get('_category', '')
                
                records.append({
                    'year': year,
                    'municipality_code': area_code,
                    'value': value,
                    'category': category
                })
            except Exception:
                continue
                
        if not records:
            return

        df = pd.DataFrame(records)
        df_pivot = df.pivot_table(
            index=['year', 'municipality_code'], 
            columns='category', 
            values='value',
            aggfunc='first'
        ).reset_index()
        
        col_mapping = {
            'J2506': 'nurseries',
            'I5101': 'elementary_schools',
            'I510110': 'elementary_teachers',
            'I5102': 'junior_high_schools',
            'I5103': 'kindergartens',
            'J4403': 'pediatricians',
            'I6100': 'libraries'
        }
        df_pivot = df_pivot.rename(columns=col_mapping)
        
        expected_cols = list(col_mapping.values())
        for col in expected_cols:
            if col not in df_pivot.columns:
                df_pivot[col] = None
                
        df_pivot = df_pivot[['year', 'municipality_code'] + expected_cols].copy()
        
        with duckdb.connect(self.db_path) as conn:
            conn.execute("INSERT INTO education_stats SELECT * FROM df_pivot")

    def get_all_integrated_trends(self) -> pd.DataFrame:
        """全市区町村の地価推移と人口推移を統合して取得 (従来機能用)"""
        query = """
            WITH price_trend AS (
                SELECT 
                    query_year as year, 
                    municipality_code,
                    ANY_VALUE(municipality) as municipality_name,
                    AVG(trade_price / NULLIF(area, 0)) as avg_price_per_sqm, 
                    COUNT(*) as transaction_count
                FROM land_prices
                WHERE trade_price IS NOT NULL AND area IS NOT NULL
                GROUP BY query_year, municipality_code
            )
            SELECT 
                COALESCE(p.year, pop.year) as year,
                COALESCE(p.municipality_code, pop.municipality_code) as municipality_code,
                p.municipality_name,
                p.avg_price_per_sqm,
                p.transaction_count,
                pop.pop_total as population
            FROM price_trend p
            FULL OUTER JOIN populations pop 
                ON p.year = pop.year AND p.municipality_code = pop.municipality_code
            WHERE p.municipality_name IS NOT NULL
            ORDER BY municipality_code, year
        """
        with duckdb.connect(self.db_path) as conn:
            return conn.execute(query).df()

    def get_district_trend(self, city_code: str, district_name: str) -> pd.DataFrame:
        """指定された地区（町丁・大字）の20年間の地価推移と、所属市区町村の人口推移を取得"""
        query = """
            WITH price_trend AS (
                SELECT 
                    query_year as year, 
                    AVG(trade_price / NULLIF(area, 0)) as avg_price_per_sqm, 
                    COUNT(*) as transaction_count
                FROM land_prices
                WHERE municipality_code = ? 
                  AND district_name LIKE ?
                  AND trade_price IS NOT NULL 
                  AND area IS NOT NULL
                GROUP BY query_year
            ),
            pop_trend AS (
                SELECT year, pop_total as population, pop_0_14, pop_15_64, pop_65_over
                FROM populations
                WHERE municipality_code = ?
            )
            SELECT 
                COALESCE(p.year, pop.year) as year,
                p.avg_price_per_sqm,
                p.transaction_count,
                pop.population,
                pop.pop_0_14,
                pop.pop_15_64,
                pop.pop_65_over
            FROM price_trend p
            FULL OUTER JOIN pop_trend pop ON p.year = pop.year
            WHERE COALESCE(p.year, pop.year) IS NOT NULL
            ORDER BY year
        """
        import re
        # XPT001の「丸の内１丁目」のような文字列から、「１丁目」などを除去して前方一致検索する
        base_name = re.sub(r'[0-9０-９]+丁目.*$', '', district_name)
        search_pattern = f"{base_name}%"
        
        with duckdb.connect(self.db_path) as conn:
            # DuckDBのプリペアドステートメントで実行
            # city_code を2回、search_pattern を1回渡す
            return conn.execute(query, [city_code, search_pattern, city_code]).df()

    def get_cities(self, pref_code: str) -> List[Dict[str, str]]:
        """指定された都道府県の市区町村一覧を取得"""
        query = """
            SELECT DISTINCT municipality_code, municipality
            FROM land_prices
            WHERE SUBSTRING(municipality_code, 1, 2) = ?
              AND municipality IS NOT NULL
            ORDER BY municipality_code
        """
        with duckdb.connect(self.db_path) as conn:
            df = conn.execute(query, [pref_code]).df()
            return df.to_dict('records')

    def get_districts(self, city_code: str) -> List[str]:
        """指定された市区町村の地区一覧を取得"""
        query = """
            SELECT DISTINCT district_name
            FROM land_prices
            WHERE municipality_code = ?
              AND district_name IS NOT NULL
            ORDER BY district_name
        """
        with duckdb.connect(self.db_path) as conn:
            df = conn.execute(query, [city_code]).df()
            return df['district_name'].tolist()

    def get_education_trend(self, city_code: str) -> pd.DataFrame:
        """指定された市区町村の教育・子育て関連指標の推移を取得"""
        query = """
            SELECT 
                COALESCE(e.year, pop.year) as year,
                COALESCE(e.municipality_code, pop.municipality_code) as municipality_code,
                pop.pop_total as population,
                pop.pop_0_14,
                e.nurseries,
                e.elementary_schools,
                e.elementary_teachers,
                e.junior_high_schools,
                e.kindergartens,
                e.pediatricians,
                e.libraries
            FROM populations pop
            FULL OUTER JOIN education_stats e 
                ON pop.year = e.year AND pop.municipality_code = e.municipality_code
            WHERE COALESCE(e.municipality_code, pop.municipality_code) = ?
            ORDER BY year
        """
        with duckdb.connect(self.db_path) as conn:
            return conn.execute(query, [city_code]).df()
