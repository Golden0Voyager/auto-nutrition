import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from mfp_adapter import MFPAdapter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def mock_create_food(adapter):
    """Mock _create_custom_food to return a fake food ref."""
    adapter._create_custom_food = MagicMock(return_value={"id": "food-123", "version": 1})


def mock_post_diary(adapter):
    """Mock _post_diary_entry to do nothing."""
    adapter._post_diary_entry = MagicMock()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    """Return a temporary directory as a Path object."""
    return tmp_path


@pytest.fixture
def mock_env(monkeypatch):
    """Remove .env influence on tests."""
    monkeypatch.delenv("MFP_USERNAME", raising=False)
    monkeypatch.delenv("MFP_PASSWORD", raising=False)


@pytest.fixture
def adapter(tmp_path):
    """Create MFPAdapter with full mocking for record_nutrition / API tests."""
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
    a._config = {}
    a._load_config = lambda: a._config
    a._csrf_token = None
    return a


@pytest.fixture
def mock_get_adapter():
    """Mock the global get_adapter function and adapter (for MCP tool tests)."""
    mock_adapter = MagicMock()
    mock_adapter.access_token = "fake-token"
    mock_adapter.user_id = 12345
    mock_adapter.token_expires_at = 999999999999
    mock_adapter.BASE_URL = "https://api.myfitnesspal.com/v2"
    mock_adapter.JOURNAL_FILE = "/tmp/test_journal.json"
    mock_adapter._JOURNAL_MAX_ENTRIES = 200
    mock_adapter.usda = MagicMock()
    mock_adapter.session = MagicMock()
    mock_adapter._config = {}
    return mock_adapter


# ---------------------------------------------------------------------------
# Cookie / Token fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_cookies():
    """Valid cookie list for MFP."""
    return [
        {"name": "mfp-session", "value": "test-session-id", "domain": ".myfitnesspal.com", "path": "/"},
        {"name": "__Secure-next-auth.session-token", "value": "test-next-auth-token", "domain": ".myfitnesspal.com", "path": "/"},
    ]


@pytest.fixture
def cookies_file(tmp_path, sample_cookies):
    """Write cookies to a temp file and return its path."""
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps(sample_cookies), encoding="utf-8")
    return str(p)


@pytest.fixture
def mock_token_response():
    """Fake token response payload."""
    return {
        "access_token": "fake-bearer-token-abc123",
        "user_id": 12345,
        "expires_in": 3600,
    }


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config():
    """Minimal supplements_config.yaml content."""
    return {
        "supplements": {
            "whey_protein": {
                "name": "Whey Protein (乳清蛋白粉 1 Scoop)",
                "calories": 120,
                "macros": {"protein": 24, "carbs": 3, "fat": 1.5},
                "aliases": ["蛋白粉", "乳清蛋白"],
            },
        },
        "regional_foods": {
            "braised_beef": {
                "name": "Braised Beef (酱牛肉 100g)",
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
                "aliases": ["煎鸡蛋", "煎蛋", "荷包蛋"],
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
def config_file(tmp_path, sample_config):
    """Write config to a temp YAML file and return its path."""
    p = tmp_path / "supplements_config.yaml"
    p.write_text(yaml.dump(sample_config, allow_unicode=True), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# USDA test database
# ---------------------------------------------------------------------------

@pytest.fixture
def usda_db(tmp_path):
    """Create a temporary USDA SQLite database with test data."""
    db_path = tmp_path / "usda_core.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE foods (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type TEXT
        )
    """)
    c.execute("""
        CREATE TABLE nutrients (
            nutrient_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            unit_name TEXT
        )
    """)
    c.execute("""
        CREATE TABLE food_nutrients (
            fdc_id INTEGER NOT NULL,
            nutrient_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            PRIMARY KEY (fdc_id, nutrient_id)
        )
    """)

    # FTS5 virtual table
    c.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)")

    # Insert test foods
    foods = [
        (1001, "Apple, raw, with skin", "sr_legacy_food"),
        (1002, "Chicken breast, boneless, skinless, raw", "sr_legacy_food"),
        (1003, "Egg, whole, raw, fresh", "sr_legacy_food"),
        (1004, "Rice, white, cooked", "sr_legacy_food"),
        (1005, "Banana, raw", "sr_legacy_food"),
        (1006, "Minerals, Zinc", "survey_fndds_food"),
        (1007, "Proximates, Protein", "survey_fndds_food"),
    ]
    c.executemany("INSERT INTO foods (fdc_id, description, data_type) VALUES (?, ?, ?)", foods)
    for fdc_id, desc, _ in foods:
        c.execute("INSERT INTO foods_fts (description, fdc_id) VALUES (?, ?)", (desc, fdc_id))

    # Insert nutrients (1008=energy kcal, 1003=protein, 1005=carbs, 1004=fat, 1093=sodium, 1092=potassium)
    nutrients = [
        (1008, "Energy", "kcal"),
        (1003, "Protein", "g"),
        (1005, "Carbohydrate, by difference", "g"),
        (1004, "Total lipid (fat)", "g"),
        (1093, "Sodium, Na", "mg"),
        (1092, "Potassium, K", "mg"),
        (1087, "Calcium, Ca", "mg"),
        (1089, "Iron, Fe", "mg"),
        (1079, "Fiber, total dietary", "g"),
        (2000, "Sugars, total including NLEA", "g"),
    ]
    c.executemany("INSERT INTO nutrients (nutrient_id, name, unit_name) VALUES (?, ?, ?)", nutrients)

    # Insert food_nutrients (per 100g values)
    fn_data = [
        # Apple
        (1001, 1008, 52),   # energy
        (1001, 1003, 0.3),  # protein
        (1001, 1005, 13.8), # carbs
        (1001, 1004, 0.2),  # fat
        (1001, 1093, 1),    # sodium
        (1001, 1092, 107),  # potassium
        (1001, 1079, 2.4),  # fiber
        (1001, 2000, 10.4), # sugar
        # Chicken breast
        (1002, 1008, 120),
        (1002, 1003, 22.5),
        (1002, 1005, 0),
        (1002, 1004, 2.6),
        (1002, 1093, 44),
        # Egg
        (1003, 1008, 155),
        (1003, 1003, 12.6),
        (1003, 1005, 1.1),
        (1003, 1004, 10.6),
        # Rice
        (1004, 1008, 130),
        (1004, 1003, 2.7),
        (1004, 1005, 28.2),
        (1004, 1004, 0.3),
        # Banana
        (1005, 1008, 89),
        (1005, 1003, 1.1),
        (1005, 1005, 22.8),
        (1005, 1004, 0.3),
    ]
    c.executemany("INSERT INTO food_nutrients (fdc_id, nutrient_id, amount) VALUES (?, ?, ?)", fn_data)

    conn.commit()
    conn.close()
    return str(db_path)
