"""套餐整组撤销：record_meal 打 group 标记，delete_meal_group 按组回滚。

设计取舍：MFP 没有「套餐条目」——record_meal 是按套餐数值展开成逐条
food_entry 写入的。因此撤销只能靠本地 journal 记住「这一批是哪个套餐」，
再按名字把对应日记条目逐条删掉。这不是服务端事务，删到一半失败时
保留 group 标记，方便重试。
"""

import json
from unittest.mock import MagicMock, patch


def _resp(payload=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload if payload is not None else {}
    return resp


class TestRecordMealTagsGroup:
    def test_logs_group_id_and_returns_it(self, adapter):
        adapter._ensure_token_valid = MagicMock()
        adapter.get_my_meals = MagicMock(return_value=[{
            "meal_id": 7,
            "name": "High Protein Lunch",
            "foods": [{"description": "Chicken", "calories": 300}],
            "totals": {"calories": 300, "protein": 50, "carbs": 0, "fat": 5},
        }])
        adapter._create_custom_food = MagicMock(return_value={"id": "f1", "version": 1})
        adapter._post_diary_entry = MagicMock()
        adapter._log_to_local_journal = MagicMock()

        result = adapter.record_meal("2026-10-23", "lunch", 7)

        assert result["group_id"]
        kwargs = adapter._log_to_local_journal.call_args[1]
        assert kwargs["group_id"] == result["group_id"]

    def test_each_batch_gets_a_distinct_group(self, adapter):
        adapter._ensure_token_valid = MagicMock()
        adapter.get_my_meals = MagicMock(return_value=[{
            "meal_id": 7,
            "name": "Lunch",
            "foods": [{"description": "Chicken", "calories": 300}],
            "totals": {"calories": 300, "protein": 0, "carbs": 0, "fat": 0},
        }])
        adapter._create_custom_food = MagicMock(return_value={"id": "f1", "version": 1})
        adapter._post_diary_entry = MagicMock()
        adapter._log_to_local_journal = MagicMock()

        first = adapter.record_meal("2026-10-23", "lunch", 7)
        second = adapter.record_meal("2026-10-23", "lunch", 7)

        assert first["group_id"] != second["group_id"]


class TestJournalGroups:
    def _write(self, adapter, entries):
        with open(adapter.JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f)

    def test_lists_grouped_entries_only(self, adapter):
        self._write(adapter, [
            {"date": "2026-10-23", "meal_name": "Lunch", "group_id": "g1",
             "timestamp": "2026-10-23T12:00:00",
             "items": [{"name": "Chicken", "source_meal": "High Protein"}]},
            {"date": "2026-10-23", "meal_name": "Dinner",
             "items": [{"name": "手动录入的"}]},
            {"date": "2026-10-22", "meal_name": "Lunch", "group_id": "g0",
             "items": [{"name": "旧套餐"}]},
        ])

        groups = adapter._journal_groups("2026-10-23")

        assert len(groups) == 1
        assert groups[0]["group_id"] == "g1"
        assert groups[0]["meal"] == "High Protein"
        assert groups[0]["items"] == ["Chicken"]

    def test_no_journal_file(self, adapter):
        assert adapter._journal_groups("2026-10-23") == []

    def test_remove_group_only_touches_target(self, adapter):
        self._write(adapter, [
            {"date": "2026-10-23", "meal_name": "Lunch", "group_id": "g1", "items": [{"name": "A"}]},
            {"date": "2026-10-23", "meal_name": "Lunch", "group_id": "g2", "items": [{"name": "B"}]},
        ])

        assert adapter.remove_journal_group("2026-10-23", "g1") is True
        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            left = json.load(f)
        assert [e["group_id"] for e in left] == ["g2"]

    def test_remove_missing_group(self, adapter):
        self._write(adapter, [{"date": "2026-10-23", "group_id": "g1", "items": [{"name": "A"}]}])
        assert adapter.remove_journal_group("2026-10-23", "nope") is False


class TestDeleteMealGroupTool:
    def _groups(self):
        return [
            {"group_id": "g1", "meal_name": "Lunch", "meal": "High Protein",
             "timestamp": "2026-10-23T12:00:00", "items": ["Chicken", "Rice"]},
            {"group_id": "g2", "meal_name": "Lunch", "meal": "High Protein",
             "timestamp": "2026-10-23T19:00:00", "items": ["Chicken"]},
        ]

    def _diary(self):
        return [
            {"id": "111", "name": "Auto_Nutrition - Chicken, 1 serving(s)", "meal": "Lunch"},
            {"id": "112", "name": "Auto_Nutrition - Rice, 1 serving(s)", "meal": "Lunch"},
            {"id": "113", "name": "Auto_Nutrition - Chicken, 1 serving(s)", "meal": "Lunch"},
        ]

    def test_lists_groups_when_no_target(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = self._groups()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23")
        assert "g1" in result and "g2" in result

    def test_no_groups(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = []
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23")
        assert "没有" in result

    def test_deletes_by_group_id(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = self._groups()
        mock_get_adapter.get_food_entries_from_html.return_value = self._diary()
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.remove_journal_group.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23", group_id="g1")

        assert "已撤销" in result and "2" in result
        deleted_ids = [c[0][0] for c in mock_get_adapter.delete_diary_entry.call_args_list]
        assert deleted_ids == ["111", "112"]
        mock_get_adapter.remove_journal_group.assert_called_once_with("2026-10-23", "g1")

    def test_matches_group_by_meal_name(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = [
            {"group_id": "g1", "meal_name": "Lunch", "meal": "High Protein",
             "timestamp": "t", "items": ["Chicken"]},
        ]
        mock_get_adapter.get_food_entries_from_html.return_value = self._diary()
        mock_get_adapter.delete_diary_entry.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            delete_meal_group("2026-10-23", meal_name="protein")

        mock_get_adapter.delete_diary_entry.assert_called_once_with("111")

    def test_ambiguous_meal_name_lists_candidates(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = self._groups()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23", meal_name="High Protein")
        assert "多个" in result
        assert "g1" in result and "g2" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_unknown_group_id(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = self._groups()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23", group_id="nope")
        assert "没有" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_partial_delete_keeps_group_for_retry(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = [
            {"group_id": "g1", "meal_name": "Lunch", "meal": "High Protein",
             "timestamp": "t", "items": ["Chicken", "Ghost"]},
        ]
        mock_get_adapter.get_food_entries_from_html.return_value = self._diary()
        mock_get_adapter.delete_diary_entry.return_value = True

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23", group_id="g1")

        assert "Ghost" in result
        assert "保留" in result
        mock_get_adapter.remove_journal_group.assert_not_called()

    def test_skips_entries_from_other_meals(self, mock_get_adapter):
        mock_get_adapter._journal_groups.return_value = [
            {"group_id": "g1", "meal_name": "Lunch", "meal": "High Protein",
             "timestamp": "t", "items": ["Chicken"]},
        ]
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "999", "name": "Auto_Nutrition - Chicken, 1 serving(s)", "meal": "Dinner"},
        ]
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            result = delete_meal_group("2026-10-23", group_id="g1")
        mock_get_adapter.delete_diary_entry.assert_not_called()
        assert "保留" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter._journal_groups.side_effect = Exception("boom")
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_meal_group
            assert "失败" in delete_meal_group("2026-10-23")
