import requests
from typing import List, Dict, Any

class EducationAPI:
    """e-Stat APIから社会・人口統計体系データ（教育・子育て関連指標）を取得するクラス"""
    
    BASE_URL = "http://api.e-stat.go.jp/rest/3.0/app/json"
    STATS_DATA_ID = "0000020201" # 統計でみる市区町村のすがた（基礎データ）
    
    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_data(self) -> list:
        """指定した統計データ（全国の市区町村分）を取得する"""
        all_data = []
        
        print(f"Fetching nationwide education data...")
        
        # J2506: 保育所等数, I5101: 小学校数, I510110: 小学校教員数, I5102: 中学校数, I5103: 幼稚園数, J4403: 小児科医師数, I6100: 公共図書館数
        categories = ["J2506", "I5101", "I510110", "I5102", "I5103", "J4403", "I6100"]
        
        for category in categories:
            stats_id = "0000020209" if category.startswith("I") else "0000020210"
            
            print(f"Fetching category {category} from dataset {stats_id}...")
            params = {
                "appId": self.api_key,
                "statsDataId": stats_id,
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
                    print(f"Warning: Failed to fetch education data for {category}. Status: {response.status_code}")
            except Exception as e:
                print(f"Error fetching education data for {category}: {e}")
            
        return all_data
