from unittest.mock import MagicMock

import pytest
import requests


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
    """载荷按 2026-10-23 实测修正：type=weight、unit=kilograms（旧写法静默不落库）。"""

    @staticmethod
    def _stub(adapter, existing=None):
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = {"items": existing or []}
        adapter.session.get.return_value = get_resp
        post_resp = MagicMock()
        post_resp.raise_for_status = MagicMock()
        post_resp.json.return_value = {"items": [{"id": "1", "value": 1}]}
        adapter.session.post.return_value = post_resp

    def test_success(self, adapter):
        self._stub(adapter)

        result = adapter.record_weight(75.5, "2026-01-01")
        assert result["status"] == "ok"
        assert result["weight_kg"] == 75.5
        assert result["date"] == "2026-01-01"

    def test_posts_to_measurements(self, adapter):
        self._stub(adapter)

        adapter.record_weight(70.0, "2026-01-01")
        call_args = adapter.session.post.call_args
        assert "measurements" in call_args[0][0]

    def test_payload_structure(self, adapter):
        self._stub(adapter)

        adapter.record_weight(80.0, "2026-06-15")
        payload = adapter.session.post.call_args[1]["json"]
        assert payload["items"][0]["value"] == 80.0
        assert payload["items"][0]["unit"] == "kilograms"
        assert payload["items"][0]["type"] == "weight"
        assert "measurement_type" not in payload["items"][0]

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

    def test_falls_back_to_web_on_404(self, adapter):
        """v2 无 nutrition_goals 端点时必须回退到网页日记解析。"""
        api_resp = MagicMock()
        api_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error", response=MagicMock(status_code=404)
        )
        web_html = (
            '<table><tr class="total alt"><td class="first">Your Daily Goal </td>'
            "<td>2,800</td><td>280 <span>40</span></td><td>93 <span>30</span></td>"
            "<td>210 <span>30</span></td><td>2,300</td><td>105</td></tr></table>"
        )
        web_resp = MagicMock()
        web_resp.raise_for_status = MagicMock()
        web_resp.text = web_html
        adapter.session.get.side_effect = [api_resp, web_resp]

        goals = adapter.get_nutrition_goals("2026-01-01")
        assert goals["energy"]["value"] == 2800
        assert goals["carbohydrates"] == 280
        assert goals["fat"] == 93
        assert goals["protein"] == 210
        assert adapter.session.get.call_count == 2

    def test_reraises_non_404(self, adapter):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "401 Client Error", response=MagicMock(status_code=401)
        )
        adapter.session.get.return_value = resp

        with pytest.raises(requests.exceptions.HTTPError):
            adapter.get_nutrition_goals("2026-01-01")

    def test_web_fallback_without_goal_row(self, adapter):
        api_resp = MagicMock()
        api_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error", response=MagicMock(status_code=404)
        )
        web_resp = MagicMock()
        web_resp.raise_for_status = MagicMock()
        web_resp.text = "<html><body>no goals here</body></html>"
        adapter.session.get.side_effect = [api_resp, web_resp]

        with pytest.raises(ValueError, match="Your Daily Goal"):
            adapter.get_nutrition_goals("2026-01-01")

    def test_web_fallback_with_incomplete_goal_row(self, adapter):
        """目标行存在但数值不足 4 列时（页面改版）应显式失败而不是返回脏数据。"""
        api_resp = MagicMock()
        api_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error", response=MagicMock(status_code=404)
        )
        web_resp = MagicMock()
        web_resp.raise_for_status = MagicMock()
        web_resp.text = '<tr><td>Your Daily Goal </td><td>2,800</td><td>280</td></tr>'
        adapter.session.get.side_effect = [api_resp, web_resp]

        with pytest.raises(ValueError, match="解析失败"):
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


class TestGoalsSourceAndSodium:
    def test_web_goal_row_includes_sodium_and_sugar(self, adapter):
        api_resp = MagicMock()
        api_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error", response=MagicMock(status_code=404)
        )
        web_resp = MagicMock()
        web_resp.raise_for_status = MagicMock()
        web_resp.text = (
            '<tr><td>Your Daily Goal </td><td>2,809</td><td>281</td>'
            "<td>93</td><td>211</td><td>2,300</td><td>50</td></tr>"
        )
        adapter.session.get.side_effect = [api_resp, web_resp]

        goals = adapter.get_nutrition_goals("2026-01-01")
        assert goals["sodium"] == 2300
        assert goals["sugar"] == 50
        assert goals["_source"] == "web"

    def test_api_goals_are_tagged_as_api(self, adapter):
        resp = MagicMock()
        resp.json.return_value = {"items": [{"energy": {"value": 2500}, "protein": 200}]}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        goals = adapter.get_nutrition_goals("2026-01-01")
        assert goals["_source"] == "api"
