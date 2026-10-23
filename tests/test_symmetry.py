"""删除/修改对称性：体重可改可删、饮水可清、食物条目可替换。

真实接口事实（2026-10-23 实测）：
  POST   /v2/measurements  正确载荷 {type:"weight", date, value, unit:"kilograms"}
                           -> 200，返回 items；旧代码用 type:"measurement" 会静默不落库
  同日重复 POST             -> 返回旧记录，不会更新（必须删旧再写）
  DELETE /v2/measurements/{数字id} -> 204
  POST   /v2/diary/water {value:0} -> 200/201，milliliters=0（upsert，可清饮水）
  PATCH  /v2/diary/{id}     -> 400（schema 未知），所以「改」只能删+重写
"""

from unittest.mock import MagicMock, patch

import pytest


def _resp(payload=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload if payload is not None else {"items": []}
    return resp


class TestRecordWeightPayload:
    def test_uses_type_weight_and_kilograms(self, adapter):
        adapter.session.get.return_value = _resp({"items": []})
        adapter.session.post.return_value = _resp({"items": [{"id": "1", "value": 71.2}]})

        adapter.record_weight(71.2, "2026-10-23")

        item = adapter.session.post.call_args[1]["json"]["items"][0]
        assert item["type"] == "weight"
        assert item["unit"] == "kilograms"
        assert item["value"] == 71.2
        assert "measurement_type" not in item

    def test_replaces_existing_value(self, adapter):
        adapter.session.get.return_value = _resp(
            {"items": [{"id": "207495583387301", "date": "2026-10-23", "value": 70.0}]}
        )
        adapter.session.delete.return_value = _resp(status_code=204)
        adapter.session.post.return_value = _resp({"items": [{"id": "2", "value": 71.2}]})

        result = adapter.record_weight(71.2, "2026-10-23")

        assert result["status"] == "ok"
        assert "207495583387301" in adapter.session.delete.call_args[0][0]
        assert adapter.session.post.called

    def test_same_value_is_idempotent(self, adapter):
        adapter.session.get.return_value = _resp(
            {"items": [{"id": "207495583387301", "date": "2026-10-23", "value": 71.2}]}
        )

        result = adapter.record_weight(71.2, "2026-10-23")

        assert result["unchanged"] is True
        adapter.session.post.assert_not_called()
        adapter.session.delete.assert_not_called()

    def test_raises_when_server_swallows_write(self, adapter):
        adapter.session.get.return_value = _resp({"items": []})
        adapter.session.post.return_value = _resp({"items": []})

        with pytest.raises(RuntimeError):
            adapter.record_weight(71.2, "2026-10-23")


class TestDeleteWeight:
    def test_deletes_matching_date(self, adapter):
        adapter.session.get.return_value = _resp(
            {
                "items": [
                    {"id": "111", "date": "2026-10-22", "value": 71.2},
                    {"id": "222", "date": "2026-10-23", "value": 70.8},
                ]
            }
        )
        adapter.session.delete.return_value = _resp(status_code=204)

        deleted = adapter.delete_weight("2026-10-23")

        assert deleted == [70.8]
        assert "222" in adapter.session.delete.call_args[0][0]
        assert "111" not in adapter.session.delete.call_args[0][0]

    def test_returns_empty_when_no_record(self, adapter):
        adapter.session.get.return_value = _resp(
            {"items": [{"id": "111", "date": "2026-10-22", "value": 71.2}]}
        )

        assert adapter.delete_weight("2026-10-23") == []
        adapter.session.delete.assert_not_called()


class TestDeleteMeasurementTool:
    def test_weight(self, mock_get_adapter):
        mock_get_adapter.delete_weight.return_value = [70.8]
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            result = delete_measurement("weight", "2026-10-23")
        assert "已删除" in result
        assert "70.8" in result

    def test_weight_missing(self, mock_get_adapter):
        mock_get_adapter.delete_weight.return_value = []
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            result = delete_measurement("weight", "2026-10-23")
        assert "没有" in result

    def test_water_clears(self, mock_get_adapter):
        mock_get_adapter.get_water.return_value = 350.0
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            result = delete_measurement("water", "2026-10-23")
        assert "350" in result
        mock_get_adapter.record_water.assert_called_once_with(0, "2026-10-23")

    def test_water_already_zero(self, mock_get_adapter):
        mock_get_adapter.get_water.return_value = 0.0
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            result = delete_measurement("water", "2026-10-23")
        assert "本来就是 0" in result
        mock_get_adapter.record_water.assert_not_called()

    def test_unknown_type(self, mock_get_adapter):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            result = delete_measurement("height", "2026-10-23")
        assert "weight" in result and "water" in result

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.delete_weight.side_effect = Exception("boom")
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_measurement
            assert "失败" in delete_measurement("weight", "2026-10-23")


class TestUpdateEntryTool:
    def _entries(self, *extra):
        base = [
            {"id": "111", "name": "Oats", "meal": "Breakfast", "calories": 300.0},
            {"id": "112", "name": "Oats", "meal": "Lunch", "calories": 300.0},
            {"id": "113", "name": "Chicken", "meal": "Dinner", "calories": 400.0},
        ]
        return list(extra) if extra else base

    def _item(self, **kwargs):
        from mfp_adapter import FoodItemModel
        return FoodItemModel(**{"name": "Oatmeal", "calories": 350, **kwargs})

    def test_replaces_by_id_and_keeps_meal(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = [
            [{"id": "113", "name": "Chicken", "meal": "Dinner", "calories": 400.0}],
            [{"id": "999", "name": "Oatmeal", "meal": "Dinner", "calories": 350.0}],
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", entry_id="113")

        assert "Oatmeal" in result and "替换" in result
        mock_get_adapter.delete_diary_entry.assert_called_once_with("113")
        call = mock_get_adapter.record_nutrition.call_args
        assert call[0][0] == "2026-10-23"
        assert call[0][1] == "dinner"
        assert call[0][2][0]["name"] == "Oatmeal"

    def test_meal_type_override(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = [
            {"id": "113", "name": "Chicken", "meal": "Dinner", "calories": 400.0}
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {"status": "ok", "count": 1}

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            update_entry(self._item(meal_type="lunch"), "2026-10-23", entry_id="113")

        assert mock_get_adapter.record_nutrition.call_args[0][1] == "lunch"

    def test_unknown_id(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self._entries()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", entry_id="404")
        assert "没有找到" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_ambiguous_name(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self._entries()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", name="Oats")
        assert "多个" in result
        mock_get_adapter.delete_diary_entry.assert_not_called()

    def test_delete_failure(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self._entries()
        mock_get_adapter.delete_diary_entry.return_value = False
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", entry_id="111")
        assert "失败" in result
        mock_get_adapter.record_nutrition.assert_not_called()

    def test_write_failure_after_delete_is_reported(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.return_value = self._entries()
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.side_effect = Exception("network down")

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", entry_id="111")

        assert "旧条目已删除" in result
        assert "network down" in result

    def test_warns_when_new_entry_not_found_after_write(self, mock_get_adapter):
        mock_get_adapter.get_food_entries_from_html.side_effect = [
            [{"id": "111", "name": "Oats", "meal": "Breakfast", "calories": 300.0}],
            [],
        ]
        mock_get_adapter.delete_diary_entry.return_value = True
        mock_get_adapter.record_nutrition.return_value = {
            "status": "ok", "count": 1,
            "warnings": ["⚠️ 未匹配到营养数据"],
        }

        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23", entry_id="111")

        assert "未能确认" in result
        assert "未匹配到营养数据" in result

    def test_requires_target(self, mock_get_adapter):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import update_entry
            result = update_entry(self._item(), "2026-10-23")
        assert "entry_id" in result and "name" in result
