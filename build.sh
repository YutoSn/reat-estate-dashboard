#!/usr/bin/env bash
set -o errexit

# Python 依存関係のインストール
pip install -r requirements.txt

# フロントエンドのビルド
cd frontend
npm install
npm run build
