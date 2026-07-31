import os
import duckdb
from dotenv import load_dotenv
from src.fetchers.education_api import EducationAPI
from src.db.duckdb_manager import DuckDBManager

def reset_and_populate():
    load_dotenv()
    db_file = 'land_price.duckdb'
    
    db = DuckDBManager(db_file)
    
    # 1. education_statsテーブルの中身を削除
    with duckdb.connect(db_file) as conn:
        conn.execute("DELETE FROM education_stats")
        print("Deleted all rows from education_stats table.")
        
    # 2. 最新のデータを取得して挿入
    api = EducationAPI(api_key=os.getenv('E_STAT_APP_ID'))
    data = api.fetch_data()
    print(f"Fetched {len(data)} raw education records.")
    
    db = DuckDBManager(db_file)
    db.insert_education_stats(data)
    
    with duckdb.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM education_stats").fetchone()[0]
        print(f"Successfully inserted {count} rows into education_stats table.")
        
if __name__ == "__main__":
    reset_and_populate()
