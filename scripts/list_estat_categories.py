"""e-Stat の統計表に、どんな指標が入っているかを一覧する。

指標を足すには (統計表ID, cat01コード) の組が要る。コードを推測すると
必ず間違える——このリポジトリは過去に I5101 を「小学校数」として扱い、
実際には「病院数」だったという事故を起こしている。

そこで追加したい指標は、必ずこのスクリプトで実データを見てから決める。

    # 健康・医療の分野に「小児科」を含む指標があるか調べる
    python scripts/list_estat_categories.py 0000020209 --grep 小児科

    # 分野の全指標を見る
    python scripts/list_estat_categories.py 0000020209

分野コードは src/indicators.py の DATASET_* を参照。
E_STAT_APP_ID が .env に必要。
"""

import argparse
import os
import pathlib
import sys

# scripts/ から実行すると sys.path はこのディレクトリになるので、リポジトリ直下を足す
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.fetchers.estat_api import EStatAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="e-Stat 統計表の指標一覧")
    parser.add_argument("dataset_id", help="統計表ID（例: 0000020209）")
    parser.add_argument("--grep", help="この文字列を含む指標だけ表示する")
    args = parser.parse_args()

    load_dotenv()
    app_id = os.getenv("E_STAT_APP_ID")
    if not app_id:
        print("E_STAT_APP_ID が未設定です（.env に入れてください）")
        return 1

    api = EStatAPI(app_id)
    meta = api._get(  # noqa: SLF001 — 調査用スクリプトなので内部呼び出しでよい
        "getMetaInfo", {"appId": app_id, "statsDataId": args.dataset_id}
    )

    try:
        classes = (
            meta["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]
        )
    except (KeyError, TypeError):
        print("メタ情報を読めませんでした。統計表IDを確認してください。")
        print(str(meta)[:500])
        return 1

    for class_obj in classes:
        if class_obj.get("@id") != "cat01":
            continue
        items = class_obj.get("CLASS", [])
        if isinstance(items, dict):
            items = [items]

        matched = [
            item for item in items
            if not args.grep or args.grep in str(item.get("@name", ""))
        ]
        print(f"{len(matched)} / {len(items)} 件")
        for item in matched:
            print(f"  {item.get('@code')}  {item.get('@name')}")
        return 0

    print("cat01 が見つかりませんでした。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
