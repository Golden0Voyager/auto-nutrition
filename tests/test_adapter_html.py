from unittest.mock import MagicMock

import pytest

SAMPLE_HTML = """
<html>
<body>
<table>
<tr class="meal_header"><td colspan="2">Breakfast</td></tr>
<tr><td data-food-entry-id="1001">Apple</td></tr>
<tr><td data-food-entry-id="1002">Banana</td></tr>
<tr class="meal_header"><td colspan="2">Lunch</td></tr>
<tr><td data-food-entry-id="2001">Chicken Breast</td></tr>
<tr class="meal_header"><td colspan="2">Dinner</td></tr>
<tr><td data-food-entry-id="3001">Salmon</td></tr>
<tr class="meal_header"><td colspan="2">Snacks</td></tr>
<tr><td data-food-entry-id="4001">Protein Bar</td></tr>
</table>
</body>
</html>
"""


class TestGetFoodEntriesFromHtml:
    def test_parses_all_meals(self, adapter):
        resp = MagicMock()
        resp.text = SAMPLE_HTML
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        assert len(entries) == 5

    def test_entry_structure(self, adapter):
        resp = MagicMock()
        resp.text = SAMPLE_HTML
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        entry = entries[0]
        assert "id" in entry
        assert "name" in entry
        assert "meal" in entry

    def test_entry_ids(self, adapter):
        resp = MagicMock()
        resp.text = SAMPLE_HTML
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        ids = [e["id"] for e in entries]
        assert "1001" in ids
        assert "4001" in ids

    def test_meal_assignment(self, adapter):
        resp = MagicMock()
        resp.text = SAMPLE_HTML
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        apple = next(e for e in entries if e["id"] == "1001")
        assert apple["meal"] == "Breakfast"

        salmon = next(e for e in entries if e["id"] == "3001")
        assert salmon["meal"] == "Dinner"

    def test_empty_html(self, adapter):
        resp = MagicMock()
        resp.text = "<html><body></body></html>"
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        assert entries == []

    def test_only_known_meals(self, adapter):
        html = """
        <html><body>
        <tr class="meal_header"><td colspan="2">Breakfast</td></tr>
        <tr><td data-food-entry-id="1001">Apple</td></tr>
        <tr class="meal_header"><td colspan="2">Brunch</td></tr>
        <tr><td data-food-entry-id="2001">Toast</td></tr>
        </body></html>
        """
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        entries = adapter.get_food_entries_from_html("2026-01-01")
        assert len(entries) == 2

    def test_calls_correct_url(self, adapter):
        resp = MagicMock()
        resp.text = ""
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        adapter.get_food_entries_from_html("2026-06-15")
        call_args = adapter.session.get.call_args
        assert "2026-06-15" in call_args[0][0]


SAMPLE_HTML_WITH_MACROS = """
<html><body><table>
<tr class="meal_header"><td colspan="6">Breakfast</td></tr>
<tr>
  <td class="first alt"><a data-food-entry-id="1001" data-locale="" href="#">Rolled Oats, 1 cup</a></td>
  <td>300</td>
  <td><span class="macro-value">54</span><span class="macro-percentage">72</span></td>
  <td><span class="macro-value">5</span><span class="macro-percentage">15</span></td>
  <td><span class="macro-value">10</span><span class="macro-percentage">13</span></td>
  <td>0</td>
  <td>0</td>
  <td class="delete"><a href="/food/remove/1001">x</a></td>
</tr>
<tr>
  <td class="first alt"><a data-food-entry-id="1002" data-locale="" href="#">Fried Egg, 1 egg</a></td>
  <td>102</td>
  <td>1</td>
  <td>8</td>
  <td>6</td>
  <td>136</td>
  <td>0</td>
  <td class="delete"><a href="/food/remove/1002">x</a></td>
</tr>
<tr class="meal_header"><td colspan="6">Lunch</td></tr>
<tr>
  <td class="first alt"><a data-food-entry-id="2001" data-locale="" href="#">Chicken Breast, 200g</a></td>
  <td>330</td>
  <td>0</td>
  <td>7</td>
  <td>62</td>
  <td>148</td>
  <td>0</td>
  <td class="delete"><a href="/food/remove/2001">x</a></td>
</tr>
</table></body></html>
"""


class TestGetFoodEntriesMacros:
    def _entries(self, adapter, html=SAMPLE_HTML_WITH_MACROS):
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp
        return adapter.get_food_entries_from_html("2026-01-01")

    def test_calories_parsed(self, adapter):
        oats = next(e for e in self._entries(adapter) if e["id"] == "1001")
        assert oats["calories"] == 300

    def test_macro_column_order(self, adapter):
        oats = next(e for e in self._entries(adapter) if e["id"] == "1001")
        assert oats["carbs"] == 54
        assert oats["fat"] == 5
        assert oats["protein"] == 10

    def test_sodium_and_sugar(self, adapter):
        egg = next(e for e in self._entries(adapter) if e["id"] == "1002")
        assert egg["sodium"] == 136
        assert egg["sugar"] == 0

    def test_row_without_macros_defaults_to_zero(self, adapter):
        html = """
        <html><body><table>
        <tr class="meal_header"><td colspan="2">Breakfast</td></tr>
        <tr><td data-food-entry-id="9001">Quick Added Calories</td></tr>
        </table></body></html>
        """
        entry = self._entries(adapter, html)[0]
        assert entry["calories"] == 0
        assert entry["protein"] == 0


class TestDeleteDiaryEntry:
    def test_delete_success(self, adapter):
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="csrf123">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 204
        resp_del.raise_for_status = MagicMock()

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        result = adapter.delete_diary_entry("12345")
        assert result is True

    def test_delete_404_returns_false(self, adapter):
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="csrf123">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 404

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        result = adapter.delete_diary_entry("99999")
        assert result is False

    def test_csrf_token_caching(self, adapter):
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="cached_token">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 204
        resp_del.raise_for_status = MagicMock()

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        adapter.delete_diary_entry("111")
        adapter.delete_diary_entry("222")

        assert adapter.session.get.call_count == 1

    def test_csrf_no_match(self, adapter):
        resp_html = MagicMock()
        resp_html.text = "<html>no csrf here</html>"
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 204
        resp_del.raise_for_status = MagicMock()

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        result = adapter.delete_diary_entry("12345")
        assert result is True

    def test_delete_other_error_raises(self, adapter):
        import requests
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="x">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 500
        resp_del.raise_for_status.side_effect = requests.exceptions.HTTPError("server error")

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        with pytest.raises(requests.exceptions.HTTPError):
            adapter.delete_diary_entry("12345")

    def test_delete_status_200(self, adapter):
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="csrf123">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 200
        resp_del.raise_for_status = MagicMock()

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        result = adapter.delete_diary_entry("12345")
        assert result is True

    def test_delete_status_202(self, adapter):
        resp_html = MagicMock()
        resp_html.text = '<meta name="csrf-token" content="csrf123">'
        resp_html.raise_for_status = MagicMock()

        resp_del = MagicMock()
        resp_del.status_code = 202
        resp_del.raise_for_status = MagicMock()

        adapter.session.get.return_value = resp_html
        adapter.session.delete.return_value = resp_del

        result = adapter.delete_diary_entry("12345")
        assert result is True
