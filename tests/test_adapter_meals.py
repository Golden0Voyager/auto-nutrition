import json
import os
from unittest.mock import MagicMock

import pytest
import requests

from mfp_adapter import MFPAdapter

# 与真实 /api/services/users/meals/mine 返回同构的样本数据
SAMPLE_MEALS_RAW = [
    {
        "meal_id": 4424592565,
        "description": "牛奶蛋白粉",
        "foods": [
            {"description": "纯牛奶 - 牛奶, 250 ml", "calories": 158, "carbs": 10, "fat": 9,
             "protein": 8, "sodium": 82, "sugar": 0},
            {"description": "我的蛋白粉 - 蛋白粉, 100 g", "calories": 569, "carbs": 47, "fat": 38,
             "protein": 7, "sodium": 374, "sugar": 0},
        ],
    },
    {
        "meal_id": 4412105796,
        "description": "燕麦牛奶煎蛋套餐",
        "foods": [
            {"description": "Whole milk, 1 cup", "calories": 149, "carbs": 12, "fat": 8, "protein": 8},
            {"description": "Oats, 1 cup", "calories": 303, "carbs": 54, "fat": 5, "protein": 11},
            {"description": "Homemade - Egg, Fried, 1 large", "calories": 90, "carbs": 0, "fat": 7, "protein": 6},
        ],
    },
]


def _json_resp(payload, status_code=200):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    resp.status_code = status_code
    return resp


@pytest.fixture
def no_sleep(monkeypatch):
    """去掉套餐写入时的 0.5s 限速 sleep。"""
    monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)


class TestGetMyMeals:
    def test_success_normalizes_totals(self, adapter):
        adapter.session.get.return_value = _json_resp(SAMPLE_MEALS_RAW)

        meals = adapter.get_my_meals()

        assert len(meals) == 2
        first = meals[0]
        assert first["meal_id"] == 4424592565
        assert first["name"] == "牛奶蛋白粉"
        assert first["food_count"] == 2
        assert first["totals"]["calories"] == 727.0
        assert first["totals"]["protein"] == 15.0
        assert first["totals"]["carbs"] == 57.0
        assert first["totals"]["fat"] == 47.0
        assert first["foods"] == SAMPLE_MEALS_RAW[0]["foods"]

    def test_uses_web_session_endpoint(self, adapter):
        adapter.session.get.return_value = _json_resp(SAMPLE_MEALS_RAW)

        adapter.get_my_meals()

        url = adapter.session.get.call_args[0][0]
        assert url == MFPAdapter.MEALS_URL
        assert "api.myfitnesspal.com" not in url
        assert adapter.session.get.call_args[1]["headers"]["Accept"] == "application/json"

    def test_empty_list(self, adapter):
        adapter.session.get.return_value = _json_resp([])

        assert adapter.get_my_meals() == []

    def test_missing_values_default_to_zero(self, adapter):
        adapter.session.get.return_value = _json_resp(
            [{"meal_id": 1, "description": "缺省值套餐", "foods": [{"description": "x"}]}]
        )

        meals = adapter.get_my_meals()

        assert meals[0]["totals"]["calories"] == 0.0
        assert meals[0]["food_count"] == 1

    def test_http_error_propagates(self, adapter):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Client Error")
        adapter.session.get.return_value = resp

        with pytest.raises(requests.exceptions.HTTPError):
            adapter.get_my_meals()


