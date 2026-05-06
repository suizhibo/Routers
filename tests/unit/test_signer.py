import pytest
from agent_routers.services.signer import HmacSigner


def test_canonical_format():
    signer = HmacSigner(key="test-key")
    canonical = signer.canonical(
        request_id="req-123",
        timestamp_iso="2026-05-05T10:00:00Z",
        user_subject="user-abc",
        agent_id="weather-agent",
        status_code=200,
        latency_ms=42,
    )
    assert canonical == "req-123|2026-05-05T10:00:00Z|user-abc|weather-agent|200|42"


def test_sign_and_verify():
    signer = HmacSigner(key="test-key")
    canonical = signer.canonical("r1", "2026-05-05T10:00:00Z", "u1", "a1", 200, 10)
    sig = signer.sign(canonical)
    assert signer.verify(canonical, sig) is True
    assert signer.verify(canonical + "x", sig) is False


def test_different_keys_different_sigs():
    s1 = HmacSigner(key="key1")
    s2 = HmacSigner(key="key2")
    c = s1.canonical("r", "t", "u", "a", 200, 1)
    assert s1.sign(c) != s2.sign(c)
