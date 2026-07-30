import requests
import datetime
from typing import List, Dict, Any

class RealEstateLibraryAPI:
    """不動産情報ライブラリAPI (地価公示・都道府県地価調査 等)"""
    
    BASE_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Ocp-Apim-Subscription-Key": self.api_key
        }

    def fetch_data(self, pref_codes: list, years_back: int = 10) -> list:
        all_data = []
        current_year = datetime.datetime.now().year
        
        # 過去N年分を取得
        target_years = [current_year - i for i in range(years_back)]
        
        for pref_code in pref_codes:
            print(f"Fetching real estate data for Prefecture {pref_code}...")
            for year in target_years:
                params = {
                    "year": str(year),
                    "area": pref_code
                }
                
                try:
                    response = requests.get(
                        f"{self.BASE_URL}/XIT001",
                        headers=self.headers,
                        params=params
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if "data" in data:
                            # 各レコードにyearを付与しておく
                            for record in data["data"]:
                                record["query_year"] = year
                            all_data.extend(data["data"])
                    else:
                        print(f"Warning: Failed to fetch real estate data for pref {pref_code}, year {year}. Status code: {response.status_code}")
                except Exception as e:
                    print(f"Error fetching real estate data for pref {pref_code}, year {year}: {e}")
                    
        return all_data
