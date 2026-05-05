from __future__ import annotations

import pytest

from agent_routers.services.forwarder import _extract_value, _build_url


def test_extract_value_dot_path():
    data = {"input": "hello", "context": {"session_id": "abc"}, "options": {"temp": 0.7}}
    assert _extract_value(data, "input") == "hello"
    assert _extract_value(data, "context.session_id") == "abc"
    assert _extract_value(data, "options.temp") == 0.7


def test_extract_value_dollar_sign():
    data = {"input": "hello"}
    assert _extract_value(data, "$") == data


def test_extract_value_missing_path():
    data = {"input": "hello"}
    assert _extract_value(data, "context.session_id") is None
    assert _extract_value(data, "foo.bar.baz") is None


def test_build_url_no_query():
    url = _build_url("/api/forecast/{city}", {"city": "NYC"}, {})
    assert url == "/api/forecast/NYC"


def test_build_url_with_query():
    url = _build_url("/api/forecast/{city}", {"city": "NYC"}, {"days": "7"})
    assert url == "/api/forecast/NYC?days=7"


def test_build_url_missing_param_raises():
    with pytest.raises(KeyError):
        _build_url("/api/forecast/{city}", {}, {})
