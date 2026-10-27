import json
import os
from unittest.mock import MagicMock, patch

import pytest

from mfp_adapter import MFPAdapter
from tests.conftest import mock_create_food, mock_post_diary


@pytest.fixture
def adapter_with_config(tmp_path):
    """Adapter with supplements_config for config-matched tests."""
    a = MFPAdapter.__new__(MFPAdapter)
    a.BASE_URL = "https://api.myfitnesspal.com/v2"
    a.JOURNAL_FILE = str(tmp_path / "journal.json")
    a.FOOD_CACHE_FILE = str(tmp_path / "food_cache.json")
    a._food_cache = None
    a._JOURNAL_MAX_ENTRIES = 200
    a.usda = MagicMock()
    a.usda.search.return_value = []
    a.session = MagicMock()
    a.session.cookies = {"mfp-session": "x"}
    a.session.headers = {}
    a.access_token = "fake-token"
    a.user_id = 12345
    a.token_expires_at = 999999999999
    a._config = {
        "supplements": {
            "whey": {
                "name": "Whey Protein",
                "calories": 120,
                "macros": {"protein": 24, "carbs": 3, "fat": 1.5},
                "aliases": ["蛋白粉"],
            },
        },
        "common_foods": {
            "apple": {
                "name": "Apple",
                "calories": 95,
                "macros": {"protein": 0.5, "carbs": 25, "fat": 0.3},
                "aliases": ["苹果"],
            },
        },
        "meal_combos": {},
        "routines": {},
    }
    a._load_config = lambda: a._config
    return a


