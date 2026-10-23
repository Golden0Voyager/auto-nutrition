"""护栏与降级路径：读回校验、journal 损坏、体重读取、删除幂等。

这些分支平时不触发，一旦触发就决定「数据会不会说错话」：
回读校验抛异常时若当成已落库会漏写一条；journal 损坏时若直接抛异常，
整组撤销和趋势分析会一起挂掉。所以它们需要被钉住，而不是靠巧合。
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tests.conftest import mock_create_food


def _resp(payload=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload if payload is not None else {"items": []}
    return resp


class TestGetLatestWeight:
    def test_returns_most_recent_value(self, adapter):
        adapter.session.get.return_value = _resp({"items": [{"value": 71.5}]})

        assert adapter.get_latest_weight() == 71.5
        assert adapter.session.get.call_args[0][0].endswith("/measurements")
        assert adapter.session.get.call_args[1]["params"] == {"type": "weight"}

    def test_returns_none_without_records(self, adapter):
        adapter.session.get.return_value = _resp({"items": []})
        assert adapter.get_latest_weight() is None

    def test_returns_none_for_null_value(self, adapter):
        adapter.session.get.return_value = _resp({"items": [{"value": None}]})
        assert adapter.get_latest_weight() is None

    def test_returns_none_for_non_numeric_value(self, adapter):
        adapter.session.get.return_value = _resp({"items": [{"value": "seventy"}]})
        assert adapter.get_latest_weight() is None


class TestDeleteMeasurementPrimitive:
    def test_missing_id_is_noop(self, adapter):
        assert adapter._delete_measurement(None) is False
        adapter.session.delete.assert_not_called()

    def test_already_gone_returns_false(self, adapter):
        adapter.session.delete.return_value = _resp(status_code=404)
        assert adapter._delete_measurement("123") is False


class TestRecordNutritionReadbackGuard:
    def test_verify_closure_reads_back_against_pre_write_snapshot(self, adapter, monkeypatch):
        mock_create_food(adapter)
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _seconds: None)
        adapter.get_food_entries_from_html = MagicMock(
            side_effect=[[], [{"meal": "Lunch", "name": "Oats"}]]
        )
        captured = {}

        def fake_post(entry, verify=None):
            captured["verify"] = verify
            captured["result"] = verify()
            return True

        adapter._post_diary_entry = fake_post
        adapter.record_nutrition("2026-10-23", "lunch", [{"name": "Oats", "calories": 300, "macros": {}}])

        # 闭包真的执行了：一次取基线，一次回读
        assert adapter.get_food_entries_from_html.call_count == 2
        assert captured["result"] is True


class TestPostDiaryEntryGuard:
    def test_verify_exception_is_treated_as_not_written(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _seconds: None)
        adapter.session.post.side_effect = requests.exceptions.Timeout("slow")

        def broken_verify():
            raise RuntimeError("readback failed")

        with pytest.raises(requests.exceptions.Timeout):
            adapter._post_diary_entry({"type": "food_entry"}, verify=broken_verify)

        # 校验异常按「未落库」处理 → 仍然重试满 3 次后抛原始异常
        assert adapter.session.post.call_count == 3


class TestJournalDegradedPaths:
    def test_corrupt_journal_reads_as_empty(self, adapter):
        Path(adapter.JOURNAL_FILE).write_text("{broken", encoding="utf-8")

        assert adapter._read_journal() == []

    def test_write_failure_returns_false_and_removes_temp_file(self, adapter, tmp_path):
        with patch("mfp_adapter.os.replace", side_effect=OSError("disk full")):
            assert adapter._write_journal([{"date": "2026-10-23"}]) is False

        # 临时文件不能留在日志目录里
        assert list(tmp_path.iterdir()) == []

    def test_remove_from_journal_ignores_corrupt_file(self, adapter):
        Path(adapter.JOURNAL_FILE).write_text("not json", encoding="utf-8")

        assert adapter._remove_from_journal("2026-10-23", "Lunch", "Oats") == 0

    def test_remove_from_journal_reports_write_failure(self, adapter):
        entry = {"date": "2026-10-23", "meal_name": "Lunch", "items": [{"name": "Oats"}]}
        Path(adapter.JOURNAL_FILE).write_text(json.dumps([entry]), encoding="utf-8")

        with patch("mfp_adapter.os.replace", side_effect=OSError("disk full")):
            assert adapter._remove_from_journal("2026-10-23", "Lunch", "Oats") == 0

        # 写回失败时原日志必须保持不变（不能出现「删了一半」的状态）
        assert json.loads(Path(adapter.JOURNAL_FILE).read_text(encoding="utf-8")) == [entry]


class TestExerciseBaselineFallback:
    def test_unreadable_baseline_disables_readback_guard(self, adapter):
        adapter.get_diary_data = MagicMock(side_effect=RuntimeError("diary down"))
        captured = {}

        def fake_post(entry, verify=None):
            captured["verify"] = verify
            return True

        adapter._post_diary_entry = fake_post
        entry = adapter.record_exercise_entry("2026-10-23", "ex-1", duration_min=30, calories=200)

        assert captured["verify"] is None
        assert entry["duration"] == 1800
