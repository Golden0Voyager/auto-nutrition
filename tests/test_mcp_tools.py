import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestRecordNutritionTool:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-01-01", "lunch", [{"name": "Apple", "calories": 95}])
            assert "成功写入" in result

    def test_exception_handling(self, mock_get_adapter):
        mock_get_adapter.record_nutrition.side_effect = Exception("network error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-01-01", "lunch", [{"name": "Apple"}])
            assert "错误" in result

    def test_time_warning_different_date(self, mock_get_adapter):
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2025-01-01", "lunch", [{"name": "Apple", "calories": 95}])
            assert "注意" in result

    def test_string_items(self, mock_get_adapter):
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-01-01", "dinner", ["100g Chicken"])
            assert "成功写入" in result


class TestGetDailySummary:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [
                {"type": "diary_meal", "nutritional_contents": {"energy": {"value": 500}, "protein": 30, "carbohydrates": 50, "fat": 15}},
            ]
        }
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800},
            "protein": 210,
            "carbohydrates": 280,
            "fat": 93,
        }
        mock_adapter_session = MagicMock()
        mock_adapter_session.get.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"items": [{"value": 75}]})
        )
        mock_get_adapter.session = mock_adapter_session

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "营养预算总结" in result

    def test_goals_fetch_failure(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.get_nutrition_goals.side_effect = Exception("API error")
        mock_get_adapter.session.get.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"items": []})
        )

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "营养预算总结" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.side_effect = Exception("network error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "获取总结失败" in result


class TestGetCookieGuide:
    def test_returns_guide(self):
        from mfp_adapter import get_cookie_guide
        result = get_cookie_guide()
        assert "Cookie" in result
        assert "手动" in result


class TestImportCookies:
    def test_success(self):
        cookies = json.dumps([{"name": "mfp-session", "value": "abc", "domain": ".myfitnesspal.com"}])
        from mfp_adapter import import_cookies
        result = import_cookies(cookies)
        assert "成功" in result

    def test_invalid_json(self):
        from mfp_adapter import import_cookies
        result = import_cookies("not json")
        assert "导入失败" in result

    def test_not_array(self):
        from mfp_adapter import import_cookies
        result = import_cookies('{"name": "cookie"}')
        assert "格式错误" in result

    def test_missing_session_token(self, cookies_file, monkeypatch):
        cookies = json.dumps([{"name": "other", "value": "abc"}])
        monkeypatch.setattr("mfp_adapter.os.path.join", lambda *args: cookies_file)
        from mfp_adapter import import_cookies
        result = import_cookies(cookies)
        assert "成功" in result


class TestGetNutritionTrends:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [
                {"type": "diary_meal", "nutritional_contents": {"energy": {"value": 500}, "protein": 30, "carbohydrates": 50, "fat": 15}},
            ]
        }
        mock_get_adapter.JOURNAL_FILE = "/tmp/nonexistent.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=False):
                from mfp_adapter import get_nutrition_trends
                result = get_nutrition_trends(3)
                assert "趋势分析" in result

    def test_days_clamping(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.JOURNAL_FILE = "/tmp/nonexistent.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=False):
                from mfp_adapter import get_nutrition_trends
                result = get_nutrition_trends(100)  # should be clamped to 30
                assert "趋势分析" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.side_effect = Exception("error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_nutrition_trends
            result = get_nutrition_trends(7)
            assert "获取趋势失败" in result


class TestGetFoodConfig:
    def test_success(self, mock_get_adapter):
        mock_get_adapter._load_config.return_value = {
            "common_foods": {"apple": {"name": "Apple"}},
            "regional_foods": {},
            "supplements": {},
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_food_config
            result = get_food_config()
            assert "本地食物库配置" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter._load_config.side_effect = Exception("error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_food_config
            result = get_food_config()
            assert "获取配置失败" in result


class TestDeleteLastEntry:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1001", "name": "Apple", "meal": "Lunch"},
            {"id": "1002", "name": "Banana", "meal": "Lunch"},
        ]
        mock_get_adapter.delete_diary_entry.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01", count=1)
            assert "成功删除" in result

    def test_no_entries(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01")
            assert "没有找到" in result

    def test_with_meal_type(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1001", "name": "Apple", "meal": "Breakfast"},
            {"id": "2001", "name": "Rice", "meal": "Lunch"},
        ]
        mock_get_adapter.delete_diary_entry.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01", meal_type="breakfast")
            assert "成功删除" in result

    def test_no_matching_meal(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1001", "name": "Apple", "meal": "Breakfast"},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01", meal_type="dinner")
            assert "没有找到" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = Exception("error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01")
            assert "删除失败" in result


class TestRecordExercise:
    def test_cardio(self, mock_get_adapter):
        mock_get_adapter._ensure_token_valid = MagicMock()
        mock_get_adapter._post_diary_entry = MagicMock()

        from mfp_adapter import ExerciseModel
        exercise = ExerciseModel(
            name="Running",
            exercise_type="cardio",
            date="2026-01-01",
            calories_burned=300,
            duration_min=30,
        )

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_exercise
            result = record_exercise(exercise)
            assert "成功记录" in result

    def test_strength(self, mock_get_adapter):
        mock_get_adapter._ensure_token_valid = MagicMock()
        mock_get_adapter._post_diary_entry = MagicMock()

        from mfp_adapter import ExerciseModel
        exercise = ExerciseModel(
            name="Bench Press",
            exercise_type="strength",
            date="2026-01-01",
            sets=4,
            reps=10,
            weight_kg=80,
        )

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_exercise
            result = record_exercise(exercise)
            assert "成功记录" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter._ensure_token_valid.side_effect = Exception("token expired")

        from mfp_adapter import ExerciseModel
        exercise = ExerciseModel(name="Run", exercise_type="cardio", date="2026-01-01")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_exercise
            result = record_exercise(exercise)
            assert "失败" in result


class TestRecordMeasurement:
    def test_weight(self, mock_get_adapter):
        mock_get_adapter.record_weight.return_value = {"status": "ok"}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_measurement
            result = record_measurement("weight", 75.5, "2026-01-01")
            assert "记录成功" in result

    def test_water(self, mock_get_adapter):
        mock_get_adapter.record_water.return_value = {"status": "ok"}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_measurement
            result = record_measurement("water", 500, "2026-01-01")
            assert "成功记录" in result

    def test_unknown_type(self, mock_get_adapter):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_measurement
            result = record_measurement("unknown", 100, "2026-01-01")
            assert "未知类型" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.record_weight.side_effect = Exception("error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_measurement
            result = record_measurement("weight", 75, "2026-01-01")
            assert "失败" in result


class TestLookupFoodNutrition:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.usda.search.return_value = [
            {"name": "Apple, raw", "calories_per_100g": 52, "macros_per_100g": {"protein": 0.3}}
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import lookup_food_nutrition
            result = lookup_food_nutrition("Apple")
            assert "USDA 查询结果" in result

    def test_no_results(self, mock_get_adapter):
        mock_get_adapter.usda.search.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import lookup_food_nutrition
            result = lookup_food_nutrition("xyznonexistent")
            assert "未找到" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.usda.search.side_effect = Exception("db error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import lookup_food_nutrition
            result = lookup_food_nutrition("Apple")
            assert "查询失败" in result


class TestGetCurrentTime:
    def test_returns_json(self):
        from mfp_adapter import get_current_time
        result = get_current_time()
        data = json.loads(result)
        assert "local" in data
        assert "utc" in data
        assert "suggested_meal_type" in data
        assert "date" in data
        assert "day_of_week" in data

    def test_suggested_meal_type(self):
        from mfp_adapter import get_current_time
        result = get_current_time()
        data = json.loads(result)
        assert data["suggested_meal_type"] in ["breakfast", "lunch", "dinner", "snack"]

    def test_breakfast_time(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 7
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01 07:30:00" if fmt == "%Y-%m-%d %H:%M:%S" else "2026-01-01" if fmt == "%Y-%m-%d" else "Wednesday" if fmt == "%A" else "07:30" if fmt == "%H:%M" else ""
            mock_dt.utcnow.return_value.strftime.return_value = "2026-01-01 07:30:00"
            from mfp_adapter import get_current_time
            result = get_current_time()
            data = json.loads(result)
            assert data["suggested_meal_type"] == "breakfast"

    def test_lunch_time(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 12
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01 12:00:00" if fmt == "%Y-%m-%d %H:%M:%S" else "2026-01-01" if fmt == "%Y-%m-%d" else "Wednesday" if fmt == "%A" else "12:00" if fmt == "%H:%M" else ""
            mock_dt.utcnow.return_value.strftime.return_value = "2026-01-01 12:00:00"
            from mfp_adapter import get_current_time
            result = get_current_time()
            data = json.loads(result)
            assert data["suggested_meal_type"] == "lunch"

    def test_dinner_time(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 19
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01 19:00:00" if fmt == "%Y-%m-%d %H:%M:%S" else "2026-01-01" if fmt == "%Y-%m-%d" else "Wednesday" if fmt == "%A" else "19:00" if fmt == "%H:%M" else ""
            mock_dt.utcnow.return_value.strftime.return_value = "2026-01-01 19:00:00"
            from mfp_adapter import get_current_time
            result = get_current_time()
            data = json.loads(result)
            assert data["suggested_meal_type"] == "dinner"

    def test_snack_time(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 15
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01 15:00:00" if fmt == "%Y-%m-%d %H:%M:%S" else "2026-01-01" if fmt == "%Y-%m-%d" else "Wednesday" if fmt == "%A" else "15:00" if fmt == "%H:%M" else ""
            mock_dt.utcnow.return_value.strftime.return_value = "2026-01-01 15:00:00"
            from mfp_adapter import get_current_time
            result = get_current_time()
            data = json.loads(result)
            assert data["suggested_meal_type"] == "snack"

    def test_night_snack_time(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01 23:00:00" if fmt == "%Y-%m-%d %H:%M:%S" else "2026-01-01" if fmt == "%Y-%m-%d" else "Wednesday" if fmt == "%A" else "23:00" if fmt == "%H:%M" else ""
            mock_dt.utcnow.return_value.strftime.return_value = "2026-01-01 23:00:00"
            from mfp_adapter import get_current_time
            result = get_current_time()
            data = json.loads(result)
            assert data["suggested_meal_type"] == "snack"

    def test_exception_handling(self):
        with patch("mfp_adapter.datetime") as mock_dt:
            mock_dt.now.side_effect = Exception("time error")
            from mfp_adapter import get_current_time
            result = get_current_time()
            assert "获取时间失败" in result


class TestGetDailySummaryEdgeCases:
    def test_exercise_entries(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [
                {"type": "exercise_entry", "energy": {"value": 300}},
                {"type": "diary_meal", "nutritional_contents": {"energy": {"value": 500}, "protein": 30, "carbohydrates": 50, "fat": 15}},
            ]
        }
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800}, "protein": 210, "carbohydrates": 280, "fat": 93,
        }
        mock_adapter_session = MagicMock()
        mock_adapter_session.get.return_value = MagicMock(raise_for_status=MagicMock(), json=MagicMock(return_value={"items": []}))
        mock_get_adapter.session = mock_adapter_session

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "营养预算总结" in result

    def test_food_entry_type(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [{"type": "food_entry", "nutritional_contents": {"energy": {"value": 200}, "protein": 15, "carbohydrates": 20, "fat": 8}}]
        }
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800}, "protein": 210, "carbohydrates": 280, "fat": 93,
        }
        mock_adapter_session = MagicMock()
        mock_adapter_session.get.return_value = MagicMock(raise_for_status=MagicMock(), json=MagicMock(return_value={"items": []}))
        mock_get_adapter.session = mock_adapter_session

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "营养预算总结" in result

    def test_weight_success(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800}, "protein": 210, "carbohydrates": 280, "fat": 93,
        }
        mock_adapter_session = MagicMock()
        weight_resp = MagicMock()
        weight_resp.raise_for_status = MagicMock()
        weight_resp.json.return_value = {"items": [{"value": 75.5}]}
        mock_adapter_session.get.return_value = weight_resp
        mock_get_adapter.session = mock_adapter_session

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "75.5" in result

    def test_weight_fetch_fails(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800}, "protein": 210, "carbohydrates": 280, "fat": 93,
        }
        mock_adapter_session = MagicMock()
        mock_adapter_session.get.side_effect = Exception("weight API error")
        mock_get_adapter.session = mock_adapter_session

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "营养预算总结" in result


class TestDeleteLastEntryEdgeCases:
    def test_delete_with_count_and_meal(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1001", "name": "Apple", "meal": "Breakfast"},
            {"id": "1002", "name": "Banana", "meal": "Breakfast"},
            {"id": "1003", "name": "Egg", "meal": "Breakfast"},
        ]
        mock_get_adapter.delete_diary_entry.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01", count=2, meal_type="breakfast")
            assert "成功删除" in result

    def test_delete_no_successful_deletions(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [{"id": "1001", "name": "Apple", "meal": "Lunch"}]
        mock_get_adapter.delete_diary_entry.return_value = False

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01")
            assert "未能成功删除" in result

    def test_delete_entry_without_id(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [{"id": None, "name": "Apple", "meal": "Lunch"}]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            result = delete_last_entry("2026-01-01")
            assert "未能成功删除" in result


class TestGetNutritionTrendsEdgeCases:
    def _make_journal_mock(self, journal_data):
        mock_adapter = MagicMock()
        mock_adapter.get_diary_data.return_value = {"items": []}
        mock_adapter.JOURNAL_FILE = "/tmp/test_journal.json"
        mock_adapter.access_token = "fake-token"
        mock_adapter.user_id = 12345
        mock_adapter.token_expires_at = 999999999999
        mock_adapter.BASE_URL = "https://api.myfitnesspal.com/v2"
        mock_adapter._JOURNAL_MAX_ENTRIES = 200
        mock_adapter.usda = MagicMock()
        mock_adapter.session = MagicMock()
        mock_adapter._config = {}
        return mock_adapter, journal_data

    def test_local_journal_loading(self, mock_get_adapter):
        journal_data = [{"date": "2026-01-01", "meal_name": "Lunch", "items": [{"name": "Apple", "macros": {"sodium": 10, "potassium": 200}}]}]
        mock_get_adapter.JOURNAL_FILE = "/tmp/test_journal.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=True):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = lambda s: s
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.read = MagicMock(return_value=json.dumps(journal_data))
                    from mfp_adapter import get_nutrition_trends
                    result = get_nutrition_trends(1)
                    assert "趋势分析" in result

    def test_local_journal_preload_fails(self, mock_get_adapter):
        mock_get_adapter.JOURNAL_FILE = "/tmp/test_journal.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=True):
                with patch("builtins.open", side_effect=Exception("read error")):
                    from mfp_adapter import get_nutrition_trends
                    result = get_nutrition_trends(1)
                    assert "趋势分析" in result

    def test_food_entry_micro_fields(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [{"type": "food_entry", "nutritional_contents": {"energy": {"value": 100}, "sodium": {"value": 50}, "potassium": 100}}]
        }
        mock_get_adapter.JOURNAL_FILE = "/tmp/nonexistent.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=False):
                from mfp_adapter import get_nutrition_trends
                result = get_nutrition_trends(1)
                assert "趋势分析" in result

    def test_micro_dict_value(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {
            "items": [{"type": "diary_meal", "nutritional_contents": {"energy": {"value": 100}, "sodium": {"value": 50}, "potassium": {"value": 100}}}]
        }
        mock_get_adapter.JOURNAL_FILE = "/tmp/nonexistent.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=False):
                from mfp_adapter import get_nutrition_trends
                result = get_nutrition_trends(1)
                assert "趋势分析" in result

    def test_local_journal_micro_enhancement(self, mock_get_adapter):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        journal_data = [{"date": today, "meal_name": "Lunch", "items": [{"name": "Apple", "macros": {"sodium": 10, "potassium": 200, "protein": 5, "carbs": 10}}]}]
        mock_get_adapter.JOURNAL_FILE = "/tmp/test_journal.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=True):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = lambda s: s
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.read = MagicMock(return_value=json.dumps(journal_data))
                    from mfp_adapter import get_nutrition_trends
                    result = get_nutrition_trends(1)
                    assert "趋势分析" in result

    def test_empty_trends_returns_message(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.JOURNAL_FILE = "/tmp/nonexistent.json"

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.os.path.exists", return_value=False):
                with patch("builtins.range", return_value=[]):
                    from mfp_adapter import get_nutrition_trends
                    result = get_nutrition_trends(7)
                    assert "没有找到趋势数据" in result


class TestRecordNutritionTimeWarning:
    def test_time_warning_meal_mismatch(self, mock_get_adapter):
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            with patch("mfp_adapter.datetime") as mock_dt:
                mock_dt.now.return_value.hour = 12
                mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2026-01-01" if fmt == "%Y-%m-%d" else "12:00" if fmt == "%H:%M" else ""
                from mfp_adapter import record_nutrition
                result = record_nutrition("2026-01-01", "dinner", [{"name": "Food", "calories": 100}])
                assert "提示" in result
