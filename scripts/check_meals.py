#!/usr/bin/env python3
"""检查某餐是否已经记过，供「餐食提醒」定时任务调用。

定时任务里只需要一行：

    .venv/bin/python scripts/check_meals.py lunch

只读不写。定时任务按退出码决定要不要提醒用户。

用法::

    check_meals.py lunch              # 检查午餐
    check_meals.py                    # 三顿都检查，列出还空着的
    check_meals.py dinner --date 2026-10-26

餐名: breakfast / lunch / dinner / snacks（snack 也认）。

退出码:
    0 = 该餐已记录（有实际热量的条目），无需提醒
    1 = 该餐还没有记录，该提醒
    2 = 参数错误
    3 = 读取日记失败（cookies 失效、网络等）

为什么要按「有热量的条目」判断而不是「有条目」：
补剂自动化会在 08:00 往 Breakfast、19:00 往 Dinner、22:30 往 Snacks 写
0 kcal 的补剂。如果只看条目数，早餐永远显示「已记录」，提醒就永远不会触发。
所以只有出现 calories > 0 的条目才算这一餐真的吃了东西。
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

# 从项目根以外的地方调用时（cron / launchd 的工作目录不一定是项目根），
# 也要能 import 到 mfp_adapter。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mfp_adapter  # noqa: E402  (必须在 sys.path 调整之后)

# 用户输入 -> (MFP 餐次名, 中文标签)
_MEALS: dict[str, tuple[str, str]] = {
    "breakfast": ("Breakfast", "早餐"),
    "lunch": ("Lunch", "午餐"),
    "dinner": ("Dinner", "晚餐"),
    "snacks": ("Snacks", "加餐"),
}
_ALIASES = {"snack": "snacks"}
_MAIN_MEALS = ("breakfast", "lunch", "dinner")


def _normalize(token: str) -> str | None:
    key = str(token or "").strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in _MEALS else None


def _summarize(entries: list[dict]) -> tuple[int, int, float]:
    """返回 (条目数, 有热量的条目数, 总热量)。"""
    calories = [float(e.get("calories") or 0) for e in entries]
    return len(entries), sum(1 for c in calories if c > 0), sum(calories)


def _fmt_kcal(value: float) -> str:
    return f"{value:.0f}" if abs(value - round(value)) < 0.5 else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查某餐是否已记录（只读）")
    parser.add_argument(
        "meals",
        nargs="*",
        default=None,
        help="breakfast / lunch / dinner / snacks；省略则检查三餐",
    )
    parser.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    args = parser.parse_args(argv)

    raw = args.meals or list(_MAIN_MEALS)
    targets: list[str] = []
    unknown: list[str] = []
    for token in raw:
        key = _normalize(token)
        if key is None:
            unknown.append(str(token))
        elif key not in targets:
            targets.append(key)

    if unknown:
        options = "、".join(_MEALS)
        print(f"错误: 未知的餐名: {'、'.join(unknown)}。可选：{options}。")
        return 2
    if not targets:
        print("错误: 没有要检查的餐次。")
        return 2

    date_str = args.date or datetime.date.today().isoformat()
    try:
        adapter = mfp_adapter.get_adapter()
        entries = adapter.get_food_entries_from_html(date_str)
    except Exception as exc:  # noqa: BLE001  (定时任务要区分「读不到」和「没记录」)
        print(f"错误: 读取 {date_str} 日记失败: {exc}")
        return 3

    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry.get("meal") or "", []).append(entry)

    missing: list[str] = []
    lines: list[str] = []
    for key in targets:
        meal_name, label = _MEALS[key]
        items = grouped.get(meal_name, [])
        count, food_count, kcal = _summarize(items)
        if food_count:
            lines.append(f"✅ {label}（{meal_name}）已记录：{count} 项 / {_fmt_kcal(kcal)} kcal")
        elif count:
            # 只有 0 kcal 的补剂，没有真正的食物
            missing.append(label)
            lines.append(f"⚠️ {label}（{meal_name}）只记了 {count} 项 0 kcal 补剂，还没有食物记录")
        else:
            missing.append(label)
            lines.append(f"⚠️ {label}（{meal_name}）还没有任何记录")

    total = sum(float(e.get("calories") or 0) for e in entries)
    lines.append(f"全天合计：{_fmt_kcal(total)} kcal（{len(entries)} 项）")
    if missing:
        lines.append(f"待补：{'、'.join(missing)}")
        lines.append("提示：直接说吃了什么就能记，不用自己算热量。")
    print("\n".join(lines))

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
