import json
import os

class DataExporter:
    """ダッシュボード用のデータをJSON形式でエクスポートするクラス"""

    def __init__(self, output_dir: str = "frontend/public"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_to_json(self, cities_data: dict, output_filename: str = "data.json"):
        """
        cities_data: {
            "11237": {
                "name": "埼玉県三郷市",
                "trend": [{"year": 2010, "avg_price": ..., "population": ...}, ...]
            },
            ...
        }
        """
        file_path = os.path.join(self.output_dir, output_filename)
        
        # NaNなどをJSONで扱える形式（None）に変換済みの辞書を受け取る前提
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cities_data, f, ensure_ascii=False, indent=2)
            
        print(f"Data successfully exported to {file_path}")
