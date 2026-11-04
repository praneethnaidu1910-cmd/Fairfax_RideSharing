"""TASKS.md #18: CORS must be an explicit, env-driven allow-list -- never a
default wildcard -- so a real deployment names its own frontend origin(s)
and nothing else gets cross-origin access."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import parse_allowed_origins


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),
        ("https://example.com", ["https://example.com"]),
        (
            "https://example.com, https://www.example.com ,",
            ["https://example.com", "https://www.example.com"],
        ),
    ],
)
def test_parse_allowed_origins(raw, expected):
    assert parse_allowed_origins(raw) == expected


def test_no_cors_middleware_by_default(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    import app.main as main_module

    reloaded = importlib.reload(main_module)
    try:
        assert not any(
            "CORSMiddleware" in str(m.cls) for m in reloaded.app.user_middleware
        )
    finally:
        importlib.reload(main_module)


def test_cors_middleware_restricted_to_configured_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com")
    import app.main as main_module

    reloaded = importlib.reload(main_module)
    try:
        with TestClient(reloaded.app) as client:
            allowed = client.get("/healthz", headers={"Origin": "https://example.com"})
            denied = client.get("/healthz", headers={"Origin": "https://evil.example"})
        assert allowed.headers.get("access-control-allow-origin") == "https://example.com"
        assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        importlib.reload(main_module)
