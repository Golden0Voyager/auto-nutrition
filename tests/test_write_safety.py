"""写入安全：5xx 重试不双写、本地日志只记成功项。"""

import json
from unittest.mock import MagicMock

import requests


def _http_error(status: int) -> requests.exceptions.HTTPError:
    return requests.exceptions.HTTPError(
        f"{status} error", response=MagicMock(status_code=status)
    )


def _ok_response() -> MagicMock:
    return MagicMock(raise_for_status=MagicMock())


class TestPostDiaryEntryIdempotency:
    """MFP 可能「已写入但返回 5xx」，盲目重试会造成双计。"""

    def test_retries_when_entry_not_landed(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)
        adapter.session.post.side_effect = [_http_error(502), _ok_response()]

        assert adapter._post_diary_entry({"type": "food_entry"}, verify=lambda: False) is True
        assert adapter.session.post.call_count == 2

    def test_treats_landed_entry_as_success_without_retry(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)
        adapter.session.post.side_effect = [_http_error(500)]

        assert adapter._post_diary_entry({"type": "food_entry"}, verify=lambda: True) is True
        assert adapter.session.post.call_count == 1

    def test_gives_up_after_three_attempts(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)
        adapter.session.post.side_effect = [_http_error(500)] * 3

        try:
            adapter._post_diary_entry({"type": "food_entry"}, verify=lambda: False)
        except requests.exceptions.HTTPError:
            pass
        else:  # pragma: no cover - 失败路径必须抛错
            raise AssertionError("应当抛出 HTTPError")
        assert adapter.session.post.call_count == 3

    def test_does_not_retry_client_error(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)
        adapter.session.post.side_effect = [_http_error(400)]

        try:
            adapter._post_diary_entry({"type": "food_entry"}, verify=lambda: True)
        except requests.exceptions.HTTPError:
            pass
        else:  # pragma: no cover
            raise AssertionError("4xx 不应被吞掉")
        assert adapter.session.post.call_count == 1


class TestJournalOnlyLogsWrittenEntries:
    def test_failed_item_not_written_to_journal(self, adapter, monkeypatch):
        monkeypatch.setattr("mfp_adapter.time.sleep", lambda _s: None)
        adapter._create_custom_food = MagicMock(return_value={"id": "f1", "version": 1})
        adapter.get_food_entries_from_html = MagicMock(return_value=[])
        adapter._post_diary_entry = MagicMock(side_effect=[None, _http_error(400)])

        adapter.record_nutrition("2026-10-23", "breakfast", [{"name": "Oats"}, {"name": "Egg"}])

        with open(adapter.JOURNAL_FILE, encoding="utf-8") as f:
            journal = json.load(f)
        names = [item["name"] for entry in journal for item in entry["items"]]
        assert names == ["Oats"]


class TestDateWarnings:
    def test_future_date_warns(self, monkeypatch):
        import datetime as dt

        from mfp_adapter import _date_warnings

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 23, 9, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)
        assert any("未来" in w for w in _date_warnings("2026-10-25"))

    def test_long_past_date_warns(self, monkeypatch):
        import datetime as dt

        from mfp_adapter import _date_warnings

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 23, 9, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)
        assert any("补录" in w for w in _date_warnings("2026-10-01"))

    def test_today_has_no_warning(self, monkeypatch):
        import datetime as dt

        from mfp_adapter import _date_warnings

        class FrozenDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 23, 9, 0, 0)

        monkeypatch.setattr("mfp_adapter.datetime", FrozenDatetime)
        assert _date_warnings("2026-10-23") == []

    def test_malformed_date_warns(self):
        from mfp_adapter import _date_warnings

        assert any("格式" in w for w in _date_warnings("2026/10/23"))
