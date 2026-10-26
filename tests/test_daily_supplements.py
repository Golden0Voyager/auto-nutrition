"""record_daily_supplements：全天补剂一次调用完成分段写入。"""

import copy
from unittest.mock import MagicMock

import pytest

import mfp_adapter
from mfp_adapter import MFPAdapter, plan_daily_supplements


def _item(name: str, calories: float = 0.0, **macros: float) -> dict:
    return {
        "name": name,
        "calories": calories,
        "macros": {"carbs": 0, "protein": 0, "fat": 0, **macros},
    }


ROUTINES = {
    "morning_stack": {
        "name": "晨补",
        "aliases": ["晨补"],
        "items": [
            _item("辅酶Q10"),
            _item("B族维生素"),
            {**_item("鱼油", 20.0, fat=2.2), "serving_ratio": 2},
        ],
    },
    "dinner_stack": {
        "name": "晚餐补剂",
        "aliases": ["晚餐补剂"],
        "items": [_item("Move Free"), {**_item("鱼油", 20.0, fat=2.2), "serving_ratio": 2}],
    },
    "night_stack": {
        "name": "睡前补剂",
        "aliases": ["睡前补剂"],
        "items": [_item("锌镁片", 4.8, carbs=1.2)],
    },
    "workout_stack": {
        "name": "训练日补剂",
        "aliases": ["训练日补剂"],
        "items": [
            _item("甜菜根粉", 35.0, carbs=8),
            _item("Whey Protein", 120.0, protein=24, carbs=3, fat=1.5),
            _item("肌酸"),
        ],
    },
    "d3_k2_stack": {
        "name": "D3+K2 隔天",
        "aliases": ["D3+K2隔天"],
        "items": [_item("D3+K2")],
    },
}


def _plan(**kwargs):
    return plan_daily_supplements(ROUTINES, resolve=lambda name: name, **kwargs)


class TestPlanDailySupplements:
    def test_default_plan_uses_three_meal_segments(self):
        plan = _plan()

        assert [(s["routine"], s["meal_type"]) for s in plan["segments"]] == [
            ("morning_stack", "breakfast"),
            ("dinner_stack", "dinner"),
            ("night_stack", "snack"),
        ]

    def test_include_workout_appends_a_snack_segment(self):
        plan = _plan(include_workout=True)

        assert plan["segments"][-1]["routine"] == "workout_stack"
        assert plan["segments"][-1]["meal_type"] == "snack"

    def test_skip_token_drops_only_the_matching_item(self):
        plan = _plan(skip=["B族"])

        names = [item["name"] for item in plan["segments"][0]["items"]]
        assert names == ["辅酶Q10", "鱼油"]
        assert plan["skipped_by_user"] == ["B族维生素"]

    def test_skip_removes_a_segment_that_loses_all_items(self):
        plan = _plan(skip=["锌镁"])

        assert [s["routine"] for s in plan["segments"]] == ["morning_stack", "dinner_stack"]

    def test_logged_items_are_skipped_per_meal(self):
        plan = _plan(logged={("Breakfast", "鱼油")})

        assert "鱼油" not in [i["name"] for i in plan["segments"][0]["items"]]
        assert "鱼油" in [i["name"] for i in plan["segments"][1]["items"]]
        assert plan["skipped_logged"] == ["鱼油"]

    def test_force_keeps_items_that_were_already_logged(self):
        plan = _plan(logged={("Breakfast", "鱼油")}, force=True)

        assert "鱼油" in [i["name"] for i in plan["segments"][0]["items"]]


