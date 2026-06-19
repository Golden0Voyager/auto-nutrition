
from mfp_adapter import MFPAdapter


def get_diary_simple(date_str):
    adapter = MFPAdapter()
    data = adapter.get_diary_data(date_str)
    # 打印所有的 entry，不限类型
    items = data.get("items", [])
    print(f"Date {date_str}: {len(items)} items total")
    for it in items:
        if it.get("type") == "food_entry":
            print(f"  - [FOOD] {it.get('food', {}).get('description')}")
        elif it.get("type") == "exercise_entry":
             print(f"  - [EXERCISE] {it.get('exercise', {}).get('description')}")
        else:
             print(f"  - [OTHER] {it.get('type')}")

if __name__ == "__main__":
    for d in ["2026-03-25", "2026-03-26", "2026-03-27"]:
        get_diary_simple(d)
