import folium
from geopy.geocoders import Nominatim
import pandas as pd

class MapGenerator:
    """地図(HTML)を生成し、ハザードマップと集計データを可視化するクラス"""

    def __init__(self):
        # ユーザーエージェントを指定してジオコーダーを初期化
        self.geolocator = Nominatim(user_agent="land_price_analyzer")
        
        # 重ねるハザードマップ（国土地理院）のタイルレイヤーURL定義
        self.hazard_layers = {
            "洪水浸水想定区域 (想定最大規模)": "https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png",
            "土砂災害警戒区域 (土石流)": "https://disaportaldata.gsi.go.jp/raster/05_dosekiryukeikaikuiki/{z}/{x}/{y}.png",
            "津波浸水想定": "https://disaportaldata.gsi.go.jp/raster/04_tsunami_newlegend_data/{z}/{x}/{y}.png"
        }

    def generate_map(self, cities_data: dict, output_file: str = "regional_analysis_map.html"):
        """
        cities_data: {
            "11237": {"name": "埼玉県三郷市", "summary": "平均地価: XX円, 人口: YY人"},
            ...
        }
        """
        # 日本の中心付近で初期化（後で自動調整）
        m = folium.Map(location=[36.0, 138.0], zoom_start=5)

        # ハザードマップレイヤーの追加
        for name, url in self.hazard_layers.items():
            folium.TileLayer(
                tiles=url,
                fmt='image/png',
                attr="国土地理院 重ねるハザードマップ",
                name=name,
                overlay=True,
                control=True,
                opacity=0.7
            ).add_to(m)

        bounds = []
        for city_code, data in cities_data.items():
            city_name = data.get("name", "")
            summary = data.get("summary", "データなし")
            
            # 市区町村の代表座標を取得
            try:
                location = self.geolocator.geocode(city_name)
                if location:
                    lat, lon = location.latitude, location.longitude
                    bounds.append([lat, lon])
                    
                    # ポップアップに表示するHTML
                    popup_html = f"<h4>{city_name}</h4><pre>{summary}</pre>"
                    
                    # マーカーの追加
                    folium.Marker(
                        location=[lat, lon],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=city_name,
                        icon=folium.Icon(color="blue", icon="info-sign")
                    ).add_to(m)
            except Exception as e:
                print(f"Failed to geocode {city_name}: {e}")

        # レイヤーコントロールを追加（ハザードマップのON/OFF切り替え用）
        folium.LayerControl().add_to(m)

        # 全てのマーカーが見えるようにズームを調整
        if bounds:
            m.fit_bounds(bounds)

        # HTMLファイルとして保存
        m.save(output_file)
        print(f"Map successfully generated: {output_file}")