class TestCrossMealDuplicates:
    """跨餐次重复保护：只挡「全局只出现一次」的条目。

    真实事故：午餐单独记了肌酸，再跑全天补剂（训练包也在写肌酸），一天记两次。
    幂等键是 (餐次, 名称)，Snacks 与 Lunch 永不相等，所以同一餐次检查抓不到。
    """

    def test_single_dose_item_logged_elsewhere_is_skipped(self):
        plan = _plan(include_workout=True, logged_anywhere={"肌酸": "Lunch"})

        workout = plan["segments"][-1]["items"]
        assert "肌酸" not in [i["name"] for i in workout]
        assert plan["skipped_cross_meal"] == ["肌酸（已记在午餐）"]

    def test_multi_dose_item_is_never_cross_meal_skipped(self):
        """鱼油晨补 1 粒 + 晚餐 2 粒，别处记过也不能跳过。"""
        plan = _plan(logged_anywhere={"鱼油": "Lunch"})

        assert "鱼油" in [i["name"] for i in plan["segments"][0]["items"]]
        assert "鱼油" in [i["name"] for i in plan["segments"][1]["items"]]
        assert plan["skipped_cross_meal"] == []

    def test_same_meal_hit_reports_as_logged_not_cross_meal(self):
        plan = _plan(
            logged={("Breakfast", "辅酶Q10")},
            logged_anywhere={"辅酶Q10": "Breakfast"},
        )

        assert plan["skipped_logged"] == ["辅酶Q10"]
        assert plan["skipped_cross_meal"] == []

    def test_force_ignores_cross_meal(self):
        plan = _plan(include_workout=True, logged_anywhere={"肌酸": "Lunch"}, force=True)

        assert "肌酸" in [i["name"] for i in plan["segments"][-1]["items"]]
        assert plan["skipped_cross_meal"] == []

    def test_unknown_meal_name_falls_back_to_raw(self):
        plan = _plan(include_workout=True, logged_anywhere={"肌酸": "Brunch"})

        assert plan["skipped_cross_meal"] == ["肌酸（已记在Brunch）"]


