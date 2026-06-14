import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from mfp_adapter import MFPAdapter
from tests.conftest import mock_create_food, mock_post_diary


@pytest.fixture
def adapter_with_config(tmp_path):
    """Adapter with supplements_config for config-matched tests."""
    a = MFPAdapter.__new__(MFPAdapter)
    a.BASE_URL = "https://api.myfitnesspal.com/v2"
    a.JOURNAL_FILE = str(tmp_path / "journal.json")
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

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
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

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
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
