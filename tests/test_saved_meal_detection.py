"""MFP 套餐名探测：输入撞上保存的套餐时改走 record_meal。

背景：用户的 MFP 套餐就是日常习惯餐食，名字天天被说出口。过去这些名字会被
当成普通食物去查配置 → 查不到 → 查 USDA → 记 0 kcal 或错数。现在写入前先
探测一次，命中就按套餐自带数值整份写入。
"""

from unittest.mock import MagicMock, patch

import pytest

from mfp_adapter import MFPAdapter


def _meal(meal_id: int, name: str, calories: float = 500.0) -> dict:
    return {
        "meal_id": meal_id,
        "name": name,
        "food_count": 1,
        "totals": {"calories": calories, "protein": 20.0, "carbs": 50.0, "fat": 15.0},
        "foods": [{"description": f"{name} 主料", "calories": calories}],
    }


MEALS = [
    _meal(1, "牛奶蛋白粉", 727.0),
    _meal(2, "Milk Oatmeal", 400.0),
    _meal(3, "蛋白粉", 120.0),
]


@pytest.fixture
def adapter():
    a = MFPAdapter.__new__(MFPAdapter)
    a._config = {}
    a._load_config = lambda: a._config
    a.get_my_meals = MagicMock(return_value=MEALS)
    return a


class TestSavedMealRef:
    def test_exact_name_is_detected(self, adapter):
        meal = adapter._saved_meal_ref("牛奶蛋白粉", MEALS)

        assert meal is not None and meal["meal_id"] == 1

    def test_case_and_space_insensitive(self, adapter):
        assert adapter._saved_meal_ref("  milk   oatmeal ", MEALS)["meal_id"] == 2

    def test_count_prefix_still_detected(self, adapter):
        """`1份 牛奶蛋白粉` 的数量被剥走后，名字仍是套餐名。"""
        assert adapter._saved_meal_ref("1份 牛奶蛋白粉", MEALS)["meal_id"] == 1

    def test_meal_name_inside_longer_input_is_detected(self, adapter):
        assert adapter._saved_meal_ref("牛奶蛋白粉套餐", MEALS)["meal_id"] == 1

    def test_longest_meal_name_wins(self, adapter):
        """「牛奶蛋白粉」和「蛋白粉」都是子串，取更长的那个。"""
        assert adapter._saved_meal_ref("牛奶蛋白粉套餐", MEALS)["meal_id"] == 1

    def test_size_spec_input_is_not_a_meal_reference(self, adapter):
        """`250ml 牛奶` 是在称重，不能被名为「牛奶」的套餐抢走。"""
        meals = MEALS + [_meal(9, "牛奶", 180.0)]

        assert adapter._saved_meal_ref("250ml 牛奶", meals) is None
        assert adapter._saved_meal_ref("100g 牛奶", meals) is None

    def test_reverse_containment_is_rejected(self, adapter):
        """输入 ⊂ 套餐名不算：`Milk` 不能命中 `Milk Oatmeal`。"""
        assert adapter._saved_meal_ref("Milk", MEALS) is None
        assert adapter._saved_meal_ref("Oatmeal", MEALS) is None

    def test_plain_food_is_not_detected(self, adapter):
        assert adapter._saved_meal_ref("100g Chicken breast", MEALS) is None

    def test_dict_input_uses_its_name(self, adapter):
        meal = adapter._saved_meal_ref({"name": "牛奶蛋白粉", "calories": 700}, MEALS)

        assert meal is not None and meal["meal_id"] == 1

    def test_ambiguous_containment_is_not_guessed(self, adapter):
        """两个同长套餐名都包含在输入里 → 不猜，按普通食物处理。"""
        meals = [_meal(11, "早餐A", 100.0), _meal(12, "早餐B", 200.0)]

        assert adapter._saved_meal_ref("早餐A早餐B", meals) is None


