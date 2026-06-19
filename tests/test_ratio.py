import json
from datetime import datetime

from mfp_adapter import get_adapter


def main():
    adapter = get_adapter()
    today = datetime.now().strftime("%Y-%m-%d")

    items = [
        {
            "name": "宝矿力 (半瓶)",
            "serving_ratio": 0.5,
            "calories": 135,
            "macros": {"protein": 0, "carbs": 33, "fat": 0}
        }
    ]

    print("正在录入 半瓶宝矿力 测算数据...")
    result = adapter.record_nutrition(today, "snack", items)
    print("\n录入完成，返回结果：")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