class TestRecordDailySupplements:
    @pytest.fixture
    def adapter(self, tmp_path):
        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter._config = {"routines": copy.deepcopy(ROUTINES)}
        adapter._config_mtime = 0
        adapter.JOURNAL_FILE = str(tmp_path / "journal.json")
        adapter._JOURNAL_MAX_ENTRIES = 200
        adapter._load_config = lambda: adapter._config
        adapter.record_nutrition = MagicMock(
            side_effect=lambda _date, _meal, items: {"status": "ok", "count": len(items)}
        )
        return adapter

    def _seed_full_day(self, adapter) -> None:
        adapter._write_journal([
            {
                "timestamp": "2026-10-24T09:00:00",
                "date": "2026-10-24",
                "meal_name": "Breakfast",
                "items": [{"name": n} for n in ("辅酶Q10", "B族维生素", "鱼油", "D3+K2")],
            },
            {
                "timestamp": "2026-10-24T19:00:00",
                "date": "2026-10-24",
                "meal_name": "Dinner",
                "items": [{"name": n} for n in ("Move Free", "鱼油")],
            },
            {
                "timestamp": "2026-10-24T22:00:00",
                "date": "2026-10-24",
                "meal_name": "Snacks",
                "items": [{"name": "锌镁片"}],
            },
        ])

    def test_dry_run_reports_without_writing(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", dry_run=True)

        adapter.record_nutrition.assert_not_called()
        assert "预览" in output
        assert "早餐" in output and "晚餐" in output and "加餐" in output

    def test_writes_one_call_per_segment(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24")

        calls = adapter.record_nutrition.call_args_list
        assert [c.args[1] for c in calls] == ["breakfast", "dinner", "snack"]
        assert [len(c.args[2]) for c in calls] == [3, 2, 1]
        assert "6 条" in output

    def test_include_workout_writes_a_fourth_segment(self, adapter):
        adapter.record_daily_supplements("2026-10-24", include_workout=True)

        calls = adapter.record_nutrition.call_args_list
        assert [c.args[1] for c in calls] == ["breakfast", "dinner", "snack", "snack"]
        assert calls[-1].args[2][0]["name"] == "甜菜根粉"

    def test_second_run_skips_everything_already_logged(self, adapter):
        self._seed_full_day(adapter)

        output = adapter.record_daily_supplements("2026-10-24")

        adapter.record_nutrition.assert_not_called()
        assert "已记录" in output

    def test_force_rewrites_even_when_journal_has_the_day(self, adapter):
        self._seed_full_day(adapter)

        adapter.record_daily_supplements("2026-10-24", force=True)

        assert adapter.record_nutrition.call_count == 3

    def test_skip_reaches_the_per_segment_call(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", skip=["B族"])

        morning_items = adapter.record_nutrition.call_args_list[0].args[2]
        assert "B族维生素" not in [item["name"] for item in morning_items]
        assert "跳过" in output

    def test_missing_routine_is_skipped(self, adapter):
        del adapter._config["routines"]["dinner_stack"]

        adapter.record_daily_supplements("2026-10-24")

        meals = [c.args[1] for c in adapter.record_nutrition.call_args_list]
        assert meals == ["breakfast", "snack"]

    def test_no_routines_returns_error(self, adapter):
        adapter._config = {"routines": {}}

        output = adapter.record_daily_supplements("2026-10-24")

        adapter.record_nutrition.assert_not_called()
        assert output.startswith("错误")

    def test_journal_entries_from_other_dates_are_ignored(self, adapter):
        adapter._write_journal([
            {
                "timestamp": "2026-10-23T09:00:00",
                "date": "2026-10-23",
                "meal_name": "Breakfast",
                "items": [{"name": "辅酶Q10"}, {"name": "B族维生素"}, {"name": "鱼油"}, {"name": "D3+K2"}],
            },
        ])

        adapter.record_daily_supplements("2026-10-24")

        assert len(adapter.record_nutrition.call_args_list[0].args[2]) == 3

    def test_segment_warnings_are_surfaced(self, adapter):
        adapter.record_nutrition = MagicMock(
            return_value={"status": "ok", "count": 1, "warnings": ["⚠️ 以下食物未匹配到营养数据"]}
        )

        output = adapter.record_daily_supplements("2026-10-24")

        assert "未匹配到营养数据" in output

    def test_one_failed_segment_does_not_stop_the_rest(self, adapter):
        adapter.record_nutrition = MagicMock(
            side_effect=[
                {"status": "ok", "count": 4},
                RuntimeError("500 Server Error"),
                {"status": "ok", "count": 1},
            ]
        )

        output = adapter.record_daily_supplements("2026-10-24")

        assert adapter.record_nutrition.call_count == 3
        assert "❌" in output
        assert "1 段写入失败" in output

    def test_cross_meal_duplicate_is_skipped_and_reported(self, adapter):
        """午餐单独记过肌酸，训练包里的那份必须跳过（否则一天记两次）。"""
        adapter._write_journal([
            {
                "timestamp": "2026-10-24T12:00:00",
                "date": "2026-10-24",
                "meal_name": "Lunch",
                "items": [{"name": "肌酸"}],
            },
        ])

        output = adapter.record_daily_supplements("2026-10-24", include_workout=True)

        workout_items = adapter.record_nutrition.call_args_list[-1].args[2]
        assert "肌酸" not in [item["name"] for item in workout_items]
        assert "其他餐次" in output
        assert "肌酸（已记在午餐）" in output

    def test_force_writes_cross_meal_duplicate(self, adapter):
        adapter._write_journal([
            {
                "timestamp": "2026-10-24T12:00:00",
                "date": "2026-10-24",
                "meal_name": "Lunch",
                "items": [{"name": "肌酸"}],
            },
        ])

        adapter.record_daily_supplements("2026-10-24", include_workout=True, force=True)

        workout_items = adapter.record_nutrition.call_args_list[-1].args[2]
        assert "肌酸" in [item["name"] for item in workout_items]

    def test_multi_dose_item_survives_a_cross_meal_hit(self, adapter):
        """鱼油早餐+晚餐各一份是设计如此，别处记过也不能跳过。"""
        adapter._write_journal([
            {
                "timestamp": "2026-10-24T12:00:00",
                "date": "2026-10-24",
                "meal_name": "Lunch",
                "items": [{"name": "鱼油"}],
            },
        ])

        adapter.record_daily_supplements("2026-10-24")

        breakfast = adapter.record_nutrition.call_args_list[0].args[2]
        dinner = adapter.record_nutrition.call_args_list[1].args[2]
        assert "鱼油" in [item["name"] for item in breakfast]
        assert "鱼油" in [item["name"] for item in dinner]


class TestResolveSegments:
    """段名归一化：短名、完整 key 都认，未知段名明确报错而不是静默忽略。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (["morning"], {"morning_stack"}),
            (["dinner"], {"dinner_stack"}),
            (["night"], {"night_stack"}),
            (["workout"], {"workout_stack"}),
            (["night_stack"], {"night_stack"}),
            (["d3"], {"d3_k2_stack"}),
            (["d3k2"], {"d3_k2_stack"}),
            (["d3_k2_stack"], {"d3_k2_stack"}),
            (["Morning", " DINNER "], {"morning_stack", "dinner_stack"}),
        ],
    )
    def test_short_names_and_full_keys(self, raw, expected):
        keys, error = mfp_adapter._resolve_segments(raw)

        assert keys == expected
        assert error is None

    @pytest.mark.parametrize("raw", [None, []])
    def test_empty_means_all_segments(self, raw):
        assert mfp_adapter._resolve_segments(raw) == (None, None)

    def test_unknown_name_is_an_error_not_a_silent_skip(self):
        keys, error = mfp_adapter._resolve_segments(["mornin"])

        assert keys is None
        assert error is not None
        assert "mornin" in error
        assert "morning" in error


class TestExtraSegments:
    """EXTRA 段（隔天补剂，如 D3+K2）只能显式点名，绝不进全天组合。

    晨补的定时任务每天都跑；D3+K2 混进标准段就会天天记一遍，
    journal 的维生素 D 摄入凭空翻倍。
    """

    def test_extra_segment_is_not_in_the_full_day_plan(self):
        plan = _plan()

        assert "d3_k2_stack" not in [s["routine"] for s in plan["segments"]]

    def test_extra_segment_is_written_when_named(self):
        plan = _plan(only={"d3_k2_stack"})

        assert [(s["routine"], s["meal_type"]) for s in plan["segments"]] == [
            ("d3_k2_stack", "breakfast")
        ]

    def test_extra_segment_can_be_combined_with_standard_ones(self):
        plan = _plan(only={"morning_stack", "d3_k2_stack"})

        assert [s["routine"] for s in plan["segments"]] == ["morning_stack", "d3_k2_stack"]


class TestPlanOnlySegments:
    """only= 只排指定段：定时任务按作息逐段调用时用。"""

    def test_only_filters_to_a_single_segment(self):
        plan = _plan(only={"night_stack"})

        assert [(s["routine"], s["meal_type"]) for s in plan["segments"]] == [
            ("night_stack", "snack")
        ]

    def test_only_none_keeps_all_default_segments(self):
        assert len(_plan(only=None)["segments"]) == 3

    def test_only_workout_still_requires_include_workout(self):
        assert _plan(only={"workout_stack"})["segments"] == []

    def test_multi_dose_item_is_not_blocked_when_scoped(self):
        plan = _plan(only={"morning_stack"}, logged_anywhere={"鱼油": "Dinner"})

        names = [item["name"] for s in plan["segments"] for item in s["items"]]
        assert "鱼油" in names

    def test_single_dose_item_is_blocked_cross_meal_when_scoped(self):
        plan = _plan(only={"morning_stack"}, logged_anywhere={"辅酶Q10": "Lunch"})

        names = [item["name"] for s in plan["segments"] for item in s["items"]]
        assert "辅酶Q10" not in names
        assert plan["skipped_cross_meal"] == ["辅酶Q10（已记在午餐）"]


class TestSegmentScopedWrite:
    """record_daily_supplements(segments=...) 只写指定段，幂等与跨餐次保护照常。"""

    @pytest.fixture
    def adapter(self, tmp_path):
        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter._config = {"routines": copy.deepcopy(ROUTINES)}
        adapter._config_mtime = 0
        adapter.JOURNAL_FILE = str(tmp_path / "journal.json")
        adapter._JOURNAL_MAX_ENTRIES = 200
        adapter._load_config = lambda: adapter._config
        adapter.record_nutrition = MagicMock(
            side_effect=lambda _date, _meal, items: {"status": "ok", "count": len(items)}
        )
        return adapter

    def test_only_morning_writes_a_single_breakfast_call(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", segments=["morning"])

        assert adapter.record_nutrition.call_count == 1
        assert adapter.record_nutrition.call_args.args[1] == "breakfast"
        assert "晨补" in output

    def test_only_night_writes_a_single_snack_call(self, adapter):
        adapter.record_daily_supplements("2026-10-24", segments=["night"])

        assert adapter.record_nutrition.call_count == 1
        assert adapter.record_nutrition.call_args.args[1] == "snack"

    def test_full_routine_key_is_accepted(self, adapter):
        adapter.record_daily_supplements("2026-10-24", segments=["dinner_stack"])

        assert adapter.record_nutrition.call_args.args[1] == "dinner"

    def test_unknown_segment_returns_error_without_writing(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", segments=["mornin"])

        adapter.record_nutrition.assert_not_called()
        assert output.startswith("错误")
        assert "mornin" in output

    def test_workout_segment_implies_include_workout(self, adapter):
        adapter.record_daily_supplements("2026-10-24", segments=["workout"])

        assert adapter.record_nutrition.call_count == 1
        names = [item["name"] for item in adapter.record_nutrition.call_args.args[2]]
        assert "Whey Protein" in names

    def test_segments_can_be_combined(self, adapter):
        adapter.record_daily_supplements("2026-10-24", segments=["dinner", "night"])

        meals = [call.args[1] for call in adapter.record_nutrition.call_args_list]
        assert meals == ["dinner", "snack"]

    def test_rerunning_the_same_segment_writes_nothing(self, adapter):
        adapter._write_journal([
            {
                "timestamp": "2026-10-24T08:00:00",
                "date": "2026-10-24",
                "meal_name": "Breakfast",
                "items": [{"name": n} for n in ("辅酶Q10", "B族维生素", "鱼油", "D3+K2")],
            }
        ])

        output = adapter.record_daily_supplements("2026-10-24", segments=["morning"])

        adapter.record_nutrition.assert_not_called()
        assert "没有需要新写入" in output

    def test_dry_run_title_names_the_segment(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", dry_run=True, segments=["night"])

        assert "睡前补剂" in output
        assert "1 条" in output
        adapter.record_nutrition.assert_not_called()

    def test_d3_segment_writes_breakfast_only(self, adapter):
        output = adapter.record_daily_supplements("2026-10-24", segments=["d3"])

        assert adapter.record_nutrition.call_count == 1
        assert adapter.record_nutrition.call_args.args[1] == "breakfast"
        names = [item["name"] for item in adapter.record_nutrition.call_args.args[2]]
        assert names == ["D3+K2"]
        assert "D3+K2" in output

    def test_morning_segment_no_longer_carries_d3(self, adapter):
        adapter.record_daily_supplements("2026-10-24", segments=["morning"])

        names = [item["name"] for item in adapter.record_nutrition.call_args.args[2]]
        assert "D3+K2" not in names


class TestToolWrapper:
    def test_delegates_to_adapter(self, monkeypatch):
        fake = MagicMock()
        fake.record_daily_supplements.return_value = "已记录"
        monkeypatch.setattr(mfp_adapter, "get_adapter", lambda: fake)

        output = mfp_adapter.record_daily_supplements(
            "2026-10-24", include_workout=True, skip=["D3"], dry_run=True
        )

        assert output == "已记录"
        fake.record_daily_supplements.assert_called_once_with(
            "2026-10-24",
            include_workout=True,
            skip=["D3"],
            dry_run=True,
            force=False,
            segments=None,
        )

    def test_forwards_segments(self, monkeypatch):
        fake = MagicMock()
        fake.record_daily_supplements.return_value = "已记录"
        monkeypatch.setattr(mfp_adapter, "get_adapter", lambda: fake)

        mfp_adapter.record_daily_supplements("2026-10-24", segments=["morning"])

        assert fake.record_daily_supplements.call_args.kwargs["segments"] == ["morning"]

    def test_returns_error_string_instead_of_raising(self, monkeypatch):
        def _boom():
            raise RuntimeError("会话失效")

        monkeypatch.setattr(mfp_adapter, "get_adapter", _boom)

        output = mfp_adapter.record_daily_supplements("2026-10-24")

        assert output.startswith("错误")
        assert "会话失效" in output
