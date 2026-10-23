import json
from unittest.mock import MagicMock, patch


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


class TestListMyMeals:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.get_my_meals.return_value = [
            {"meal_id": 4424592565, "name": "牛奶蛋白粉", "food_count": 2,
             "totals": {"calories": 727.0, "protein": 15.0, "carbs": 57.0, "fat": 47.0},
             "foods": []},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import list_my_meals
            result = list_my_meals()
            assert "4424592565" in result
            assert "牛奶蛋白粉" in result
            assert "727" in result

    def test_empty(self, mock_get_adapter):
        mock_get_adapter.get_my_meals.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import list_my_meals
            result = list_my_meals()
            assert "还没有自定义套餐" in result

    def test_error(self, mock_get_adapter):
        mock_get_adapter.get_my_meals.side_effect = Exception("401 Unauthorized")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import list_my_meals
            result = list_my_meals()
            assert "错误" in result


class TestRecordMealTool:
    def test_success(self, mock_get_adapter):
        mock_get_adapter.record_meal.return_value = {
            "status": "ok", "meal": "牛奶蛋白粉", "meal_id": 4424592565, "count": 2,
            "totals": {"calories": 727.0, "protein": 15.0, "carbs": 57.0, "fat": 47.0},
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_meal
            result = record_meal("2026-01-01", "dinner", 4424592565)
            assert "成功写入套餐" in result
            assert "牛奶蛋白粉" in result
            mock_get_adapter.record_meal.assert_called_once_with("2026-01-01", "dinner", 4424592565)

    def test_accepts_meal_name(self, mock_get_adapter):
        mock_get_adapter.record_meal.return_value = {
            "status": "ok", "meal": "Milk Protein Shake", "meal_id": 5083761427, "count": 2,
            "totals": {"calories": 239.0, "protein": 29.0, "carbs": 14.0, "fat": 8.0},
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_meal
            result = record_meal("2026-01-01", "snack", "Milk Protein Shake")
            assert "成功写入套餐" in result
            mock_get_adapter.record_meal.assert_called_once_with("2026-01-01", "snack", "Milk Protein Shake")

    def test_time_warning_different_date(self, mock_get_adapter):
        mock_get_adapter.record_meal.return_value = {
            "status": "ok", "meal": "测试套餐", "meal_id": 1, "count": 1,
            "totals": {"calories": 100.0, "protein": 1.0, "carbs": 1.0, "fat": 1.0},
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_meal
            result = record_meal("2025-01-01", "lunch", 1)
            assert "注意" in result

    def test_error(self, mock_get_adapter):
        mock_get_adapter.record_meal.side_effect = ValueError("未找到套餐「蛋白粉牛奶」。当前可用套餐: Milk Oatmeal(id=5083755153), Milk Protein Shake(id=5083761427)")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_meal
            result = record_meal("2026-01-01", "dinner", "蛋白粉牛奶")
            assert "错误" in result
            assert "5083761427" in result


class TestMealTimeWarnings:
    def test_date_mismatch(self):
        from mfp_adapter import _meal_time_warnings
        warnings = _meal_time_warnings("2020-01-01", "lunch")
        assert any("注意" in w for w in warnings)

    def test_meal_mismatch_uses_frozen_clock(self, monkeypatch):
        import datetime as dt

        from mfp_adapter import _meal_time_warnings

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 22, 12, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)
        warnings = _meal_time_warnings("2026-10-22", "dinner")
        assert any("通常对应 lunch" in w for w in warnings)

    def test_matching_meal_no_warning(self, monkeypatch):
        import datetime as dt

        from mfp_adapter import _meal_time_warnings

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 22, 12, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)
        assert _meal_time_warnings("2026-10-22", "lunch") == []


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
    def test_success(self, tmp_path, monkeypatch):
        from mfp_adapter import MFPAdapter, import_cookies

        target = tmp_path / "cookies.json"
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(target))
        cookies = json.dumps([{"name": "mfp-session", "value": "abc", "domain": ".myfitnesspal.com"}])
        result = import_cookies(cookies)
        assert "成功" in result
        assert json.loads(target.read_text(encoding="utf-8"))[0]["name"] == "mfp-session"

    def test_invalid_json(self):
        from mfp_adapter import import_cookies
        result = import_cookies("not json")
        assert "导入失败" in result

    def test_not_array(self):
        from mfp_adapter import import_cookies
        result = import_cookies('{"name": "cookie"}')
        assert "格式错误" in result

    def test_missing_session_token(self, tmp_path, monkeypatch):
        from mfp_adapter import MFPAdapter, import_cookies

        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(tmp_path / "cookies.json"))
        cookies = json.dumps([{"name": "other", "value": "abc"}])
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


