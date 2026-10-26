#!/usr/bin/env python3
"""按段记录当天补剂，供定时任务调用。

定时任务里只需要一行：

    .venv/bin/python scripts/record_supplements.py morning

把日期、段名、退出码都固化下来，避免在定时任务里手拼 python -c 出错。

用法::

    record_supplements.py morning                 # 晨补 -> 早餐
    record_supplements.py dinner night            # 晚餐补剂 + 睡前补剂
    record_supplements.py morning --dry-run       # 只预览不写入
    record_supplements.py morning --date 2026-10-26
    record_supplements.py workout --skip D3       # 训练包，跳过 D3+K2

段名: morning / dinner / night / workout（也接受完整 key morning_stack 等）。

退出码: 0 = 成功（含「今天已记过，跳过」），1 = 失败，2 = 参数错误。
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按段记录当天补剂（晨补 / 晚餐 / 睡前 / 训练包）",
    )
    parser.add_argument(
        "segments",
        nargs="+",
        help="morning / dinner / night / workout，或完整 key（morning_stack 等）",
    )
    parser.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    parser.add_argument("--force", action="store_true", help="忽略「今天已记」检查")
    parser.add_argument(
        "--skip",
        action="append",
        default=None,
        metavar="片段",
        help="要跳过的名称片段，可重复传（如 --skip D3 --skip 锌镁）",
    )
    args = parser.parse_args(argv)

    date_str = args.date or datetime.date.today().isoformat()
    output = mfp_adapter.record_daily_supplements(
        date_str,
        skip=args.skip,
        dry_run=args.dry_run,
        force=args.force,
        segments=args.segments,
    )
    print(output)

    # 「错误」开头 = 整体失败；含 ❌ = 某一段写入失败。两种情况都让退出码非 0，
    # 定时任务才能发现出事了。
    return 1 if (output.startswith("错误") or "❌" in output) else 0


if __name__ == "__main__":
    sys.exit(main())
