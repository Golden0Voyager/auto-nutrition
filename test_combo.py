
import json
from mfp_adapter import get_adapter

def test_favorite_meal_combo():
    mfp = get_adapter()
    
    # 模拟 LLM 解析后的输入：包含一个组合名 + 一个额外项
    test_items = [
        {
            "name": "日常标准早餐",
            "serving_ratio": 1.0,
            "calories": 0, # 这里传 0 没关系，因为逻辑中会从配置库展开
            "macros": {"protein": 0, "carbs": 0, "fat": 0}
        },
        {
            "name": "半个火龙果",
            "serving_ratio": 1.0,
            "calories": 60,
            "macros": {"protein": 1.5, "carbs": 12, "fat": 0.5}
        }
    ]
    
    print("Testing Combo Expansion and Recording...")
    try:
        # 我们直接调用内部的 record_nutrition 方法
        # 注意：这里使用的是 mfp 对象的实例方法，它接收的是字典列表
        result = mfp.record_nutrition("2026-03-27", "breakfast", test_items)
        print(f"Result: {json.dumps(result, indent=2)}")
        if result["count"] >= 5:
            print("SUCCESS: Combo expanded to 4 items + 1 extra item.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_favorite_meal_combo()