class TestRecordMeal:
    def _stub(self, adapter, meals=SAMPLE_MEALS_RAW):
        adapter.session.get.return_value = _json_resp(meals)
        adapter._create_custom_food = MagicMock(return_value={"id": "food-123", "version": 1})
        adapter._post_diary_entry = MagicMock()

    def test_success_writes_each_food(self, adapter, no_sleep):
        self._stub(adapter)

        result = adapter.record_meal("2026-01-01", "dinner", 4424592565)

        assert result["status"] == "ok"
        assert result["meal"] == "牛奶蛋白粉"
        assert result["meal_id"] == 4424592565
        assert result["count"] == 2
        assert result["totals"]["calories"] == 727.0
        assert adapter._create_custom_food.call_count == 2
        assert adapter._post_diary_entry.call_count == 2

    def test_diary_entry_structure(self, adapter, no_sleep):
        self._stub(adapter)

        adapter.record_meal("2026-01-01", "breakfast", 4412105796)

        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["type"] == "food_entry"
        assert entry["date"] == "2026-01-01"
        assert entry["meal_name"] == "Breakfast"
        assert entry["food"] == {"id": "food-123", "version": 1}
        assert entry["servings"] == 1.0

    def test_macros_carry_micros(self, adapter, no_sleep):
        self._stub(adapter)

        adapter.record_meal("2026-01-01", "dinner", 4424592565)

        first_item = adapter._create_custom_food.call_args_list[0][0][0]
        assert first_item["name"] == "纯牛奶 - 牛奶, 250 ml"
        assert first_item["calories"] == 158.0
        assert first_item["macros"]["protein"] == 8.0
        assert first_item["macros"]["sodium"] == 82.0
        assert first_item["macros"]["sugar"] == 0.0
        assert first_item["source_meal"] == "牛奶蛋白粉"

    def test_meal_not_found_lists_available(self, adapter, no_sleep):
        self._stub(adapter)

        with pytest.raises(ValueError, match="未找到套餐「999」"):
            adapter.record_meal("2026-01-01", "dinner", 999)

    def test_meal_not_found_when_no_meals(self, adapter, no_sleep):
        self._stub(adapter, meals=[])

        with pytest.raises(ValueError, match="当前可用套餐: 无"):
            adapter.record_meal("2026-01-01", "dinner", 1)

    def test_empty_meal_rejected(self, adapter, no_sleep):
        self._stub(adapter, meals=[{"meal_id": 7, "description": "空套餐", "foods": []}])

        with pytest.raises(ValueError, match="没有任何食物"):
            adapter.record_meal("2026-01-01", "dinner", 7)

    def test_partial_failure_marks_status(self, adapter, no_sleep):
        self._stub(adapter)
        adapter._create_custom_food = MagicMock(
            side_effect=[{"id": "food-1", "version": 1}, RuntimeError("boom")]
        )

        result = adapter.record_meal("2026-01-01", "dinner", 4424592565)

        assert result["status"] == "partial"
        assert result["count"] == 2
        assert "写入失败" in result["warnings"][0]
        assert "我的蛋白粉" in result["warnings"][0]

    def test_http_error_recorded_per_food(self, adapter, no_sleep):
        self._stub(adapter)
        http_error = requests.exceptions.HTTPError("400 Client Error")
        http_error.response = MagicMock(status_code=400, text='{"error":"bad"}')
        adapter._post_diary_entry = MagicMock(side_effect=http_error)

        result = adapter.record_meal("2026-01-01", "dinner", 4424592565)

        assert result["status"] == "partial"
        assert result["count"] == 2
        assert adapter._post_diary_entry.call_count == 2
        assert "纯牛奶 - 牛奶, 250 ml" in result["warnings"][0]
        assert "我的蛋白粉 - 蛋白粉, 100 g" in result["warnings"][0]

    def test_journal_written(self, adapter, no_sleep):
        self._stub(adapter)

        adapter.record_meal("2026-01-01", "dinner", 4424592565)

        assert os.path.exists(adapter.JOURNAL_FILE)
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert len(journal) == 1
        entry = journal[0]
        assert entry["date"] == "2026-01-01"
        assert entry["meal_name"] == "Dinner"
        assert len(entry["items"]) == 2
        assert entry["items"][0]["source_meal"] == "牛奶蛋白粉"
        assert entry["items"][0]["calories"] == 158.0

    def test_meal_type_mapping(self, adapter, no_sleep):
        self._stub(adapter)

        adapter.record_meal("2026-01-01", "snack", 4412105796)

        entry = adapter._post_diary_entry.call_args[0][0]
        assert entry["meal_name"] == "Snacks"


