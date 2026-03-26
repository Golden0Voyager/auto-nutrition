import json
from mfp_adapter import MFPAdapter

def get_full_diary(date_str):
    adapter = MFPAdapter()
    data = adapter.get_diary_data(date_str)
    print(f"--- Full Data for {date_str} ---")
    
    # 打印所有的 meal 名称，看看系统里到底叫什么
    meals = [i.get("meal_name") for i in data.get("items", []) if i.get("type") == "diary_meal"]
    print(f"Available meals in diary: {meals}")
    
    # 打印前 2000 字符的原始响应
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])

if __name__ == "__main__":
    get_full_diary("2026-03-26")
