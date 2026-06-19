import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from mfp_adapter import USDALocalResolver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def resolver(usda_db):
    """Create a USDALocalResolver pointing at the test database."""
    r = USDALocalResolver.__new__(USDALocalResolver)
    r.DB_PATH = Path(usda_db)
    return r


@pytest.fixture
def legacy_usda_db(tmp_path):
    """Create a temporary USDA SQLite database with legacy flat schema."""
    db_path = tmp_path / "usda_legacy.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE foods (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type TEXT,
            energy REAL, protein REAL, carbs REAL, fat REAL,
            sodium REAL, potassium REAL, fiber REAL, sugar REAL
        )
    """)
    c.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)")

    foods = [
        (2001, "Apple, raw, with skin", "sr_legacy_food", 52, 0.3, 13.8, 0.2, 1, 107, 2.4, 10.4),
        (2002, "Chicken breast, boneless, skinless", "sr_legacy_food", 120, 22.5, 0, 2.6, 44, 0, 0, 0),
        (2003, "Minerals, Zinc", "survey_fndds_food", 0, 0, 0, 0, 0, 0, 0, 0),
    ]
    for row in foods:
        c.execute(
            "INSERT INTO foods (fdc_id, description, data_type, energy, protein, carbs, fat, sodium, potassium, fiber, sugar) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        c.execute("INSERT INTO foods_fts (description, fdc_id) VALUES (?, ?)", (row[1], row[0]))

    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def legacy_resolver(legacy_usda_db):
    r = USDALocalResolver.__new__(USDALocalResolver)
    r.DB_PATH = Path(legacy_usda_db)
    return r


@pytest.fixture
def dv_usda_db(tmp_path):
    """Create a database with foods containing DV nutrients."""
    db_path = tmp_path / "usda_dv.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT NOT NULL, data_type TEXT)")
    c.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)")
    c.execute("CREATE TABLE food_nutrients (fdc_id INTEGER, nutrient_id INTEGER, amount REAL)")

    c.execute("INSERT INTO foods VALUES (3001, 'Spinach, raw', 'sr_legacy_food')")
    c.execute("INSERT INTO foods_fts VALUES ('Spinach, raw', 3001)")

    fn_data = [
        (3001, 1008, 23), (3001, 1003, 2.9), (3001, 1005, 3.6), (3001, 1004, 0.4),
        (3001, 1087, 99), (3001, 1089, 2.7), (3001, 1106, 469), (3001, 1162, 28.1),
    ]
    c.executemany("INSERT INTO food_nutrients VALUES (?, ?, ?)", fn_data)

    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def dv_resolver(dv_usda_db):
    r = USDALocalResolver.__new__(USDALocalResolver)
    r.DB_PATH = Path(dv_usda_db)
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_apple(self, resolver):
        results = resolver.search("Apple", page_size=3)
        assert len(results) > 0
        assert any("Apple" in r["name"] for r in results)
        assert results[0]["calories_per_100g"] > 0
        assert "macros_per_100g" in results[0]

    def test_search_chicken(self, resolver):
        results = resolver.search("Chicken breast", page_size=3)
        assert len(results) > 0
        assert any("Chicken" in r["name"] for r in results)

    def test_search_egg(self, resolver):
        results = resolver.search("Egg", page_size=3)
        assert len(results) > 0

    def test_search_rice(self, resolver):
        results = resolver.search("Rice", page_size=3)
        assert len(results) > 0

    def test_search_banana(self, resolver):
        results = resolver.search("Banana", page_size=3)
        assert len(results) > 0

    def test_search_no_results(self, resolver):
        results = resolver.search("xyznonexistent", page_size=3)
        assert results == []

    def test_search_page_size_limit(self, resolver):
        results = resolver.search("Apple", page_size=1)
        assert len(results) <= 1

    def test_search_non_ascii_query(self, resolver):
        """Non-English query should still work (may return results or empty)."""
        results = resolver.search("苹果", page_size=3)
        assert isinstance(results, list)

    def test_search_db_not_exists(self, tmp_path):
        r = USDALocalResolver.__new__(USDALocalResolver)
        r.DB_PATH = tmp_path / "nonexistent.db"
        results = r.search("Apple", page_size=3)
        assert results == []

    def test_search_exception_handling(self, resolver):
        """Search should return empty list on exception."""
        with patch("sqlite3.connect", side_effect=Exception("db error")):
            results = resolver.search("Apple", page_size=3)
            assert results == []

    def test_search_english_word_extraction(self, resolver):
        """Query with numbers and non-alpha chars should be cleaned."""
        results = resolver.search("Apple 100g", page_size=3)
        assert len(results) > 0

    def test_search_empty_english_words(self, resolver):
        """Query with no English words should return empty."""
        results = resolver.search("12345", page_size=3)
        assert results == []

    def test_macros_per_100g_structure(self, resolver):
        results = resolver.search("Apple", page_size=1)
        assert len(results) > 0
        macros = results[0]["macros_per_100g"]
        assert isinstance(macros, dict)
        assert "protein" in macros
        assert "carbs" in macros
        assert "fat" in macros

    def test_search_filters_minerals(self, resolver):
        """Minerals/Proximates/Sugars entries should be filtered out."""
        results = resolver.search("Minerals", page_size=10)
        for r in results:
            assert not r["name"].startswith("Minerals,")

    def test_search_and_fallback_to_or(self, resolver):
        """AND query with zero results should fallback to OR."""
        results = resolver.search("Apple raw skin", page_size=3)
        assert len(results) > 0


class TestFoodRelevanceScore:
    def test_exact_first_term_match(self, resolver):
        score = resolver._food_relevance_score("Apple, raw, with skin", ["Apple"])
        assert score > 0

    def test_penalty_for_noise_words(self, resolver):
        score_noisy = resolver._food_relevance_score("Apple juice, canned", ["Apple"])
        score_clean = resolver._food_relevance_score("Apple, raw", ["Apple"])
        assert score_clean > score_noisy

    def test_bonus_for_raw_cooked(self, resolver):
        score_raw = resolver._food_relevance_score("Chicken, raw", ["Chicken"])
        score_plain = resolver._food_relevance_score("Chicken, frozen", ["Chicken"])
        assert score_raw > score_plain

    def test_short_description_bonus(self, resolver):
        score_short = resolver._food_relevance_score("Egg", ["Egg"])
        score_long = resolver._food_relevance_score("Egg, large, with added vitamin D", ["Egg"])
        assert score_short > score_long

    def test_multiple_query_words(self, resolver):
        score = resolver._food_relevance_score("Chicken breast, boneless", ["Chicken", "breast"])
        assert score > 0

    def test_no_match(self, resolver):
        score = resolver._food_relevance_score("Beef, frozen", ["Apple"])
        assert score <= 0


class TestSearchNormalized:
    def test_normalized_via_search(self, resolver):
        results = resolver.search("Apple", page_size=3)
        assert len(results) > 0
        assert results[0]["calories_per_100g"] == 52.0

    def test_energy_priority(self, resolver):
        """Foods with energy data should appear before those without."""
        results = resolver.search("Apple", page_size=10)
        energy_indices = [i for i, r in enumerate(results) if r["calories_per_100g"] > 0]
        no_energy_indices = [i for i, r in enumerate(results) if r["calories_per_100g"] == 0]
        if energy_indices and no_energy_indices:
            assert max(energy_indices) < min(no_energy_indices)


class TestSearchLegacy:
    def test_legacy_search_apple(self, legacy_resolver):
        results = legacy_resolver.search("Apple", page_size=3)
        assert len(results) > 0
        assert results[0]["calories_per_100g"] == 52

    def test_legacy_search_filters_minerals(self, legacy_resolver):
        results = legacy_resolver.search("Minerals", page_size=10)
        for r in results:
            assert not r["name"].startswith("Minerals,")

    def test_legacy_search_macros_structure(self, legacy_resolver):
        results = legacy_resolver.search("Apple", page_size=1)
        assert len(results) > 0
        macros = results[0]["macros_per_100g"]
        assert "protein" in macros
        assert "carbs" in macros
        assert "fat" in macros
        assert "sodium" in macros
        assert "potassium" in macros
        assert "fiber" in macros
        assert "sugar" in macros

    def test_legacy_or_fallback(self, legacy_usda_db):
        r = USDALocalResolver.__new__(USDALocalResolver)
        r.DB_PATH = Path(legacy_usda_db)
        results = r.search("raw chicken", page_size=3)
        assert isinstance(results, list)


class TestDvConversion:
    def test_calcium_dv_conversion(self, dv_resolver):
        results = dv_resolver.search("Spinach", page_size=1)
        assert len(results) > 0
        calcium = results[0]["macros_per_100g"].get("calcium")
        assert calcium is not None
        assert calcium == pytest.approx(round(99 / 1300.0 * 100, 1))

    def test_iron_dv_conversion(self, dv_resolver):
        results = dv_resolver.search("Spinach", page_size=1)
        iron = results[0]["macros_per_100g"].get("iron")
        assert iron is not None
        assert iron == pytest.approx(round(2.7 / 18.0 * 100, 1))

    def test_vitamin_a_dv_conversion(self, dv_resolver):
        results = dv_resolver.search("Spinach", page_size=1)
        vitamin_a = results[0]["macros_per_100g"].get("vitamin_a")
        assert vitamin_a is not None
        assert vitamin_a == pytest.approx(round(469 / 900.0 * 100, 1))

    def test_vitamin_c_dv_conversion(self, dv_resolver):
        results = dv_resolver.search("Spinach", page_size=1)
        vitamin_c = results[0]["macros_per_100g"].get("vitamin_c")
        assert vitamin_c is not None
        assert vitamin_c == pytest.approx(round(28.1 / 90.0 * 100, 1))

    def test_unknown_nutrient_skipped(self, tmp_path):
        db_path = tmp_path / "usda_unknown_nutrient.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT NOT NULL, data_type TEXT)")
        c.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)")
        c.execute("CREATE TABLE food_nutrients (fdc_id INTEGER, nutrient_id INTEGER, amount REAL)")
        c.execute("INSERT INTO foods VALUES (4001, 'Test Food', 'sr_legacy_food')")
        c.execute("INSERT INTO foods_fts VALUES ('Test Food', 4001)")
        c.executemany("INSERT INTO food_nutrients VALUES (?, ?, ?)", [
            (4001, 1008, 100), (4001, 1003, 10), (4001, 9999, 50),
        ])
        conn.commit()
        conn.close()

        r = USDALocalResolver.__new__(USDALocalResolver)
        r.DB_PATH = db_path
        results = r.search("Test Food", page_size=1)
        assert len(results) > 0
