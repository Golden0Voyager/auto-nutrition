"""工具层分支：查不到、匹配到多条、目标缺少 id 等提示路径。

这些分支不改数据，只决定「用户看到哪句话」。但它们的契约是
「有疑问就不删」——一旦被重构改成猜一个目标，就会静默误删。
所以用测试钉住这个契约，而不是钉住文案本身。
"""

from unittest.mock import MagicMock, patch

from mfp_adapter import (
    ExerciseModel,
    FoodItemModel,
    delete_entry,
    delete_exercise,
    delete_last_entry,
    delete_meal_group,
    get_daily_summary,
    get_goals,
    record_exercise,
    record_meal,
    search_exercise,
    update_entry,
)


def _item(**kwargs):
    return FoodItemModel(**{"name": "Oatmeal", "calories": 350, **kwargs})


class TestDeleteEntryBranches:
    ENTRIES = [
        {"id": "111", "name": "Oats", "meal": "Breakfast", "calories": 300.0},
        {"id": "112", "name": "Oats", "meal": "Lunch", "calories": 300.0},
        {"id": "113", "name": "Chicken", "meal": "Dinner", "calories": 400.0},
    ]

    def test_meal_filter_narrows_candidates(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter._remove_from_journal.return_value = 1

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", entry_id="112", meal_type="lunch")

        assert "已删除 Lunch 的「Oats」" in result
        assert "本地日志已同步" in result

    def test_meal_filter_with_no_match_reports_empty(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", name="Oats", meal_type="snack")

        assert "没有找到可删除" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_unknown_entry_id(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", entry_id="404")

        assert "没有找到 id=404" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_exact_name_single_match(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter._remove_from_journal.return_value = 0

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", name="chicken")

        mock_get_adapter.delete_diary_entry.assert_called_once_with("113")
        assert "本地日志无匹配项" in result

    def test_ambiguous_exact_name_returns_candidates(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", name="Oats")

        assert "匹配到多个" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_entry_without_id_is_not_deleted(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"name": "Mystery", "meal": "Lunch"},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", name="Mystery")

        assert "缺少 entry id" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_read_failure_is_reported(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = Exception("html down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_entry("2026-10-23", name="Oats")

        assert "删除失败" in result and "html down" in result


class TestDeleteLastEntryBranches:
    def test_unknown_meal_type(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_last_entry("2026-10-23", meal_type="brunch")

        assert "未知餐次" in result

    def test_non_positive_count_is_rejected(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "111", "name": "Oats", "meal": "Breakfast"},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_last_entry("2026-10-23", count=0)

        assert "count 必须 ≥ 1" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()


class TestUpdateEntryBranches:
    ENTRIES = [
        {"id": "111", "name": "Oats", "meal": "Breakfast", "calories": 300.0},
        {"id": "113", "name": "Chicken", "meal": "Dinner", "calories": 400.0},
    ]

    def test_no_entries_for_date(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", entry_id="111")

        assert "没有找到可修改" in result

    def test_exact_name_single_match(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = [
            self.ENTRIES,
            [{"id": "999", "name": "Oatmeal", "meal": "Breakfast"}],
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", name="Oats")

        assert "已用「Oatmeal」替换" in result
        mock_get_adapter.delete_diary_entry.assert_called_once_with("111")

    def test_unique_substring_match(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = [
            self.ENTRIES,
            [{"id": "999", "name": "Oatmeal", "meal": "Breakfast"}],
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", name="chick")

        assert "已用「Oatmeal」替换" in result
        mock_get_adapter.delete_diary_entry.assert_called_once_with("113")

    def test_ambiguous_substring_returns_candidates(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "111", "name": "Oatmeal", "meal": "Breakfast"},
            {"id": "112", "name": "Oat bar", "meal": "Snack"},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", name="oat")

        assert "匹配到多个" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_no_name_match(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", name="zzz")

        assert "没有名称匹配" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_entry_without_id_is_not_modified(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"name": "Mystery", "meal": "Lunch"},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", name="Mystery")

        assert "缺少 entry id" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_unknown_meal_type_override(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self.ENTRIES

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(meal_type="brunch"), "2026-10-23", entry_id="111")

        assert "未知餐次" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_readback_failure_does_not_block_replacement(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = [
            self.ENTRIES,
            Exception("readback down"),
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", entry_id="111")

        assert "已用「Oatmeal」替换" in result

    def test_lookup_failure_is_reported(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = Exception("html down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = update_entry(_item(), "2026-10-23", entry_id="111")

        assert "修改失败" in result and "html down" in result


class TestSearchExerciseFailure:
    def test_catalog_failure_is_reported(self, mock_get_adapter):
        mock_get_adapter.search_exercises.side_effect = Exception("catalog down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = search_exercise("running")

        assert "搜索运动失败" in result and "catalog down" in result


class TestRecordExerciseFallbacks:
    def test_weight_read_failure_falls_back_to_70kg(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [{"id": "ex1", "description": "Running"}]
        mock_get_adapter.get_latest_weight.side_effect = Exception("measurements down")
        mock_get_adapter.record_exercise_entry.return_value = {"id": "x"}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = record_exercise(
                ExerciseModel(name="Running", exercise_type="cardio", date="2026-10-23", duration_min=30)
            )

        assert "按 70kg 估算" in result
        assert mock_get_adapter.record_exercise_entry.call_args[1]["calories"] > 0


class TestRecordMealOutput:
    def test_success_output_mentions_group_undo(self, mock_get_adapter):
        mock_get_adapter.record_meal.return_value = {
            "meal": "高蛋白套餐",
            "meal_id": 1,
            "group_id": "2026-10-23-1-123",
            "count": 2,
            "totals": {"calories": 600, "protein": 50, "carbs": 40, "fat": 20},
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = record_meal("2026-10-23", "lunch", 1)

        assert "高蛋白套餐" in result
        assert "delete_meal_group(date='2026-10-23', group_id='2026-10-23-1-123')" in result


class TestDeleteMealGroupBranches:
    GROUP = {
        "group_id": "g1",
        "meal": "套餐A",
        "meal_name": "Dinner",
        "timestamp": "2026-10-23T12:00:00",
        "items": ["Chicken"],
    }

    def test_unmatched_meal_name(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = [self.GROUP]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_meal_group("2026-10-23", meal_name="zzz")

        assert "没有套餐名包含" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_failed_delete_keeps_group_marker(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = [self.GROUP]
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1", "meal": "Dinner", "name": "Chicken"},
        ]
        mock_get_adapter.delete_diary_entry.return_value = False

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_meal_group("2026-10-23", group_id="g1")

        assert "撤销未完成" in result and "未找到 1 项" in result
        mock_get_adapter.remove_journal_group.assert_not_called()


class TestDeleteExerciseBranches:
    ITEMS = [
        {"type": "exercise_entry", "id": "e1", "exercise": {"description": "Running"}},
    ]

    def test_requires_target(self, mock_get_adapter):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_exercise("2026-10-23")

        assert "请提供 entry_id 或 name" in result

    def test_unknown_entry_id(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": self.ITEMS}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_exercise("2026-10-23", entry_id="nope")

        assert "没有找到 id 为" in result
        mock_get_adapter.delete_exercise_entry.assert_not_called()

    def test_no_name_match(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": self.ITEMS}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_exercise("2026-10-23", name="swimming")

        assert "没有找到名称包含" in result

    def test_delete_failure_is_reported(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": self.ITEMS}
        mock_get_adapter.delete_exercise_entry.return_value = False

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_exercise("2026-10-23", entry_id="e1")

        assert "删除失败" in result

    def test_read_failure_is_reported(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.side_effect = Exception("diary down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = delete_exercise("2026-10-23", entry_id="e1")

        assert "删除运动失败" in result and "diary down" in result


class TestGoalRenderingFallbacks:
    def test_goals_bad_value_renders_dash(self, mock_get_adapter):
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": "not-a-number",
            "protein": 200,
            "carbohydrates": 250,
            "fat": 80,
            "_source": "api",
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = get_goals("2026-10-23")

        assert "| 热量 | — |" in result

    def _summary_adapter(self, mock_get_adapter, goals):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [
                {
                    "type": "diary_meal",
                    "nutritional_contents": {
                        "energy": 500,
                        "protein": 30,
                        "carbohydrates": 50,
                        "fat": 15,
                        "sodium": 500,
                        "sugar": 20,
                    },
                },
            ]
        }
        mock_get_adapter.get_nutrition_goals.return_value = goals
        mock_get_adapter.get_food_entries_from_html.return_value = []
        mock_get_adapter.get_water.return_value = 250.0
        mock_get_adapter.session.get.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"items": [{"value": 70.5}]}),
        )

    def test_dict_goal_values_are_unwrapped(self, mock_get_adapter):
        self._summary_adapter(
            mock_get_adapter,
            {
                "energy": {"value": 2800},
                "protein": 210,
                "carbohydrates": 280,
                "fat": 93,
                "sodium": {"value": 2300},
                "sugar": 50,
            },
        )

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = get_daily_summary("2026-10-23")

        assert "🧂 钠: 500mg 已摄入 / 剩余 1800mg" in result
        assert "🍬 糖: 20.0g 已摄入 / 剩余 30.0g" in result
        assert "当前体重: 70.5kg" in result

    def test_bad_micronutrient_goal_is_ignored(self, mock_get_adapter):
        self._summary_adapter(
            mock_get_adapter,
            {
                "energy": {"value": 2800},
                "protein": 210,
                "carbohydrates": 280,
                "fat": 93,
                "sodium": "unknown",
                "sugar": 50,
            },
        )

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            result = get_daily_summary("2026-10-23")

        sodium_line = next(line for line in result.splitlines() if "钠" in line)
        assert "剩余" not in sodium_line
