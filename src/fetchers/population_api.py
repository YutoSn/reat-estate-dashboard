import requests
from typing import List, Dict, Any

class PopulationAPI:
    """e-Stat APIから社会・人口統計体系データを取得するクラス"""
    
    BASE_URL = "http://api.e-stat.go.jp/rest/3.0/app/json"
    STATS_DATA_ID = "0000020201" # 市区町村データ
    
    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_data(self) -> list:
        """指定した統計データ（全国の市区町村分）を取得する"""
        all_data = []
        
        print(f"Fetching nationwide population data...")
        
        # A2301: 総人口, A1301: 15歳未満, A1302: 15-64歳, A1303: 65歳以上
        categories = ["A2301", "A1301", "A1302", "A1303"]
        
        for category in categories:
            print(f"Fetching category {category}...")
            params = {
                "appId": self.api_key,
                "statsDataId": self.STATS_DATA_ID,
                "cdCat01": category
            }
            
            try:
                response = requests.get(f"{self.BASE_URL}/getStatsData", params=params)
                if response.status_code == 200:
                    data = response.json()
                    try:
                        stat_data = data["GET_STATS_DATA"]["STATISTICAL_DATA"]["DATA_INF"]["VALUE"]
                        if isinstance(stat_data, dict):
                            stat_data = [stat_data]
                        
                        # Add category info to each record
                        for record in stat_data:
                            record["_category"] = category
                            
                        all_data.extend(stat_data)
                    except KeyError:
                        print(f"Warning: No valid data found in response for {category}.")
                else:
                    print(f"Warning: Failed to fetch population data for {category}. Status: {response.status_code}")
            except Exception as e:
                print(f"Error fetching population data for {category}: {e}")
            
        return all_data
