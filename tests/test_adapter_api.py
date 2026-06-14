import json
from unittest.mock import MagicMock, patch

import pytest
from mfp_adapter import MFPAdapter, SessionExpiredError


class TestGetDiaryData:
    def test_success(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"type": "diary_meal", "meal_name": "Lunch"}]}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        data = adapter.get_diary_data("2026-01-01")
        assert "items" in data
        assert data["items"][0]["type"] == "diary_meal"

    def test_calls_ensure_token(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": []}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        adapter.get_diary_data("2026-01-01")
        adapter.session.get.assert_called_once()

    def test_api_error(self, adapter):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("API error")
        adapter.session.get.return_value = resp

        with pytest.raises(Exception, match="API error"):
            adapter.get_diary_data("2026-01-01")


class TestRecordWeight:
    def test_success(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        result = adapter.record_weight(75.5, "2026-01-01")
        assert result["status"] == "ok"
        assert result["weight_kg"] == 75.5
        assert result["date"] == "2026-01-01"

    def test_posts_to_measurements(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        adapter.record_weight(70.0, "2026-01-01")
        call_args = adapter.session.post.call_args
        assert "measurements" in call_args[0][0]

    def test_payload_structure(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        adapter.record_weight(80.0, "2026-06-15")
        payload = adapter.session.post.call_args[1]["json"]
        assert payload["items"][0]["value"] == 80.0
        assert payload["items"][0]["unit"] == "kg"
        assert payload["items"][0]["measurement_type"] == "weight"


class TestRecordWater:
    def test_success(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        result = adapter.record_water(500, "2026-01-01")
        assert result["status"] == "ok"
        assert result["ml"] == 500

    def test_posts_to_water_endpoint(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        adapter.record_water(250, "2026-01-01")
        call_args = adapter.session.post.call_args
        assert "water" in call_args[0][0]

    def test_payload_units(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        adapter.record_water(100, "2026-01-01")
        payload = adapter.session.post.call_args[1]["json"]
        assert payload["units"] == "milliliters"
        assert payload["value"] == 100

    def test_updates_headers(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        adapter.record_water(100, "2026-01-01")
        assert "mfp-client-id" in adapter.session.headers
        assert "mfp-user-id" in adapter.session.headers


class TestGetNutritionGoals:
    def test_success(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"energy": {"value": 2500}}]}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        goals = adapter.get_nutrition_goals("2026-01-01")
        assert goals["energy"]["value"] == 2500

    def test_empty_items(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": []}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        with pytest.raises(IndexError):
            adapter.get_nutrition_goals("2026-01-01")


class TestPostDiaryEntry:
    def test_success(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        entry = {"type": "food_entry", "date": "2026-01-01"}
        adapter._post_diary_entry(entry)
        adapter.session.post.assert_called_once()

    def test_payload_wrapped(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        adapter.session.post.return_value = resp

        entry = {"type": "food_entry"}
        adapter._post_diary_entry(entry)
        payload = adapter.session.post.call_args[1]["json"]
        assert "items" in payload
        assert payload["items"][0] == entry
