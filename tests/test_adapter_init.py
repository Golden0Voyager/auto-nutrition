import json
import os
from unittest.mock import MagicMock, patch

import pytest

from mfp_adapter import MFPAdapter, SessionExpiredError


@pytest.fixture
def adapter_without_network(tmp_path, monkeypatch):
    """Create MFPAdapter without real network calls."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(MFPAdapter, "JOURNAL_FILE", str(tmp_path / "journal.json"))
    monkeypatch.setattr(MFPAdapter, "TOKEN_URL", "http://fake/token")

    with patch("mfp_adapter.requests.Session") as mock_sess_cls:
        mock_session = MagicMock()
        mock_session.cookies = {"mfp-session": "fake"}
        mock_session.headers = {}
        mock_sess_cls.return_value = mock_session

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.BASE_URL = "https://api.myfitnesspal.com/v2"
        adapter.JOURNAL_FILE = str(tmp_path / "journal.json")
        adapter._JOURNAL_MAX_ENTRIES = 200
        adapter.usda = MagicMock()
        adapter.session = mock_session
        adapter.access_token = None
        adapter.user_id = None
        adapter.token_expires_at = 0
        adapter._config = None
        return adapter


class TestLoadCookies:
    def test_load_cookies_success(self, tmp_path, monkeypatch):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text(json.dumps([
            {"name": "session", "value": "abc", "domain": ".myfitnesspal.com", "path": "/"}
        ]), encoding="utf-8")

        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.session = MagicMock()
        adapter.session.cookies = MagicMock()

        adapter._load_cookies()
        assert adapter.session.cookies.update.called

    def test_load_cookies_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(tmp_path / "nonexistent.json"))

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.session = MagicMock()
        adapter.session.cookies = {}

        adapter._load_cookies()  # Should not raise

    def test_load_cookies_invalid_json(self, tmp_path, monkeypatch):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.session = MagicMock()
        adapter.session.cookies = {}

        adapter._load_cookies()  # Should not raise

    def test_load_cookies_empty_list(self, tmp_path, monkeypatch):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.session = MagicMock()
        adapter.session.cookies = {}

        adapter._load_cookies()

    def test_load_cookies_multiple_cookies(self, tmp_path, monkeypatch):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text(json.dumps([
            {"name": "c1", "value": "v1", "domain": ".myfitnesspal.com", "path": "/"},
            {"name": "c2", "value": "v2", "domain": ".myfitnesspal.com", "path": "/"},
        ]), encoding="utf-8")
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))

        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.session = MagicMock()
        adapter.session.cookies = {}

        adapter._load_cookies()


class TestFetchAccessToken:
    def test_fetch_token_success(self, adapter_without_network):
        adapter = adapter_without_network
        resp = MagicMock()
        resp.json.return_value = {"access_token": "tok123", "user_id": 99, "expires_in": 7200}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        adapter._fetch_access_token()
        assert adapter.access_token == "tok123"
        assert adapter.user_id == 99
        assert adapter.token_expires_at > 0
        assert "Authorization" in adapter.session.headers

    def test_fetch_token_no_cookies(self, adapter_without_network):
        adapter = adapter_without_network
        adapter.session.cookies = {}

        adapter._fetch_access_token()
        assert adapter.access_token is None

    def test_fetch_token_401_clears_token(self, adapter_without_network):
        import requests as req
        adapter = adapter_without_network
        adapter.session.cookies = {"mfp-session": "expired"}
        resp = MagicMock()
        resp.status_code = 401
        exc = req.exceptions.HTTPError(response=resp)
        adapter.session.get.side_effect = exc

        adapter._fetch_access_token()
        assert adapter.access_token is None

    def test_fetch_token_network_error(self, adapter_without_network):
        adapter = adapter_without_network
        adapter.session.cookies = {"mfp-session": "x"}
        adapter.session.get.side_effect = Exception("network timeout")

        adapter._fetch_access_token()
        assert adapter.access_token is None


class TestEnsureTokenValid:
    def test_valid_token_passes(self, adapter_without_network):
        adapter = adapter_without_network
        adapter.access_token = "valid"
        adapter.token_expires_at = 999999999999
        adapter._ensure_token_valid()  # Should not raise

    def test_expired_token_refreshes(self, adapter_without_network):
        adapter = adapter_without_network
        adapter.access_token = None
        adapter.token_expires_at = 0

        resp = MagicMock()
        resp.json.return_value = {"access_token": "newtok", "user_id": 1}
        resp.raise_for_status = MagicMock()
        adapter.session.get.return_value = resp

        adapter._ensure_token_valid()
        assert adapter.access_token == "newtok"

    def test_no_token_after_refresh_raises(self, adapter_without_network):
        adapter = adapter_without_network
        adapter.access_token = None
        adapter.token_expires_at = 0
        adapter.session.get.side_effect = Exception("fail")

        with pytest.raises(SessionExpiredError):
            adapter._ensure_token_valid()


class TestLoadConfig:
    def test_load_config_success(self, adapter_without_network, tmp_path):
        import yaml
        adapter = adapter_without_network
        config_path = tmp_path / "supplements_config.yaml"
        config_path.write_text(yaml.dump({"supplements": {"test": {"name": "Test"}}}), encoding="utf-8")
        adapter._config = None
        adapter._config_mtime = 0

        with patch("os.path.dirname", return_value=str(tmp_path)):
            config = adapter._load_config()
            assert "supplements" in config

    def test_load_config_missing_file(self, adapter_without_network, tmp_path):
        adapter = adapter_without_network
        fake_dir = str(tmp_path / "nonexistent")
        os.makedirs(fake_dir, exist_ok=True)
        adapter._config = None
        adapter._config_mtime = 0

        with patch("os.path.dirname", return_value=fake_dir), patch("os.path.exists", return_value=False):
            config = adapter._load_config()
            assert config == {}

    def test_load_config_cached(self, adapter_without_network):
        adapter = adapter_without_network
        adapter._config = {"cached": True}
        adapter._config_mtime = 12345

        with patch("os.path.getmtime", return_value=12345), patch("os.path.exists", return_value=True):
            config = adapter._load_config()
            assert config == {"cached": True}

    def test_load_config_hot_reload(self, adapter_without_network, tmp_path):
        import yaml
        adapter = adapter_without_network
        config_path = tmp_path / "supplements_config.yaml"
        config_path.write_text(yaml.dump({"new": True}), encoding="utf-8")
        adapter._config = {"old": True}
        adapter._config_mtime = 100

        with patch("os.path.dirname", return_value=str(tmp_path)):
            config = adapter._load_config()
            assert config == {"new": True}

    def test_load_config_parse_error(self, adapter_without_network, tmp_path):
        adapter = adapter_without_network
        config_path = tmp_path / "supplements_config.yaml"
        config_path.write_text(": invalid yaml: [", encoding="utf-8")
        adapter._config = None
        adapter._config_mtime = 0

        with patch("os.path.dirname", return_value=str(tmp_path)):
            config = adapter._load_config()
            assert config == {}


class TestMFPAdapterInit:
    def test_init_with_cookies(self, tmp_path, monkeypatch):
        cookies_file = tmp_path / "cookies.json"
        cookies_file.write_text(json.dumps([
            {"name": "mfp-session", "value": "abc", "domain": ".myfitnesspal.com", "path": "/"}
        ]), encoding="utf-8")

        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(cookies_file))
        monkeypatch.setattr(MFPAdapter, "JOURNAL_FILE", str(tmp_path / "journal.json"))

        with patch("mfp_adapter.requests.Session") as mock_sess_cls:
            mock_session = MagicMock()
            mock_session.cookies = {"mfp-session": "abc"}
            mock_session.headers = {}
            mock_sess_cls.return_value = mock_session

            resp = MagicMock()
            resp.json.return_value = {"access_token": "tok", "user_id": 1, "expires_in": 3600}
            resp.raise_for_status = MagicMock()
            mock_session.get.return_value = resp

            adapter = MFPAdapter()
            assert adapter.access_token == "tok"

    def test_init_without_cookies(self, tmp_path, monkeypatch):
        monkeypatch.setattr(MFPAdapter, "COOKIES_FILE", str(tmp_path / "nonexistent.json"))
        monkeypatch.setattr(MFPAdapter, "JOURNAL_FILE", str(tmp_path / "journal.json"))

        with patch("mfp_adapter.requests.Session") as mock_sess_cls:
            mock_session = MagicMock()
            mock_session.cookies = {}
            mock_session.headers = {}
            mock_sess_cls.return_value = mock_session

            adapter = MFPAdapter()
            assert adapter.access_token is None
