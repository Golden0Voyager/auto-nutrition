from unittest.mock import MagicMock

import requests
from mfp_adapter import is_server_error


def test_not_http_error():
    assert is_server_error(ValueError("boom")) is False


def test_http_error_400():
    exc = requests.exceptions.HTTPError(response=MagicMock(status_code=400))
    assert is_server_error(exc) is False


def test_http_error_401():
    resp = MagicMock()
    resp.status_code = 401
    exc = requests.exceptions.HTTPError(response=resp)
    assert is_server_error(exc) is False


def test_http_error_500():
    resp = MagicMock()
    resp.status_code = 500
    exc = requests.exceptions.HTTPError(response=resp)
    assert is_server_error(exc) is True


def test_http_error_503():
    resp = MagicMock()
    resp.status_code = 503
    exc = requests.exceptions.HTTPError(response=resp)
    assert is_server_error(exc) is True


def test_http_error_no_response():
    exc = requests.exceptions.HTTPError()
    assert is_server_error(exc) is False


def test_connection_error():
    exc = requests.exceptions.ConnectionError()
    assert is_server_error(exc) is False


def test_timeout_error():
    exc = requests.exceptions.Timeout()
    assert is_server_error(exc) is False
