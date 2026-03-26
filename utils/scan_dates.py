from mfp_adapter import MFPAdapter

def scan_range(start_date_obj, days=3):
    import datetime
    adapter = MFPAdapter()
    for i in range(days):
        d = start_date_obj + datetime.timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        data = adapter.get_diary_data(ds)
        items = [it for it in data.get("items", []) if it.get("type") == "food_entry"]
        print(f"Date {ds}: {len(items)} items found")
        for it in items:
            print(f"  - {it.get('food', {}).get('description')}")

if __name__ == "__main__":
    import datetime
    # 扫描前后三天
    base = datetime.date(2026, 3, 24)
    scan_range(base, 5)
