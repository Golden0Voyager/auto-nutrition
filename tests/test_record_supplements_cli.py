"""scripts/record_supplements.py 的 CLI 契约。

合并定时任务后这条命令每天只跑一次，靠 ``--every-other-day`` 表达隔天节奏，
所以「非服用日不能少写、也不能多写」是硬约束——写错就是天天吃 D3 或
一天都不吃，而且静默。
"""

import sys
from pathlib import Path

import pytest

import mfp_adapter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import record_supplements  # noqa: E402  (必须在 sys.path 调整之后)


@pytest.fixture
def captured(monkeypatch):
    """替换真正的写入函数，只记录被调用的 segments。"""
    calls: list[dict] = []

    def fake(date_str, **kwargs):
        calls.append({"date": date_str, **kwargs})
        return "✅ 已写入 8 条"

    monkeypatch.setattr(mfp_adapter, "record_daily_supplements", fake)
    return calls


def test_dose_day_writes_everything(captured, capsys):
    code = record_supplements.main(["morning", "dinner", "night", "d3", "--date", "2026-11-02"])

    assert code == 0
    assert len(captured) == 1
    assert captured[0]["segments"] == ["d3_k2_stack", "dinner_stack", "morning_stack", "night_stack"]
    assert "跳过" not in capsys.readouterr().out


def test_non_dose_day_drops_d3_and_says_so(captured, capsys):
    code = record_supplements.main(
        ["morning", "dinner", "night", "d3", "--every-other-day", "d3", "--date", "2026-11-03"]
    )

    assert code == 0
    assert captured[0]["segments"] == ["dinner_stack", "morning_stack", "night_stack"]
    assert "不是隔天服用日" in capsys.readouterr().out


def test_non_dose_day_with_only_the_extra_segment_skips_the_write(captured, capsys):
    """空列表会被 record_daily_supplements 当成「写全部」，必须在这里截住。"""
    code = record_supplements.main(["d3", "--every-other-day", "d3", "--date", "2026-11-03"])

    assert code == 0
    assert captured == []
    assert "没有需要写入的补剂段" in capsys.readouterr().out


def test_unknown_segment_exits_2_without_writing(captured, capsys):
    code = record_supplements.main(["mornin", "--date", "2026-11-02"])

    assert code == 2
    assert captured == []
    assert "mornin" in capsys.readouterr().out


def test_write_failure_exits_1(captured, monkeypatch):
    monkeypatch.setattr(mfp_adapter, "record_daily_supplements", lambda *a, **k: "❌ 写入失败: 401")

    assert record_supplements.main(["morning", "--date", "2026-11-02"]) == 1


def test_idempotent_noop_exits_0(captured, monkeypatch):
    monkeypatch.setattr(mfp_adapter, "record_daily_supplements", lambda *a, **k: "今天没有需要新写入的条目")

    assert record_supplements.main(["morning", "--date", "2026-11-02"]) == 0
