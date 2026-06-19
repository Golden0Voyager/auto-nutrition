#!/usr/bin/env python3
"""端到端审计：检查本地日志 + USDA 搜索回归测试"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mfp_adapter import USDALocalResolver


def main():
    # ===== 1. 检查本地日志最近记录 =====
    with open('/Users/hainingyu/Code/auto_nutrition/nutrition_journal.json') as f:
        data = json.load(f)

    print("=== 最近7天餐食记录 ===")
    by_date_meal = defaultdict(lambda: defaultdict(list))
    for entry in data:
        d = entry['date']
        m = entry['meal_name']
        for item in entry['items']:
            by_date_meal[d][m].append(item['name'])

    for d in sorted(by_date_meal.keys())[-7:]:
        print(f"\n{d}:")
        for m, foods in by_date_meal[d].items():
            print(f"  {m}: {foods}")

    # ===== 2. 检测重复录入问题 =====
    print("\n\n=== 重复录入检测 ===")
    dup_issues = []
    for d in sorted(by_date_meal.keys())[-7:]:
        for m, foods in by_date_meal[d].items():
            seen = {}
            for f in foods:
                seen[f] = seen.get(f, 0) + 1
            for f, count in seen.items():
                if count > 1:
                    dup_issues.append(f"{d} {m}: '{f}' x{count}")
    if dup_issues:
        print("发现重复:")
        for issue in dup_issues:
            print(f"  ⚠️ {issue}")
    else:
        print("最近7天无重复")

    # ===== 3. USDA 端到端搜索测试 =====
    print("\n\n=== USDA 端到端搜索测试 ===")
    usda = USDALocalResolver()

    all_foods = set()
    for d in sorted(by_date_meal.keys())[-7:]:
        for m, foods in by_date_meal[d].items():
            for name in foods:
                clean = name.split('(')[0].split('/')[0].strip()
                if clean and len(clean) > 2:
                    all_foods.add(clean)

    failures = []
    for food in sorted(all_foods):
        results = usda.search(food, page_size=1)
        if results:
            print(f"✓ {food} -> {results[0]['name'][:50]} ({results[0]['calories_per_100g']} kcal)")
        else:
            print(f"✗ {food} -> NO RESULTS")
            failures.append(food)

    print(f"\n失败 {len(failures)}/{len(all_foods)}: {failures}")

    # ===== 4. 日志清理验证 =====
    print("\n\n=== 日志清理验证 ===")
    sample = data[-1]['items'][0] if data else {}
    null_count = sum(1 for v in sample.get('macros', {}).values() if v is None)
    internal_fields = [k for k in sample.keys() if k.startswith('_')]
    print(f"最新条目: {sample.get('name', 'N/A')}")
    print(f"  macros 中 null 值: {null_count}")
    print(f"  内部字段: {internal_fields}")
    if null_count > 5 or internal_fields:
        print("  ⚠️ 日志清理可能未生效")
    else:
        print("  ✓ 日志清理正常")

if __name__ == "__main__":
    main()