class TestSplitSavedMealRefs:
    def test_splits_meals_from_plain_items(self, adapter):
        meal_hits, plain, notes = adapter.split_saved_meal_refs(
            ["牛奶蛋白粉", "100g Chicken breast", {"name": "Milk Oatmeal"}]
        )

        assert [m["meal_id"] for m in meal_hits] == [1, 2]
        assert plain == ["100g Chicken breast"]
        assert notes == []

    def test_duplicate_meal_is_written_once(self, adapter):
        meal_hits, plain, notes = adapter.split_saved_meal_refs(["牛奶蛋白粉", "牛奶蛋白粉"])

        assert [m["meal_id"] for m in meal_hits] == [1]
        assert plain == []
        assert any("重复出现" in n for n in notes)

    def test_no_meals_means_everything_is_plain(self, adapter):
        adapter.get_my_meals = MagicMock(return_value=[])

        meal_hits, plain, notes = adapter.split_saved_meal_refs(["牛奶蛋白粉"])

        assert meal_hits == []
        assert plain == ["牛奶蛋白粉"]
        assert notes == []

    def test_meal_fetch_failure_never_blocks_the_write(self, adapter):
        adapter.get_my_meals = MagicMock(side_effect=RuntimeError("network down"))

        meal_hits, plain, notes = adapter.split_saved_meal_refs(["牛奶蛋白粉", "Apple"])

        assert meal_hits == []
        assert plain == ["牛奶蛋白粉", "Apple"]
        assert notes == []

    def test_meals_are_cached_within_ttl(self, adapter):
        adapter.split_saved_meal_refs(["Apple"])
        adapter.split_saved_meal_refs(["Apple"])

        assert adapter.get_my_meals.call_count == 1


class TestRecordNutritionToolRoutesMeals:
    def _adapter(self):
        mfp = MagicMock()
        mfp.split_saved_meal_refs.return_value = ([_meal(1, "牛奶蛋白粉", 727.0)], ["100g Rice"], [])
        mfp._write_resolved_meal.return_value = {
            "status": "ok", "count": 2, "totals": {"calories": 727.0},
        }
        mfp.record_nutrition.return_value = {"status": "ok", "count": 1}
        return mfp

    def test_meal_goes_through_record_meal_path(self):
        mfp = self._adapter()

        with patch("mfp_adapter.get_adapter", return_value=mfp):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-10-26", "breakfast", ["牛奶蛋白粉", "100g Rice"])

        mfp._write_resolved_meal.assert_called_once()
        assert mfp._write_resolved_meal.call_args[0][2]["meal_id"] == 1
        assert "按套餐写入" in result and "牛奶蛋白粉" in result
        assert "成功写入 MyFitnessPal" in result
        # 普通食物仍然走原管线，且不会把套餐名再传一遍
        assert mfp.record_nutrition.call_args[0][2] == ["100g Rice"]

    def test_only_meal_still_reports(self):
        mfp = self._adapter()
        mfp.split_saved_meal_refs.return_value = ([_meal(1, "牛奶蛋白粉", 727.0)], [], [])

        with patch("mfp_adapter.get_adapter", return_value=mfp):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-10-26", "breakfast", ["牛奶蛋白粉"])

        assert "按套餐写入" in result
        mfp.record_nutrition.assert_not_called()

    def test_detection_failure_falls_back_to_plain_items(self):
        mfp = self._adapter()
        mfp.split_saved_meal_refs.side_effect = TypeError("unpack failed")
        mfp.record_nutrition.return_value = {"status": "ok", "count": 2}

        with patch("mfp_adapter.get_adapter", return_value=mfp):
            from mfp_adapter import record_nutrition
            result = record_nutrition("2026-10-26", "breakfast", ["牛奶蛋白粉", "100g Rice"])

        assert "成功写入 MyFitnessPal" in result
        assert mfp.record_nutrition.call_args[0][2] == ["牛奶蛋白粉", "100g Rice"]