class TestRecordNutrition:
    def test_dict_input_with_calories(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Test Food", "calories": 100, "macros": {"protein": 10, "carbs": 5, "fat": 2}}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)

        assert result["status"] == "ok"
        assert result["count"] == 1

    def test_string_input(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = ["100g Chicken Breast"]
        result = adapter.record_nutrition("2026-01-01", "dinner", items)
        assert result["status"] == "ok"

    def test_string_input_with_kcal(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = ["100g Chicken Breast (165 kcal)"]
        result = adapter.record_nutrition("2026-01-01", "dinner", items)
        assert result["status"] == "ok"

    def test_string_input_kcal_format2(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = ["100g Chicken Breast 165kcal"]
        result = adapter.record_nutrition("2026-01-01", "dinner", items)
        assert result["status"] == "ok"

    def test_config_matched_item(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)

        items = [{"name": "Whey Protein", "calories": 100}]
        result = adapter_with_config.record_nutrition("2026-01-01", "snack", items)
        assert result["status"] == "ok"

    def test_usda_fallback(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        adapter.usda.search.return_value = [
            {"name": "Apple, raw", "calories_per_100g": 52, "macros_per_100g": {"protein": 0.3, "carbs": 13.8, "fat": 0.2}}
        ]

        items = [{"name": "Custom Unique Food XYZ"}]
        result = adapter.record_nutrition("2026-01-01", "snack", items)
        assert result["status"] == "ok"
        adapter.usda.search.assert_called()

    def test_ai_fallback(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Custom Food", "calories": 200, "macros": {"protein": 15}}]
        result = adapter.record_nutrition("2026-01-01", "snack", items)
        assert result["status"] == "ok"

    def test_zero_calories_warning(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Unknown Food"}]
        result = adapter.record_nutrition("2026-01-01", "snack", items)
        assert result["status"] == "ok"
        assert "warnings" in result

    def test_multiple_items(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [
            {"name": "Food A", "calories": 100},
            {"name": "Food B", "calories": 200},
            {"name": "Food C", "calories": 150},
        ]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["count"] == 3

    def test_meal_type_breakfast(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Egg", "calories": 90}]
        adapter.record_nutrition("2026-01-01", "breakfast", items)
        call_args = adapter._post_diary_entry.call_args
        entry = call_args[0][0]
        assert entry["meal_name"] == "Breakfast"

    def test_meal_type_lunch(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Rice", "calories": 200}]
        adapter.record_nutrition("2026-01-01", "lunch", items)
        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["meal_name"] == "Lunch"

    def test_meal_type_dinner(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Fish", "calories": 200}]
        adapter.record_nutrition("2026-01-01", "dinner", items)
        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["meal_name"] == "Dinner"

    def test_meal_type_snack(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Banana", "calories": 100}]
        adapter.record_nutrition("2026-01-01", "snack", items)
        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["meal_name"] == "Snacks"

    def test_meal_type_unknown_defaults_to_snacks(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "X", "calories": 100}]
        adapter.record_nutrition("2026-01-01", "brunch", items)
        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["meal_name"] == "Snacks"

    def test_create_food_error_handling(self, adapter):
        mock_post_diary(adapter)
        adapter._create_custom_food = MagicMock(side_effect=Exception("API error"))

        items = [{"name": "Food", "calories": 100}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["count"] == 1
        assert result["status"] == "ok"

    def test_http_error_on_create_food(self, adapter):
        mock_post_diary(adapter)
        import requests
        resp = MagicMock()
        resp.text = "Bad Request"
        exc = requests.exceptions.HTTPError(response=resp)
        adapter._create_custom_food = MagicMock(side_effect=exc)

        items = [{"name": "Food", "calories": 100}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["status"] == "ok"

    def test_serving_ratio_scaling(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        adapter.usda.search.return_value = [
            {"name": "Apple", "calories_per_100g": 52, "macros_per_100g": {"protein": 0.3}}
        ]

        items = [{"name": "Custom Unique Food", "serving_ratio": 2.0}]
        result = adapter.record_nutrition("2026-01-01", "snack", items)
        assert result["status"] == "ok"

    def test_local_journal_written(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Food", "calories": 100}]
        adapter.record_nutrition("2026-01-01", "lunch", items)
        assert os.path.exists(adapter.JOURNAL_FILE)

    def test_local_journal_content(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Apple", "calories": 95}]
        adapter.record_nutrition("2026-01-01", "snack", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert len(journal) == 1
        assert journal[0]["date"] == "2026-01-01"
        assert journal[0]["meal_name"] == "Snacks"
        assert len(journal[0]["items"]) == 1

    def test_journal_max_entries(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter._JOURNAL_MAX_ENTRIES = 3

        for i in range(5):
            items = [{"name": f"Food {i}", "calories": 100}]
            adapter.record_nutrition("2026-01-01", "lunch", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert len(journal) == 3


class TestComboExpansion:
    def test_combo_match(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config._config["meal_combos"] = {
            "morning_stack": {
                "name": "晨补",
                "aliases": ["晨间补剂", "补剂"],
                "items": [
                    {"name": "Fish Oil", "calories": 10, "macros": {"carbs": 0, "protein": 0, "fat": 1.1}},
                    {"name": "Vitamin B", "calories": 0, "macros": {"carbs": 0, "protein": 0, "fat": 0}},
                ],
            },
        }

        items = [{"name": "晨间补剂"}]
        result = adapter_with_config.record_nutrition("2026-01-01", "breakfast", items)
        assert result["count"] == 2

    def test_routine_match(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config._config["routines"] = {
            "night_stack": {
                "name": "晚补",
                "aliases": ["睡前补剂"],
                "items": [
                    {"name": "Calcium", "calories": 0, "macros": {"carbs": 0, "protein": 0, "fat": 0}},
                ],
            },
        }

        items = [{"name": "睡前补剂"}]
        result = adapter_with_config.record_nutrition("2026-01-01", "dinner", items)
        assert result["count"] == 1

    def test_specific_routine_beats_generic_alias(self, adapter_with_config):
        """「睡前补剂」必须展开成 night_stack，不能被先出现的泛化别名「补剂」抢走。"""
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config._config["meal_combos"] = {
            "morning_stack": {
                "name": "晨补",
                "aliases": ["补剂"],
                "items": [
                    {"name": "Fish Oil", "calories": 10, "macros": {"carbs": 0, "protein": 0, "fat": 1.1}},
                    {"name": "Vitamin B", "calories": 0, "macros": {"carbs": 0, "protein": 0, "fat": 0}},
                ],
            },
        }
        adapter_with_config._config["routines"] = {
            "night_stack": {
                "name": "晚补",
                "aliases": ["睡前补剂"],
                "items": [
                    {"name": "ZMA", "calories": 4.8, "macros": {"carbs": 1.2, "protein": 0, "fat": 0}},
                ],
            },
        }

        items = [{"name": "睡前补剂"}]
        result = adapter_with_config.record_nutrition("2026-01-01", "snack", items)

        # 命中泛化别名会展开成 2 项（晨补），命中具体别名只展开 1 项（晚补）
        assert result["count"] == 1

    def test_combo_with_ratio(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config._config["meal_combos"] = {
            "stack": {
                "name": "Stack",
                "aliases": [],
                "items": [
                    {"name": "Item", "calories": 100, "macros": {"protein": 10}},
                ],
            },
        }

        items = [{"name": "Stack", "serving_ratio": 0.5}]
        result = adapter_with_config.record_nutrition("2026-01-01", "snack", items)
        assert result["count"] == 1

    def test_combo_with_micros(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config._config["meal_combos"] = {
            "stack": {
                "name": "Stack",
                "aliases": [],
                "items": [
                    {"name": "Item", "calories": 50, "macros": {"protein": 5}, "micros": {"sodium": 100}},
                ],
            },
        }

        items = [{"name": "Stack"}]
        result = adapter_with_config.record_nutrition("2026-01-01", "snack", items)
        assert result["count"] == 1


class TestComboDeclaredValues:
    """组合/套餐自带的数值是用户手写定稿：配置层不得悄悄改写，只允许告警。

    这是 P0 修复的回归防线 —— 修复前 `煎蛋 180 kcal` 会被配置层的
    `Fried Egg 90 kcal` 覆盖，且没有任何提示。
    """

    def _adapter(self, adapter_with_config):
        adapter_with_config._config["common_foods"]["fried_egg"] = {
            "name": "Fried Egg",
            "calories": 90,
            "macros": {"protein": 6.3, "carbs": 0.6, "fat": 7.0},
            "aliases": ["煎蛋"],
        }
        return adapter_with_config

    def _breakfast_combo(self, adapter, items):
        adapter._config["meal_combos"] = {
            "my_breakfast": {"name": "我的早餐", "aliases": ["早餐组合"], "items": items},
        }

    def test_declared_calories_beat_config(self, adapter_with_config):
        adapter = self._adapter(adapter_with_config)
        mock_create_food(adapter)
        mock_post_diary(adapter)
        self._breakfast_combo(adapter, [
            {"name": "Fried Egg (煎鸡蛋)", "calories": 180,
             "macros": {"protein": 12.6, "carbs": 1.2, "fat": 14.0}},
        ])

        result = adapter.record_nutrition("2026-01-01", "breakfast", [{"name": "早餐组合"}])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 180
        assert written["macros"]["protein"] == 12.6
        assert written["name"] == "Fried Egg (煎鸡蛋)"  # 保留用户写的名字
        assert result["count"] == 1
        # 冲突必须告警，但不能覆盖
        assert any("套餐声明值 180" in w and "90" in w for w in result["warnings"])

    def test_longer_config_name_wins_over_a_short_declared_alias(self, adapter_with_config):
        """配置里的正式产品名比组合里的简称更完整时，用配置名。

        回归：routines 里写的是「鱼油」，配置里是
        「Fish Oil (Swisse 无腥味野生鱼油 1粒 - EPA 180 / DHA 120)」。
        Level 0 无条件保留原名会让 MFP 里只剩「鱼油」，看不出几粒、什么产品。
        """
        adapter = adapter_with_config
        adapter._config["common_foods"]["fish_oil"] = {
            "name": "Fish Oil (Swisse 无腥味野生鱼油 1粒 - EPA 180 / DHA 120)",
            "calories": 10,
            "macros": {"fat": 1.1},
            "aliases": ["鱼油"],
        }
        mock_create_food(adapter)
        mock_post_diary(adapter)
        self._breakfast_combo(adapter, [
            {"name": "鱼油", "calories": 10, "macros": {"fat": 1.1}},
        ])

        adapter.record_nutrition("2026-01-01", "breakfast", [{"name": "早餐组合"}])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["name"] == "Fish Oil (Swisse 无腥味野生鱼油 1粒 - EPA 180 / DHA 120)"
        assert written["calories"] == 10

    def test_ratio_scales_declared_value_without_false_conflict(self, adapter_with_config):
        """2 份套餐：声明值与配置同比放大，不应误报冲突。"""
        adapter = self._adapter(adapter_with_config)
        mock_create_food(adapter)
        mock_post_diary(adapter)
        self._breakfast_combo(adapter, [
            # 声明值与配置一致（90），乘 2 份后两边都是 180
            {"name": "Fried Egg (煎鸡蛋)", "calories": 90,
             "macros": {"protein": 6.3, "carbs": 0.6, "fat": 7.0}},
        ])

        result = adapter.record_nutrition(
            "2026-01-01", "breakfast", [{"name": "早餐组合", "serving_ratio": 2}]
        )

        assert adapter._create_custom_food.call_args[0][0]["calories"] == 180
        assert "warnings" not in result

    def test_zero_declared_falls_back_to_config(self, adapter_with_config):
        """声明 0 kcal 视为「未填」，仍按配置兜底。"""
        adapter = adapter_with_config
        mock_create_food(adapter)
        mock_post_diary(adapter)
        self._breakfast_combo(adapter, [
            {"name": "Apple", "calories": 0, "macros": {}},
        ])

        result = adapter.record_nutrition("2026-01-01", "breakfast", [{"name": "早餐组合"}])

        assert adapter._create_custom_food.call_args[0][0]["calories"] == 95
        assert "warnings" not in result

    def test_declared_kept_when_config_has_no_match(self, adapter_with_config):
        """配置里没有的条目，声明值原样写入，不产生冲突告警。"""
        adapter = adapter_with_config
        mock_create_food(adapter)
        mock_post_diary(adapter)
        self._breakfast_combo(adapter, [
            {"name": "Paella (西班牙海鲜饭)", "calories": 500,
             "macros": {"protein": 25, "carbs": 60, "fat": 18}},
        ])

        result = adapter.record_nutrition("2026-01-01", "breakfast", [{"name": "早餐组合"}])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 500
        assert written["macros"]["protein"] == 25
        assert "warnings" not in result

    def test_config_matched_zero_calorie_is_not_flagged_unmatched(self, adapter_with_config):
        """配置命中且配置值本就是 0 kcal（胶囊类补剂），不应报「未匹配」。"""
        adapter = adapter_with_config
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter._config["supplements"]["coq10"] = {
            "name": "CoQ10",
            "calories": 0,
            "macros": {"fat": 0},
            "aliases": ["辅酶Q10"],
        }

        result = adapter.record_nutrition("2026-01-01", "breakfast", [{"name": "辅酶Q10"}])

        assert result["count"] == 1
        assert "warnings" not in result

    def test_direct_dict_input_still_uses_ai_fallback(self, adapter_with_config):
        """非套餐路径不变：直接传 dict 仍按 L3 估算兜底，配置优先。"""
        adapter = self._adapter(adapter_with_config)
        mock_create_food(adapter)
        mock_post_diary(adapter)

        adapter.record_nutrition(
            "2026-01-01", "breakfast",
            [{"name": "煎蛋", "calories": 180}],
        )

        assert adapter._create_custom_food.call_args[0][0]["calories"] == 90


class TestSameMealDuplicateHint:
    """同一条命令跑两次时给一条提示，不拦。

    基线复用 _diary_entries_snapshot（本来就要取来防双写），零额外请求。
    跨餐次不提示——早餐和晚餐各喝一杯牛奶是正常需求。
    """

    def _with_snapshot(self, adapter, entries):
        adapter._diary_entries_snapshot = MagicMock(return_value=entries)
        mock_create_food(adapter)
        mock_post_diary(adapter)
        return adapter

    def test_hints_when_same_meal_already_has_the_item(self, adapter_with_config):
        adapter = self._with_snapshot(
            adapter_with_config,
            [("Breakfast", "Auto_Nutrition - Apple, 1 serving(s)")],
        )

        result = adapter.record_nutrition(
            "2026-01-01", "breakfast", [{"name": "Apple", "calories": 95}]
        )

        assert any("今天已有同名条目" in w for w in result["warnings"])
        assert result["count"] == 1  # 仍然写入，只是提示

    @pytest.mark.parametrize(
        "items",
        [
            [{"name": "Apple"}, {"name": "Apple"}],
            [{"name": "苹果"}, {"name": "Apple"}],
        ],
    )
    def test_hints_for_duplicates_inside_the_same_batch(self, adapter_with_config, items):
        adapter = self._with_snapshot(adapter_with_config, [])

        result = adapter.record_nutrition("2026-01-01", "breakfast", items)

        assert result["count"] == 2  # 两份可能是真实需求，只提示，不拦截
        assert any("本次录入" in w and "重复" in w for w in result["warnings"])

    def test_no_hint_when_item_is_in_another_meal(self, adapter_with_config):
        adapter = self._with_snapshot(
            adapter_with_config,
            [("Dinner", "Auto_Nutrition - Apple, 1 serving(s)")],
        )

        result = adapter.record_nutrition(
            "2026-01-01", "breakfast", [{"name": "Apple", "calories": 95}]
        )

        assert "warnings" not in result

    def test_no_hint_when_snapshot_is_unavailable(self, adapter_with_config):
        adapter = self._with_snapshot(adapter_with_config, None)

        result = adapter.record_nutrition(
            "2026-01-01", "breakfast", [{"name": "Apple", "calories": 95}]
        )

        assert "warnings" not in result


class TestRecordNutritionEdgeCases:
    def test_empty_items(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        result = adapter.record_nutrition("2026-01-01", "lunch", [])
        assert result["status"] == "ok"
        assert result["count"] == 0

    def test_dict_input_with_quotes_in_keys(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{'"name"': 'Test', '"calories"': 100}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["status"] == "ok"

    def test_dict_input_invalid_missing_name(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"calories": 100}]
        with pytest.raises(ValueError):
            adapter.record_nutrition("2026-01-01", "lunch", items)

    def test_ai_macros_dict(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)

        items = [{"name": "Custom", "calories": 200, "macros": {"protein": 15, "carbs": 10, "fat": 5}}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["status"] == "ok"


class TestCreateCustomFood:
    def test_basic_food(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": "food-999", "version": 1}]}
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        item = {"name": "Test Food", "calories": 100, "macros": {"protein": 10, "carbs": 5, "fat": 2}}
        result = adapter._create_custom_food(item)
        assert result["id"] == "food-999"
        assert result["version"] == 1

    def test_food_with_micros(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": "food-111", "version": 2}]}
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        item = {
            "name": "Test Food", "calories": 200,
            "macros": {"protein": 20, "carbs": 10, "fat": 5, "sodium": 100, "potassium": 200, "fiber": 3, "sugar": 5, "cholesterol": 50, "saturated_fat": 2},
        }
        result = adapter._create_custom_food(item)
        assert result["id"] == "food-111"

    def test_food_response_without_items_key(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"item": {"id": "food-222", "version": 3}}
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        item = {"name": "Test", "calories": 50}
        result = adapter._create_custom_food(item)
        assert result["id"] == "food-222"

    def test_food_zero_calories(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": "food-333", "version": 1}]}
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        item = {"name": "Water", "calories": 0}
        result = adapter._create_custom_food(item)
        assert result["id"] == "food-333"

    def test_food_all_micro_fields(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": "food-444", "version": 1}]}
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        item = {
            "name": "Complete Food", "calories": 300,
            "macros": {
                "protein": 30, "carbs": 20, "fat": 10, "sodium": 100, "potassium": 200,
                "calcium": 10, "iron": 5, "vitamin_a": 20, "vitamin_c": 30, "vitamin_d": 10,
                "fiber": 3, "sugar": 5, "cholesterol": 50, "saturated_fat": 2,
                "polyunsaturated_fat": 1, "monounsaturated_fat": 1.5, "trans_fat": 0.5,
            },
        }
        result = adapter._create_custom_food(item)
        assert result["id"] == "food-444"


class TestRecordNutritionPydanticModel:
    def test_pydantic_model_input(self, adapter):
        from mfp_adapter import FoodItemModel
        mock_create_food(adapter)
        mock_post_diary(adapter)

        item = FoodItemModel(name="Pydantic Food", calories=100)
        result = adapter.record_nutrition("2026-01-01", "lunch", [item])
        assert result["status"] == "ok"


class TestRecordNutritionUsdaException:
    def test_usda_search_exception(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.side_effect = Exception("DB corrupted")

        items = [{"name": "Unknown Food XYZ"}]
        result = adapter.record_nutrition("2026-01-01", "lunch", items)
        assert result["status"] == "ok"


class TestRecordNutritionAiMacrosNonDict:
    def test_ai_macros_not_dict(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = []

        from mfp_adapter import FoodItemModel
        original_dump = FoodItemModel.model_dump

        def _patched_dump(self, **kwargs):
            d = original_dump(self, **kwargs)
            if "macros" in d and d["macros"] is not None:
                d["macros"] = self.macros
            return d

        with patch.object(FoodItemModel, "model_dump", _patched_dump):
            items = [{"name": "AI Food", "calories": 200, "macros": {"protein": 10, "carbs": 5, "fat": 2}}]
            result = adapter.record_nutrition("2026-01-01", "lunch", items)
            assert result["status"] == "ok"


class TestFoodCacheReuse:
    """一条食物只存「1 份基准值」，份量走日记 servings 倍数。"""

    def _ok_resp(self, fid: str, version: int = 1) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": fid, "version": version}]}
        resp.raise_for_status = MagicMock()
        return resp

    def test_second_identical_food_reuses_id(self, adapter):
        adapter.session.post.return_value = self._ok_resp("food-1")
        item = {"name": "Oats", "calories": 75.8, "macros": {"protein": 2.7, "carbs": 13.5, "fat": 1.4}}

        first = adapter._create_custom_food(item)
        second = adapter._create_custom_food(item)

        assert first["id"] == second["id"] == "food-1"
        assert first["cached"] is False
        assert second["cached"] is True
        assert adapter.session.post.call_count == 1

    def test_same_name_different_portion_reuses_food(self, adapter):
        """同名不同份量不再新建食物——份量交给 servings。"""
        adapter.session.post.return_value = self._ok_resp("food-1")
        adapter._create_custom_food({"name": "Apple", "calories": 95})

        result = adapter._create_custom_food({"name": "apple", "calories": 190})

        assert result["id"] == "food-1"
        assert result["cached"] is True
        assert adapter.session.post.call_count == 1

    def test_different_names_create_separate_foods(self, adapter):
        adapter.session.post.side_effect = [self._ok_resp("food-1"), self._ok_resp("food-2")]

        adapter._create_custom_food({"name": "Oats", "calories": 75.8})
        result = adapter._create_custom_food({"name": "Rolled Oats", "calories": 75.8})

        assert result["id"] == "food-2"
        assert adapter.session.post.call_count == 2

    def test_cache_persisted_to_disk(self, adapter, tmp_path):
        adapter.session.post.return_value = self._ok_resp("food-9")
        adapter._create_custom_food({"name": "Apple", "calories": 95})

        saved = json.loads((tmp_path / "food_cache.json").read_text(encoding="utf-8"))
        assert len(saved["entries"]) == 1
        entry = next(iter(saved["entries"].values()))
        assert entry["id"] == "food-9"
        assert entry["calories"] == 95

    def test_force_new_bypasses_cache(self, adapter):
        adapter.session.post.side_effect = [self._ok_resp("food-1"), self._ok_resp("food-2")]
        item = {"name": "Oats", "calories": 75.8}

        adapter._create_custom_food(item)
        result = adapter._create_custom_food(item, force_new=True)

        assert result["id"] == "food-2"
        assert result["cached"] is False
        assert adapter.session.post.call_count == 2


class TestServingMultiplier:
    """份量倍数：本次热量 / 食物基准热量。"""

    def test_servings_scale_by_calories(self, adapter):
        ref = {"id": "f1", "version": 1, "cached": True, "base_calories": 95}
        assert adapter._servings_for({"calories": 190}, ref) == 2.0
        assert adapter._servings_for({"calories": 47.5}, ref) == 0.5

    def test_zero_base_falls_back_to_one_serving(self, adapter):
        ref = {"id": "f1", "version": 1, "cached": True, "base_calories": 0}
        assert adapter._servings_for({"calories": 0}, ref) == 1.0

    def test_write_food_entry_posts_scaled_servings(self, adapter):
        adapter._create_custom_food = MagicMock(
            return_value={"id": "f1", "version": 1, "cached": True, "base_calories": 95}
        )
        adapter._post_diary_entry = MagicMock()

        adapter._write_food_entry("2026-01-01", "Snacks", {"name": "Apple", "calories": 190})

        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["servings"] == 2.0
        assert entry["food"] == {"id": "f1", "version": 1}


class TestSanityGate:
    """USDA top-1 误匹配的拦截：数值离谱时退回 AI 估算，或至少显式告警。"""

    ABSURD = {
        "name": "Chicken drumstick, weird entry",
        "calories_per_100g": 440.0,
        "macros_per_100g": {"protein": 10.0, "carbs": 1.0, "fat": 44.0},
    }

    def test_usda_overestimate_falls_back_to_ai(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [self.ABSURD]

        result = adapter.record_nutrition(
            "2026-01-01", "dinner",
            [{"name": "小鸡腿 1个", "calories": 110, "macros": {"protein": 10, "carbs": 3, "fat": 6.5}}],
        )

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 110
        assert result["status"] == "ok"
        assert "warnings" not in result

    def test_suspect_value_written_with_warning_when_no_ai(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [self.ABSURD]

        result = adapter.record_nutrition("2026-01-01", "dinner", [{"name": "小鸡腿 1个"}])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 440
        assert any("自相矛盾" in w for w in result.get("warnings", []))

    def test_macro_inconsistent_value_rejected(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [{
            "name": "Broken entry",
            "calories_per_100g": 300.0,
            "macros_per_100g": {"protein": 1.0, "carbs": 1.0, "fat": 1.0},
        }]

        result = adapter.record_nutrition("2026-01-01", "lunch", [{"name": "Mystery food"}])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 300
        assert any("自相矛盾" in w for w in result.get("warnings", []))

    def test_normal_usda_value_passes_through(self, adapter):
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [{
            "name": "Chicken breast, raw",
            "calories_per_100g": 165.0,
            "macros_per_100g": {"protein": 31.0, "carbs": 0.0, "fat": 3.6},
        }]

        result = adapter.record_nutrition(
            "2026-01-01", "lunch", [{"name": "100g Chicken breast", "calories": 150}],
        )

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 165.0
        assert "warnings" not in result

    def test_config_match_bypasses_gate(self, adapter_with_config):
        mock_create_food(adapter_with_config)
        mock_post_diary(adapter_with_config)
        adapter_with_config.usda.search.return_value = [self.ABSURD]

        result = adapter_with_config.record_nutrition(
            "2026-01-01", "snack", [{"name": "蛋白粉", "calories": 120}],
        )

        written = adapter_with_config._create_custom_food.call_args[0][0]
        assert written["calories"] == 120
        assert "warnings" not in result

    def test_explicit_weight_keeps_usda_value(self, adapter):
        """给了克重时，USDA 的 per-100g 换算比 AI 估算可靠，倍数闸门必须让路。

        实测踩过：``100g 鸡胸肉`` USDA 165 kcal、AI 估 90，比值 1.8 触发降级，
        把正确值改成了 90。规格换算的权威性高于 AI 心算。
        """
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [{
            "name": "Chicken breast roasted",
            "calories_per_100g": 165.0,
            "macros_per_100g": {"protein": 31.0, "carbs": 0.0, "fat": 3.6},
        }]

        result = adapter.record_nutrition(
            "2026-01-01", "lunch",
            [{"name": "100g Chicken breast", "calories": 90,
              "macros": {"protein": 15, "carbs": 0, "fat": 2}}],
        )

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 165.0
        assert "warnings" not in result

    def test_explicit_weight_in_display_qty_also_skips_ratio_gate(self, adapter):
        """字符串输入把规格剥进 display_qty，同样不能让 AI 覆盖 USDA。"""
        mock_create_food(adapter)
        mock_post_diary(adapter)
        adapter.usda.search.return_value = [{
            "name": "Peanuts, raw",
            "calories_per_100g": 567.0,
            "macros_per_100g": {"protein": 25.8, "carbs": 16.1, "fat": 49.2},
        }]

        adapter.record_nutrition("2026-01-01", "snack", ["100g Peanuts (300 kcal)"])

        written = adapter._create_custom_food.call_args[0][0]
        assert written["calories"] == 567.0

    def test_has_explicit_size_reads_both_places(self, adapter):
        """规格可能落在 name（dict 输入）或 display_qty（字符串输入）里。"""
        assert adapter._has_explicit_size({"name": "100g 花生"}) is True
        assert adapter._has_explicit_size({"name": "花生", "display_qty": "100g"}) is True
        assert adapter._has_explicit_size({"name": "Milk 250ml"}) is True
        assert adapter._has_explicit_size({"name": "小鸡腿 1个"}) is False
        assert adapter._has_explicit_size({"name": "Apple", "display_qty": "1份"}) is False


class TestFoodCacheZeroCalorieMismatch:
    """0 kcal 无法用 servings 倍数表达（0 × n 恒为 0），缓存必须按「零卡性」隔离。"""

    def _ok_resp(self, fid: str, version: int = 1) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"items": [{"id": fid, "version": version}]}
        resp.raise_for_status = MagicMock()
        return resp

    def test_zero_base_cache_does_not_poison_later_calories(self, adapter):
        """第一次被兜底记成 0，同名食物之后不能永远写 0。"""
        adapter.session.post.side_effect = [self._ok_resp("food-0"), self._ok_resp("food-10")]

        first = adapter._create_custom_food({"name": "鱼油", "calories": 0})
        second = adapter._create_custom_food({"name": "鱼油", "calories": 10})

        assert first["base_calories"] == 0
        assert second["id"] == "food-10"
        assert second["cached"] is False
        assert adapter._servings_for({"calories": 10}, second) == 1.0

    def test_nonzero_base_not_reused_for_zero_item(self, adapter):
        """反过来：缓存是 95 kcal、本次是 0，复用会把 95 写进去。"""
        adapter.session.post.side_effect = [self._ok_resp("food-95"), self._ok_resp("food-0")]

        adapter._create_custom_food({"name": "Apple", "calories": 95})
        second = adapter._create_custom_food({"name": "Apple", "calories": 0})

        assert second["id"] == "food-0"
        assert second["cached"] is False

    def test_both_zero_still_reuses(self, adapter):
        """0 kcal 补剂本身是稳定的，照常复用，避免食物库膨胀。"""
        adapter.session.post.return_value = self._ok_resp("food-coq10")

        adapter._create_custom_food({"name": "CoQ10", "calories": 0})
        second = adapter._create_custom_food({"name": "CoQ10", "calories": 0})

        assert second["cached"] is True
        assert adapter.session.post.call_count == 1
