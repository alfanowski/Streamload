from __future__ import annotations

from unittest.mock import MagicMock

from streamload.utils.domain_resolver.validator import validate_domain


def _resp(status: int, text: str):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


VALID_HTML = (
    '<html><body><div id="app" data-page=\''
    '{"version":"abc","props":{"foo":1}}\'></div></body></html>'
)


def test_validate_returns_true_on_valid_inertia_page():
    http = MagicMock()
    http.get.return_value = _resp(200, VALID_HTML)
    assert validate_domain(http, "x.tld") is True


def test_validate_rejects_non_200():
    http = MagicMock()
    http.get.return_value = _resp(404, VALID_HTML)
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_missing_app_div():
    http = MagicMock()
    http.get.return_value = _resp(200, "<html>parking page</html>")
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_app_div_without_data_page():
    http = MagicMock()
    http.get.return_value = _resp(200, '<div id="app"></div>')
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_data_page_missing_version():
    http = MagicMock()
    html = '<div id="app" data-page=\'{"props":{}}\'></div>'
    http.get.return_value = _resp(200, html)
    assert validate_domain(http, "x.tld") is False


def test_validate_rejects_data_page_missing_props():
    http = MagicMock()
    html = '<div id="app" data-page=\'{"version":"v"}\'></div>'
    http.get.return_value = _resp(200, html)
    assert validate_domain(http, "x.tld") is False


def test_validate_returns_false_on_http_exception():
    http = MagicMock()
    http.get.side_effect = RuntimeError("boom")
    assert validate_domain(http, "x.tld") is False


def test_validate_uses_curl_and_lang_path():
    http = MagicMock()
    http.get.return_value = _resp(200, VALID_HTML)
    validate_domain(http, "x.tld", lang="it")
    http.get.assert_called_once()
    args, kwargs = http.get.call_args
    assert args[0] == "https://x.tld/it"
    assert kwargs.get("use_curl") is True


def test_validate_rejects_malformed_data_page_json():
    http = MagicMock()
    html = '<div id="app" data-page=\'not valid json\'></div>'
    http.get.return_value = _resp(200, html)
    assert validate_domain(http, "x.tld") is False