ENTRIES_FIXTURE = [
    {"id": "1001", "name": "Rolled Oats, 1 cup", "meal": "Breakfast",
     "calories": 300, "protein": 10, "carbs": 54, "fat": 5, "sodium": 0, "sugar": 0},
    {"id": "1002", "name": "Fried Egg, 1 egg", "meal": "Breakfast",
     "calories": 102, "protein": 6, "carbs": 1, "fat": 8, "sodium": 136, "sugar": 0},
    {"id": "2001", "name": "Chicken Breast, 200g", "meal": "Lunch",
     "calories": 330, "protein": 62, "carbs": 0, "fat": 7, "sodium": 148, "sugar": 0},
]


class TestGetDiaryEntries:
    def test_lists_each_food_item(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = ENTRIES_FIXTURE

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "Rolled Oats, 1 cup" in result
            assert "Chicken Breast, 200g" in result

    def test_groups_by_meal_with_subtotals(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = ENTRIES_FIXTURE

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "Breakfast" in result
            assert "Lunch" in result
            assert "小计" in result
            # 早餐小计 300+102=402，午餐 330
            assert "402" in result
            assert "330" in result

    def test_day_total(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = ENTRIES_FIXTURE

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "全天合计" in result
            assert "732" in result

    def test_meal_type_filter(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = ENTRIES_FIXTURE

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23", "breakfast")
            assert "Rolled Oats, 1 cup" in result
            assert "Chicken Breast, 200g" not in result
            assert "402" in result

    def test_snack_maps_to_snacks(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "4001", "name": "Protein Bar", "meal": "Snacks",
             "calories": 200, "protein": 20, "carbs": 20, "fat": 5},
        ]

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23", "snack")
            assert "Protein Bar" in result

    def test_invalid_meal_type_rejected(self, mock_get_adapter):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23", "brunch")
            assert "brunch" in result
            assert "breakfast" in result.lower()

    def test_empty_meal_reports_nothing_recorded(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23", "dinner")
            assert "没有" in result

    def test_empty_day_reports_nothing_recorded(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = []

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "没有" in result

    def test_exception_handling(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = Exception("network error")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "获取" in result and "失败" in result


class TestGetGoals:
    def test_reports_goals_and_source(self, mock_get_adapter):
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2809.0}, "carbohydrates": 281.0, "fat": 93.0,
            "protein": 211.0, "sodium": 2300, "sugar": 50, "_source": "web",
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_goals
            result = get_goals("2026-10-23")
            assert "2809" in result
            assert "2300" in result
            assert "web" in result

    def test_missing_macro_renders_dash(self, mock_get_adapter):
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800.0}, "carbohydrates": 280.0, "fat": 93.0,
            "protein": 210.0, "_source": "api",
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_goals
            result = get_goals("2026-10-23")
            assert "钠" in result
            assert "—" in result

    def test_exception_handling(self, mock_get_adapter):
        mock_get_adapter.get_nutrition_goals.side_effect = Exception("boom")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_goals
            result = get_goals("2026-10-23")
            assert "失败" in result


class TestDailySummaryCorrections:
    def _goals(self):
        return {"energy": {"value": 2809.0}, "protein": 211.0, "carbohydrates": 281.0,
                "fat": 93.0, "sodium": 2300, "sugar": 50, "_source": "web"}

    def test_warns_when_goals_fail(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.get_nutrition_goals.side_effect = Exception("boom")
        mock_get_adapter.get_water.return_value = 0.0

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "默认值" in result

    def test_counts_diary_meal_once(self, mock_get_adapter):
        nc = {"energy": {"value": 300}, "protein": 10, "carbohydrates": 40, "fat": 5,
              "sodium": 200, "sugar": 3}
        mock_get_adapter.get_diary_data.return_value = {"items": [
            {"type": "diary_meal", "diary_meal": "Breakfast", "nutritional_contents": nc},
            {"type": "food_entry", "nutritional_contents": nc},
        ]}
        mock_get_adapter.get_nutrition_goals.return_value = self._goals()
        mock_get_adapter.get_water.return_value = 0.0

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-01-01")
            assert "- 300 (已吃)" in result

    def test_shows_sodium_sugar_water_exercise_steps(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": [
            {"type": "diary_meal", "nutritional_contents": {
                "energy": {"value": 300}, "protein": 10, "carbohydrates": 40, "fat": 5,
                "sodium": 628, "sugar": 4}},
            {"type": "exercise_entry", "duration": 600, "energy": {"value": 120},
             "exercise": {"description": "Running"}},
            {"type": "steps_aggregate", "steps": 725, "energy": {"value": 9}},
        ]}
        mock_get_adapter.get_nutrition_goals.return_value = self._goals()
        mock_get_adapter.get_water.return_value = 500.0

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-10-23")
            assert "628" in result          # 钠已摄入
            assert "饮水" in result and "500" in result
            assert "Running" in result       # 运动明细
            assert "725" in result           # 步数

    def test_water_failure_does_not_break_summary(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        mock_get_adapter.get_nutrition_goals.return_value = self._goals()
        mock_get_adapter.get_water.side_effect = Exception("water API down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-10-23")
            assert "营养预算总结" in result


class TestGetWater:
    def test_returns_milliliters(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"item": {"date": "2026-10-23", "milliliters": 750.0}}
        adapter.session.get.return_value = resp

        assert adapter.get_water("2026-10-23") == 750.0

    def test_missing_item_returns_zero(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {}
        adapter.session.get.return_value = resp

        assert adapter.get_water("2026-10-23") == 0.0


DELETE_FIXTURE = [
    {"id": "1001", "name": "Rolled Oats, 1 cup", "meal": "Breakfast",
     "calories": 300, "protein": 10, "carbs": 54, "fat": 5},
    {"id": "1002", "name": "Fried Egg, 1 egg", "meal": "Breakfast",
     "calories": 102, "protein": 6, "carbs": 1, "fat": 8},
    {"id": "2001", "name": "Chicken Breast, 200g", "meal": "Lunch",
     "calories": 330, "protein": 62, "carbs": 0, "fat": 7},
]


class TestDeleteEntry:
    def _call(self, mock_get_adapter, **kwargs):
        mock_get_adapter.get_food_entries_from_html.return_value = DELETE_FIXTURE
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_entry
            return delete_entry("2026-10-23", **kwargs)

    def test_delete_by_id(self, mock_get_adapter):
        mock_get_adapter.delete_diary_entry.return_value = True
        result = self._call(mock_get_adapter, entry_id="1002")
        mock_get_adapter.delete_diary_entry.assert_called_once_with("1002")
        assert "Fried Egg" in result

    def test_delete_by_id_syncs_journal(self, mock_get_adapter):
        mock_get_adapter.delete_diary_entry.return_value = True
        self._call(mock_get_adapter, entry_id="1002")
        mock_get_adapter._remove_from_journal.assert_called_once_with(
            "2026-10-23", "Breakfast", "Fried Egg, 1 egg")

    def test_delete_by_unique_name_substring(self, mock_get_adapter):
        mock_get_adapter.delete_diary_entry.return_value = True
        result = self._call(mock_get_adapter, name="oats")
        mock_get_adapter.delete_diary_entry.assert_called_once_with("1001")
        assert "Rolled Oats" in result

    def test_ambiguous_name_lists_candidates_and_deletes_nothing(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "1", "name": "Egg White", "meal": "Breakfast"},
            {"id": "2", "name": "Egg Yolk", "meal": "Breakfast"},
        ]
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_entry
            result = delete_entry("2026-10-23", name="egg")
            assert "多个" in result
            mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_missing_name_reports_and_deletes_nothing(self, mock_get_adapter):
        result = self._call(mock_get_adapter, name="pizza")
        assert "没有" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_requires_id_or_name(self, mock_get_adapter):
        result = self._call(mock_get_adapter)
        assert "entry_id" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_invalid_meal_type_rejected(self, mock_get_adapter):
        result = self._call(mock_get_adapter, entry_id="1001", meal_type="brunch")
        assert "brunch" in result

    def test_failed_delete_reports(self, mock_get_adapter):
        mock_get_adapter.delete_diary_entry.return_value = False
        result = self._call(mock_get_adapter, entry_id="1001")
        assert "失败" in result
        mock_get_adapter._remove_from_journal.assert_not_called()


class TestDiaryEntryIds:
    def test_entries_expose_ids(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = DELETE_FIXTURE
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_diary_entries
            result = get_diary_entries("2026-10-23")
            assert "1001" in result
            assert "ID" in result


class TestDeleteLastEntrySemantics:
    def test_meal_type_deletes_exactly_count(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = DELETE_FIXTURE
        mock_get_adapter.delete_diary_entry.return_value = True
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            delete_last_entry("2026-10-23", meal_type="breakfast")
            assert mock_get_adapter.delete_diary_entry.call_count == 1

    def test_all_in_meal_deletes_whole_meal(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = DELETE_FIXTURE
        mock_get_adapter.delete_diary_entry.return_value = True
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            delete_last_entry("2026-10-23", meal_type="breakfast", all_in_meal=True)
            assert mock_get_adapter.delete_diary_entry.call_count == 2

    def test_delete_syncs_journal(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = DELETE_FIXTURE
        mock_get_adapter.delete_diary_entry.return_value = True
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_last_entry
            delete_last_entry("2026-10-23", meal_type="lunch")
            mock_get_adapter._remove_from_journal.assert_called_once_with(
                "2026-10-23", "Lunch", "Chicken Breast, 200g")


class TestHealthCheck:
    def _prepare(self, mock_get_adapter):
        mock_get_adapter._ensure_token_valid.return_value = True
        mock_get_adapter._load_config.return_value = {
            "supplements": {"a": {}}, "common_foods": {"b": {}},
            "regional_foods": {}, "routines": {}, "meal_combos": {},
        }
        mock_get_adapter.usda.search.return_value = [{"name": "Oats"}]
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2809.0}, "protein": 211.0, "_source": "api"}
        mock_get_adapter.get_water.return_value = 0.0

    def test_reports_every_check(self, mock_get_adapter):
        self._prepare(mock_get_adapter)
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import health_check
            result = health_check()
            for expected in ("Cookie", "配置", "USDA", "目标", "饮水", "结论"):
                assert expected in result

    def test_all_green_conclusion(self, mock_get_adapter):
        self._prepare(mock_get_adapter)
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import health_check
            assert "全部正常" in health_check()

    def test_token_failure_is_reported_not_raised(self, mock_get_adapter):
        self._prepare(mock_get_adapter)
        mock_get_adapter._ensure_token_valid.side_effect = Exception("expired")
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import health_check
            result = health_check()
            assert "❌" in result
            assert "get_cookie_guide" in result

    def test_usda_failure_is_degraded_but_not_blocking(self, mock_get_adapter):
        self._prepare(mock_get_adapter)
        mock_get_adapter.usda.search.return_value = []
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import health_check
            result = health_check()
            assert "⚠️" in result


class TestSummaryConsistency:
    def _setup(self, mock_get_adapter, html_entries):
        mock_get_adapter.get_diary_data.return_value = {"items": [
            {"type": "diary_meal", "nutritional_contents": {
                "energy": {"value": 300}, "protein": 10, "carbohydrates": 40, "fat": 5}},
        ]}
        mock_get_adapter.get_nutrition_goals.return_value = {
            "energy": {"value": 2800}, "protein": 210, "carbohydrates": 280, "fat": 93}
        mock_get_adapter.get_water.return_value = 0.0
        mock_get_adapter.get_food_entries_from_html.return_value = html_entries

    def test_warns_when_v2_and_html_disagree(self, mock_get_adapter):
        self._setup(mock_get_adapter, [{"calories": 450}])

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-10-23")
            assert "口径" in result
            assert "450" in result

    def test_silent_when_totals_match(self, mock_get_adapter):
        self._setup(mock_get_adapter, [{"calories": 305}])

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            result = get_daily_summary("2026-10-23")
            assert "口径" not in result

    def test_html_failure_does_not_break_summary(self, mock_get_adapter):
        self._setup(mock_get_adapter, [])
        mock_get_adapter.get_food_entries_from_html.side_effect = Exception("html down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import get_daily_summary
            assert "营养预算总结" in get_daily_summary("2026-10-23")


class TestWriteDateWarnings:
    def _freeze(self, monkeypatch):
        import datetime as dt

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 23, 9, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)

    def test_record_measurement_warns_on_future_date(self, mock_get_adapter, monkeypatch):
        self._freeze(monkeypatch)
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_measurement
            result = record_measurement("water", 250, "2026-12-01")
            assert "未来" in result

    def test_record_exercise_warns_on_future_date(self, mock_get_adapter, monkeypatch):
        self._freeze(monkeypatch)
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import ExerciseModel, record_exercise
            result = record_exercise(ExerciseModel(
                name="Running", exercise_type="cardio", date="2026-12-01", calories_burned=300))
            assert "未来" in result

    def test_record_nutrition_warns_on_long_past(self, mock_get_adapter, monkeypatch):
        self._freeze(monkeypatch)
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-09-01", "breakfast", ["Oats"])
            assert "补录" in result
