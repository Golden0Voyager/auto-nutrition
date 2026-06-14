import json
import os
from unittest.mock import MagicMock, patch

import pytest
from mfp_adapter import MFPAdapter


@pytest.fixture
def adapter(tmp_path):
    a = MFPAdapter.__new__(MFPAdapter)
    a.JOURNAL_FILE = str(tmp_path / "journal.json")
    a._JOURNAL_MAX_ENTRIES = 200
    return a


class TestLogToLocalJournal:
    def test_creates_journal_file(self, adapter):
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snacks", items)
        assert os.path.exists(adapter.JOURNAL_FILE)

    def test_journal_content_structure(self, adapter):
        items = [{"name": "Apple", "calories": 95, "macros": {"protein": 0.5}}]
        adapter._log_to_local_journal("2026-01-01", "Lunch", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        assert len(journal) == 1
        entry = journal[0]
        assert "timestamp" in entry
        assert entry["date"] == "2026-01-01"
        assert entry["meal_name"] == "Lunch"
        assert len(entry["items"]) == 1

    def test_cleans_internal_fields(self, adapter):
        items = [{"name": "Apple", "calories": 95, "_config_matched": True, "_unmatched": False}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "_config_matched" not in item
        assert "_unmatched" not in item

    def test_cleans_none_values(self, adapter):
        items = [{"name": "Apple", "calories": 95, "fiber": None}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "fiber" not in item

    def test_cleans_empty_nested_dict(self, adapter):
        items = [{"name": "Apple", "macros": {}}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "macros" not in item

    def test_cleans_none_in_nested_dict(self, adapter):
        items = [{"name": "Apple", "macros": {"protein": 0.5, "fiber": None}}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "fiber" not in item["macros"]
        assert item["macros"]["protein"] == 0.5

    def test_appends_to_existing_journal(self, adapter):
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)
        adapter._log_to_local_journal("2026-01-01", "Lunch", [{"name": "Rice", "calories": 200}])

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        assert len(journal) == 2

    def test_max_entries_trimming(self, adapter):
        adapter._JOURNAL_MAX_ENTRIES = 2

        for i in range(4):
            adapter._log_to_local_journal(f"2026-01-0{i+1}", "Lunch", [{"name": f"Food {i}", "calories": 100}])

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        assert len(journal) == 2
        assert journal[0]["items"][0]["name"] == "Food 2"
        assert journal[1]["items"][0]["name"] == "Food 3"

    def test_atomic_write_no_corruption(self, adapter):
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_utf8_content(self, adapter):
        items = [{"name": "煎鸡蛋", "calories": 90}]
        adapter._log_to_local_journal("2026-01-01", "早餐", items)

        with open(adapter.JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)

        assert journal[0]["items"][0]["name"] == "煎鸡蛋"
        assert journal[0]["meal_name"] == "早餐"

    def test_journal_permission_error(self, adapter):
        adapter.JOURNAL_FILE = "/nonexistent/path/journal.json"
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)
        assert not os.path.exists("/nonexistent/path/journal.json")

    def test_json_dump_failure_cleanup(self, adapter):
        call_count = [0]
        original_replace = os.replace

        def mock_replace(src, dst):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("JSON serialization failed")
            return original_replace(src, dst)

        with patch("mfp_adapter.os.replace", side_effect=mock_replace):
            items = [{"name": "Apple", "calories": 95}]
            adapter._log_to_local_journal("2026-01-01", "Snack", items)
