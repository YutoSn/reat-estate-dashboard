import os
import duckdb
from dotenv import load_dotenv
from src.fetchers.population_api import PopulationAPI
from src.db.duckdb_manager import DuckDBManager

def reset_and_populate():
    load_dotenv()
    db_file = 'land_price.duckdb'
    
    # 1. populationsテーブルの中身を削除
    with duckdb.connect(db_file) as conn:
        conn.execute("DELETE FROM populations")
        print("Deleted all rows from populations table.")
        
    # 2. 最新のデータを取得して挿入
    api = PopulationAPI(api_key=os.getenv('E_STAT_APP_ID'))
    data = api.fetch_data()
    print(f"Fetched {len(data)} raw population records.")
    
    db = DuckDBManager(db_file)
    db.insert_populations(data)
    
    with duckdb.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM populations").fetchone()[0]
        print(f"Successfully inserted {count} rows into populations table.")
        
if __name__ == "__main__":
    reset_and_populate()
