import os
import requests
import datetime
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import math

from src.db.duckdb_manager import DuckDBManager
from config import DUCKDB_FILE, TARGET_YEARS

load_dotenv()
API_KEY = os.getenv("REAL_ESTATE_LIBRARY_API_KEY")

app = FastAPI(title="Land Price Analysis Backend")

# CORS設定 (開発用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = DuckDBManager(DUCKDB_FILE)

@app.get("/api/tiles/{z}/{x}/{y}")
def get_mlit_tiles(z: int, x: int, y: int):
    """国交省不動産情報ライブラリ XPT001 APIのプロキシ"""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API Key not configured")
        
    url = "https://www.reinfolib.mlit.go.jp/ex-api/external/XPT001"
    params = {
        "z": z,
        "x": x,
        "y": y,
        "from": "20231",
        "to": "20234",
        "response_format": "pbf"
    }
    headers = {
        "Ocp-Apim-Subscription-Key": API_KEY
    }
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 404:
            return Response(content=b"", media_type="application/x-protobuf")
            
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail=res.text)
            
        return Response(content=res.content, media_type="application/x-protobuf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/education_trend")
def get_education_trend(city_code: str):
    """
    指定された市区町村の教育・子育て関連指標の20年間の推移を取得する。
    """
    db = DuckDBManager(DUCKDB_FILE)
    try:
        df = db.get_education_trend(city_code)
        
        # 最新年からTARGET_YEARS(20年)分にフィルタリング
        current_year = datetime.datetime.now().year
        df = df[df['year'] > (current_year - TARGET_YEARS)]
        
        # NaNをNoneに変換
        df = df.replace({float('nan'): None})
        
        return {
            "city_code": city_code,
            "trend": df.to_dict(orient="records")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/api/trend")
def get_district_trend(city_code: str, district_name: str):
    """指定された市区町村・地区の過去20年の地価および人口トレンドを取得"""
    df = db.get_district_trend(city_code, district_name)
    
    # 最新年からTARGET_YEARS(20年)分にフィルタリング
    current_year = datetime.datetime.now().year
    df = df[df['year'] > (current_year - TARGET_YEARS)]
    
    # NaNをNoneに変換
    df = df.replace({float('nan'): None})
    
    # 結果の整形
    trend_list = df.to_dict(orient='records')
    
    return {
        "city_code": city_code,
        "district_name": district_name,
        "trend": trend_list
    }

@app.get("/api/prefectures")
def get_prefectures():
    """ドロップダウン用の対象都道府県リスト"""
    prefectures = [
        {"code": "03", "name": "岩手県"},
        {"code": "04", "name": "宮城県"},
        {"code": "06", "name": "山形県"},
        {"code": "08", "name": "茨城県"},
        {"code": "11", "name": "埼玉県"},
        {"code": "12", "name": "千葉県"},
        {"code": "13", "name": "東京都"},
        {"code": "14", "name": "神奈川県"}
    ]
    return prefectures

@app.get("/api/cities/{pref_code}")
def get_cities(pref_code: str):
    """指定された都道府県の市区町村リストを取得"""
    cities = db.get_cities(pref_code)
    return cities

@app.get("/api/districts/{city_code}")
def get_districts(city_code: str):
    """指定された市区町村の地区リストを取得"""
    districts = db.get_districts(city_code)
    return districts

# Vite等のフロントエンド開発サーバーを利用中なので、ビルドした静的ファイルを
# 配信するルーティングは省略（または public フォルダをマウントするだけ）。
# 本番運用時は frontend/dist をマウントする。
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
