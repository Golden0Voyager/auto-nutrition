import json
import os
from unittest.mock import patch

import pytest

from mfp_adapter import MFPAdapter, _normalize_entry_name


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

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
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

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "_config_matched" not in item
        assert "_unmatched" not in item

    def test_cleans_none_values(self, adapter):
        items = [{"name": "Apple", "calories": 95, "fiber": None}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "fiber" not in item

    def test_cleans_empty_nested_dict(self, adapter):
        items = [{"name": "Apple", "macros": {}}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "macros" not in item

    def test_cleans_none_in_nested_dict(self, adapter):
        items = [{"name": "Apple", "macros": {"protein": 0.5, "fiber": None}}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        item = journal[0]["items"][0]
        assert "fiber" not in item["macros"]
        assert item["macros"]["protein"] == 0.5

    def test_appends_to_existing_journal(self, adapter):
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)
        adapter._log_to_local_journal("2026-01-01", "Lunch", [{"name": "Rice", "calories": 200}])

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        assert len(journal) == 2

    def test_max_entries_trimming(self, adapter):
        adapter._JOURNAL_MAX_ENTRIES = 2

        for i in range(4):
            adapter._log_to_local_journal(f"2026-01-0{i+1}", "Lunch", [{"name": f"Food {i}", "calories": 100}])

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)

        assert len(journal) == 2
        assert journal[0]["items"][0]["name"] == "Food 2"
        assert journal[1]["items"][0]["name"] == "Food 3"

    def test_overflow_is_archived_not_dropped(self, adapter):
        """超出窗口的旧记录必须转存归档，不能在截断时静默消失。"""
        adapter._JOURNAL_MAX_ENTRIES = 2

        for i in range(4):
            adapter._log_to_local_journal(f"2026-01-0{i+1}", "Lunch", [{"name": f"Food {i}", "calories": 100}])

        archive_file = os.path.join(os.path.dirname(adapter.JOURNAL_FILE), "nutrition_journal_archive.json")
        assert os.path.exists(archive_file)
        with open(archive_file, encoding="utf-8") as f:
            archive = json.load(f)

        archived_names = [e["items"][0]["name"] for e in archive]
        assert archived_names == ["Food 0", "Food 1"]

        # 归档 + 窗口 = 原始 4 条，一条不少
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert [e["items"][0]["name"] for e in journal] + archived_names == [
            "Food 2", "Food 3", "Food 0", "Food 1",
        ]

    def test_retry_after_journal_write_failure_does_not_duplicate_archive(self, adapter):
        """归档成功而 journal 写失败时，重试不得反复追加同一条旧记录。"""
        adapter._JOURNAL_MAX_ENTRIES = 1
        adapter._log_to_local_journal("2026-01-01", "Lunch", [{"name": "Old", "calories": 100}])

        original_replace = os.replace
        failed = False

        def fail_journal_once(src, dst):
            nonlocal failed
            if not failed and dst == adapter.JOURNAL_FILE:
                failed = True
                raise OSError("simulated journal write failure")
            return original_replace(src, dst)

        with patch("mfp_adapter.os.replace", side_effect=fail_journal_once):
            adapter._log_to_local_journal("2026-01-02", "Lunch", [{"name": "New", "calories": 200}])
        adapter._log_to_local_journal("2026-01-02", "Lunch", [{"name": "New", "calories": 200}])

        archive_file = os.path.join(os.path.dirname(adapter.JOURNAL_FILE), "nutrition_journal_archive.json")
        with open(archive_file, encoding="utf-8") as f:
            archive = json.load(f)
        assert [entry["items"][0]["name"] for entry in archive] == ["Old"]

    def test_atomic_write_no_corruption(self, adapter):
        items = [{"name": "Apple", "calories": 95}]
        adapter._log_to_local_journal("2026-01-01", "Snack", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_utf8_content(self, adapter):
        items = [{"name": "煎鸡蛋", "calories": 90}]
        adapter._log_to_local_journal("2026-01-01", "早餐", items)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
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


class TestArchiveFailureKeepsJournal:
    """归档出任何问题时都必须保留全部 journal 条目——宁可文件大，不可丢数据。"""

    def _fill(self, adapter, count=4):
        for i in range(count):
            adapter._log_to_local_journal(
                f"2026-01-0{i+1}", "Lunch", [{"name": f"Food {i}", "calories": 100}]
            )

    def test_corrupt_archive_file_keeps_all_entries(self, adapter):
        adapter._JOURNAL_MAX_ENTRIES = 2
        archive_file = os.path.join(
            os.path.dirname(adapter.JOURNAL_FILE), "nutrition_journal_archive.json"
        )
        with open(archive_file, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")

        self._fill(adapter)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert len(journal) == 4, "归档读不出来时不能截断 journal"

    def test_archive_write_failure_keeps_all_entries(self, adapter):
        adapter._JOURNAL_MAX_ENTRIES = 2
        real_replace = os.replace

        def flaky_replace(src, dst):
            if str(dst).endswith("nutrition_journal_archive.json"):
                raise OSError("disk full")
            return real_replace(src, dst)

        with patch("mfp_adapter.os.replace", side_effect=flaky_replace):
            self._fill(adapter)

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert len(journal) == 4, "归档写不进去时不能截断 journal"

    def test_malformed_items_do_not_crash(self, adapter):
        """items 不是 dict 时只记错误日志，不能把异常抛给调用方。"""
        adapter._log_to_local_journal("2026-01-01", "Lunch", [None])
        assert not os.path.exists(adapter.JOURNAL_FILE)


class TestRemoveFromJournal:
    def test_removes_matching_item(self, adapter):
        adapter._log_to_local_journal("2026-10-23", "Breakfast", [{"name": "Oats", "calories": 300}])
        removed = adapter._remove_from_journal("2026-10-23", "Breakfast", "Oats")
        assert removed == 1
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            assert json.load(f) == []

    def test_keeps_other_items_in_same_meal(self, adapter):
        adapter._log_to_local_journal(
            "2026-10-23", "Breakfast",
            [{"name": "Oats", "calories": 300}, {"name": "Egg", "calories": 100}],
        )
        assert adapter._remove_from_journal("2026-10-23", "Breakfast", "Oats") == 1
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert [i["name"] for i in journal[0]["items"]] == ["Egg"]

    def test_returns_zero_when_no_match(self, adapter):
        adapter._log_to_local_journal("2026-10-23", "Breakfast", [{"name": "Oats", "calories": 300}])
        assert adapter._remove_from_journal("2026-10-23", "Lunch", "Oats") == 0

    def test_missing_journal_file_returns_zero(self, adapter):
        assert adapter._remove_from_journal("2026-10-23", "Breakfast", "Oats") == 0


class TestNormalizeEntryName:
    """网页端条目名 → journal 裸名。

    真实事故：删除肌酸时提示「本地日志无匹配项」，journal 留脏数据，
    趋势虚高。原因是网页显示 ``Auto_Nutrition - 肌酸, 1 serving(s)``，
    而 journal 里只有 ``肌酸``，`==` 恒失配。
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Auto_Nutrition - Whey Protein, 1 serving(s)", "Whey Protein"),
            ("Auto_Nutrition - 肌酸, 1 serving(s)", "肌酸"),
            ("Auto_Nutrition - Oats, 2 servings", "Oats"),
            ("Auto_Nutrition - Apple", "Apple"),
            ("Whey Protein", "Whey Protein"),
            ("纯牛奶 - 牛奶, 250 ml", "纯牛奶 - 牛奶, 250 ml"),
            ("Milk (Full Cream, 300ml)", "Milk (Full Cream, 300ml)"),
            ("", ""),
        ],
    )
    def test_strips_brand_and_serving(self, raw, expected):
        assert _normalize_entry_name(raw) == expected

    def test_removes_item_reported_with_brand_prefix(self, adapter):
        """端到端：用网页端带前缀的名字删除，journal 必须同步掉。"""
        adapter._log_to_local_journal(
            "2026-10-23", "Dinner",
            [{"name": "肌酸", "calories": 0}, {"name": "鱼油", "calories": 20}],
        )

        removed = adapter._remove_from_journal(
            "2026-10-23", "Dinner", "Auto_Nutrition - 肌酸, 1 serving(s)"
        )

        assert removed == 1
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        assert [i["name"] for i in journal[0]["items"]] == ["鱼油"]

    def test_match_is_case_insensitive(self, adapter):
        adapter._log_to_local_journal("2026-10-23", "Snack", [{"name": "Whey Protein", "calories": 120}])

        assert adapter._remove_from_journal(
            "2026-10-23", "Snack", "Auto_Nutrition - whey protein, 1 serving(s)"
        ) == 1

    def test_empty_name_does_not_wipe_journal(self, adapter):
        """空名字归一化后为空，必须直接放弃，不能匹配到任意空名条目。"""
        adapter._log_to_local_journal("2026-10-23", "Snack", [{"name": "", "calories": 10}])

        assert adapter._remove_from_journal("2026-10-23", "Snack", "Auto_Nutrition - , 1 serving(s)") == 0
