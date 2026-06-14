import pytest
from unittest.mock import patch
from mfp_adapter import MFPAdapter


_TEST_CONFIG = {
    "supplements": {
        "whey_protein": {
            "name": "Whey Protein (乳清蛋白粉 1 Scoop)",
            "calories": 120,
            "macros": {"protein": 24, "carbs": 3, "fat": 1.5},
            "aliases": ["蛋白粉", "乳清蛋白"],
        },
        "fish_oil": {
            "name": "Fish Oil (鱼油 1 Capsule)",
            "calories": 10,
            "macros": {"protein": 0, "carbs": 0, "fat": 1.1},
            "micros": {"epa": 180, "dha": 120},
            "aliases": ["鱼油"],
        },
    },
    "regional_foods": {
        "braised_beef": {
            "name": "Braised Beef (传统酱牛肉 100g)",
            "calories": 246,
            "macros": {"protein": 31.4, "carbs": 3.2, "fat": 11.0},
            "aliases": ["酱牛肉"],
        },
    },
    "common_foods": {
        "apple": {
            "name": "Apple (Red/Green, Medium)",
            "calories": 95,
            "macros": {"protein": 0.5, "carbs": 25, "fat": 0.3},
            "aliases": ["苹果", "Apple"],
        },
        "fried_egg": {
            "name": "Fried Egg (煎鸡蛋 Sunny Up)",
            "calories": 90,
            "macros": {"protein": 6.3, "carbs": 0.6, "fat": 7.0},
            "aliases": ["煎鸡蛋", "煎蛋"],
        },
    },
    "meal_combos": {
        "morning_stack": {
            "name": "晨补 (Morning Stack)",
            "aliases": ["晨间补剂", "补剂"],
            "items": [
                {"name": "Fish Oil", "calories": 10, "macros": {"carbs": 0, "protein": 0, "fat": 1.1}},
            ],
        },
    },
    "routines": {
        "night_stack": {
            "name": "晚补 (Night Stack)",
            "aliases": ["睡前补剂"],
            "items": [
                {"name": "Calcium", "calories": 0, "macros": {"carbs": 0, "protein": 0, "fat": 0}},
            ],
        },
    },
}


@pytest.fixture
def adapter_with_config(tmp_path):
    """Create adapter with mock config."""
    a = MFPAdapter.__new__(MFPAdapter)
    a._config = _TEST_CONFIG.copy()
    a._config_mtime = 0
    a.usda = None
    a.session = None
    a.access_token = "fake"
    a.user_id = 1
    a.token_expires_at = 999999999999
    a.BASE_URL = "https://api.myfitnesspal.com/v2"
    a.JOURNAL_FILE = str(tmp_path / "journal.json")
    a._JOURNAL_MAX_ENTRIES = 200
    a._load_config = lambda: a._config
    return a


class TestApplyConfigSafeguard:
    def test_match_supplement_english(self, adapter_with_config):
        item = {"name": "Whey Protein", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Whey Protein (乳清蛋白粉 1 Scoop)"
        assert result["calories"] == 120
        assert result["macros"]["protein"] == 24

    def test_match_supplement_chinese(self, adapter_with_config):
        item = {"name": "蛋白粉", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Whey Protein (乳清蛋白粉 1 Scoop)"
        assert result["calories"] == 120

    def test_match_supplement_alias(self, adapter_with_config):
        item = {"name": "乳清蛋白", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Whey Protein (乳清蛋白粉 1 Scoop)"

    def test_match_regional_food(self, adapter_with_config):
        item = {"name": "酱牛肉 100g", "calories": 200}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Braised Beef (传统酱牛肉 100g)"
        assert result["calories"] == 246

    def test_match_common_food(self, adapter_with_config):
        item = {"name": "Apple", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Apple (Red/Green, Medium)"
        assert result["calories"] == 95

    def test_match_common_food_chinese(self, adapter_with_config):
        item = {"name": "苹果", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Apple (Red/Green, Medium)"

    def test_match_fried_egg(self, adapter_with_config):
        item = {"name": "煎蛋", "calories": 80}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Fried Egg (煎鸡蛋 Sunny Up)"
        assert result["calories"] == 90

    def test_serving_ratio_scaling(self, adapter_with_config):
        item = {"name": "Whey Protein", "calories": 100, "serving_ratio": 0.5}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["calories"] == 60.0  # 120 * 0.5

    def test_micros_included(self, adapter_with_config):
        item = {"name": "鱼油", "calories": 10}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["macros"]["epa"] == 180
        assert result["macros"]["dha"] == 120

    def test_no_match_returns_original(self, adapter_with_config):
        item = {"name": "Unknown Food XYZ", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Unknown Food XYZ"
        assert result["calories"] == 100
        assert "_config_matched" not in result

    def test_empty_config(self, adapter_with_config):
        adapter_with_config._config = {}
        item = {"name": "Apple", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Apple"

    def test_config_matched_flag(self, adapter_with_config):
        item = {"name": "Whey Protein", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result.get("_config_matched") is True

    def test_word_boundary_not_match_partial(self, adapter_with_config):
        """'Gel' should not match 'Gelatin'."""
        adapter_with_config._config["supplements"]["gelatin"] = {
            "name": "Gelatin",
            "calories": 50,
            "macros": {"protein": 10, "carbs": 0, "fat": 0},
            "aliases": ["gelatin"],
        }
        item = {"name": "Gel", "calories": 10}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["name"] == "Gel"

    def test_fish_oil_alias_match(self, adapter_with_config):
        item = {"name": "鱼油", "calories": 10}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result["macros"]["epa"] == 180

    def test_case_insensitive_match(self, adapter_with_config):
        item = {"name": "WHEY PROTEIN", "calories": 100}
        result = adapter_with_config._apply_config_safeguard(item)
        assert result.get("_config_matched") is True
