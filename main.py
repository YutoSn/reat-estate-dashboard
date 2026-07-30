import os
import datetime
from config import TARGET_PREFECTURE_CODES, TARGET_YEARS, DUCKDB_FILE
from src.fetchers.real_estate_api import RealEstateLibraryAPI
from src.fetchers.population_api import PopulationAPI
from src.db.duckdb_manager import DuckDBManager
from src.data_exporter import DataExporter
from dotenv import load_dotenv

def main():
    print("--- 不動産・地域データ総合取得・分析システム ---")
    
    # .env ファイルから環境変数を読み込む
    load_dotenv()
    
    real_estate_api_key = os.getenv("REAL_ESTATE_LIBRARY_API_KEY")
    e_stat_app_id = os.getenv("E_STAT_APP_ID")
    
    if not real_estate_api_key or not e_stat_app_id:
        print("Error: API Keys not found in .env file.")
        return

    print(f"Target Prefecture Codes: {TARGET_PREFECTURE_CODES}")
    print(f"Target Years: Past {TARGET_YEARS} years")
    
    # データベースの初期化
    db = DuckDBManager(DUCKDB_FILE)
    
    # 不動産データの取得と登録
    try:
        real_estate_api = RealEstateLibraryAPI(api_key=real_estate_api_key)
        print("Fetching real estate data (by Prefecture)...")
        real_estate_data = real_estate_api.fetch_data(pref_codes=TARGET_PREFECTURE_CODES, years_back=TARGET_YEARS)
        print(f"Fetched {len(real_estate_data)} real estate records.")
        db.insert_land_prices(real_estate_data)
    except Exception as e:
        print(f"Error during real estate data processing: {e}")

    # 人口データの取得と登録
    try:
        population_api = PopulationAPI(api_key=e_stat_app_id)
        print("Fetching nationwide population data...")
        population_data = population_api.fetch_data()
        print(f"Fetched {len(population_data)} population records.")
        db.insert_populations(population_data)
    except Exception as e:
        print(f"Error during population data processing: {e}")

    # 分析・集計結果の表示とフロントエンドへのエクスポート
    print("\n--- Integrated Trend & JSON Export ---")
    
    # 全市区町村の統合データを取得
    trend_df = db.get_all_integrated_trends()
    
    # 対象年数でフィルタリング (最新年から TARGET_YEARS 年分)
    current_year = datetime.datetime.now().year
    trend_df = trend_df[trend_df['year'] > (current_year - TARGET_YEARS)]
    
    # NaN を None (null) に変換
    trend_df = trend_df.replace({float('nan'): None})
    
    cities_data = {}
    
    # DataFrameを都市ごとにグループ化して辞書に構築
    for city_code, group in trend_df.groupby('municipality_code'):
        # 最初の有効な都市名を取得
        city_name = group['municipality_name'].dropna().iloc[0] if not group['municipality_name'].dropna().empty else f"Code:{city_code}"
        
        trend_list = group.drop(columns=['municipality_code', 'municipality_name']).to_dict(orient='records')
        
        cities_data[city_code] = {
            "name": city_name,
            "trend": trend_list
        }
        
    print(f"Successfully processed data for {len(cities_data)} municipalities.")

    # JSON出力
    exporter = DataExporter(output_dir="frontend/public")
    exporter.export_to_json(cities_data, output_filename="data.json")
    
if __name__ == "__main__":
    main()