class TestResolveMeal:
    """meal_ref 支持 ID / 精确名称 / 模糊名称，歧义时必须报错而不是猜测。"""

    MEALS = [
        {"meal_id": 5083761427, "name": "Milk Protein Shake", "food_count": 2,
         "totals": {"calories": 239.0, "protein": 29.0, "carbs": 14.0, "fat": 8.0}, "foods": []},
        {"meal_id": 5083755153, "name": "Milk Oatmeal", "food_count": 2,
         "totals": {"calories": 449.0, "protein": 18.0, "carbs": 66.0, "fat": 13.0}, "foods": []},
        {"meal_id": 5083746902, "name": "Ham & Egg Avo Ciabatta", "food_count": 4,
         "totals": {"calories": 384.0, "protein": 18.0, "carbs": 35.0, "fat": 19.0}, "foods": []},
    ]

    def test_by_id(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, 5083755153)
        assert meal["name"] == "Milk Oatmeal"

    def test_by_digit_string(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, "5083746902")
        assert meal["name"] == "Ham & Egg Avo Ciabatta"

    def test_by_exact_name_case_insensitive(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, "  milk protein shake ")
        assert meal["meal_id"] == 5083761427

    def test_by_fuzzy_name_typo(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, "Milk Protein Shke")
        assert meal["meal_id"] == 5083761427

    def test_by_partial_name(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, "Protein Shake")
        assert meal["meal_id"] == 5083761427

    def test_by_unique_substring(self, adapter):
        meal = adapter._resolve_meal(self.MEALS, "Ciabatta")
        assert meal["meal_id"] == 5083746902

    def test_ambiguous_substring_lists_candidates(self, adapter):
        with pytest.raises(ValueError, match="匹配到多个套餐") as exc:
            adapter._resolve_meal(self.MEALS, "Milk")
        assert "5083761427" in str(exc.value)
        assert "5083755153" in str(exc.value)

    def test_ambiguous_name_lists_candidates(self, adapter):
        dup = dict(self.MEALS[0])
        dup["meal_id"] = 999
        dup["totals"] = {"calories": 300.0, "protein": 29.0, "carbs": 14.0, "fat": 8.0}
        with pytest.raises(ValueError, match="匹配到多个套餐") as exc:
            adapter._resolve_meal(self.MEALS + [dup], "Milk Protein Shake")
        assert "5083761427" in str(exc.value)
        assert "999" in str(exc.value)

    def test_duplicate_exact_names_are_ambiguous(self, adapter):
        dup = dict(self.MEALS[1])
        dup["meal_id"] = 999
        with pytest.raises(ValueError, match="匹配到多个套餐"):
            adapter._resolve_meal(self.MEALS + [dup], "Milk Oatmeal")

    def test_fuzzy_ambiguity_lists_candidates(self, adapter):
        """查询词与两个相近名称都高置信命中（且无精确命中）时，走模糊歧义分支。"""
        variant = dict(self.MEALS[0])
        variant["meal_id"] = 999
        variant["name"] = "Milk Protein Shake XL"
        with pytest.raises(ValueError, match="匹配到多个套餐") as exc:
            adapter._resolve_meal([self.MEALS[0], variant], "Milk Protein Shakee")
        assert "5083761427" in str(exc.value)
        assert "999" in str(exc.value)

    def test_not_found_lists_all(self, adapter):
        with pytest.raises(ValueError, match="未找到套餐") as exc:
            adapter._resolve_meal(self.MEALS, "蛋白粉牛奶")
        assert "Milk Protein Shake" in str(exc.value)
        assert "Milk Oatmeal" in str(exc.value)

    def test_not_found_when_no_meals(self, adapter):
        with pytest.raises(ValueError, match="当前可用套餐: 无"):
            adapter._resolve_meal([], "anything")

    def test_record_meal_by_name(self, adapter, no_sleep):
        adapter.session.get.return_value = _json_resp([
            {"meal_id": 5083761427, "description": "Milk Protein Shake",
             "foods": [{"description": "Whole Milk, 1 cup", "calories": 149, "carbs": 12,
                        "fat": 8, "protein": 8, "sodium": 105, "sugar": 12}]},
        ])
        adapter._create_custom_food = MagicMock(return_value={"id": "food-1", "version": 1})
        adapter._post_diary_entry = MagicMock()

        result = adapter.record_meal("2026-01-01", "snack", "Milk Protein Shke")

        assert result["meal"] == "Milk Protein Shake"
        assert result["count"] == 1
        assert adapter._post_diary_entry.call_count == 1
