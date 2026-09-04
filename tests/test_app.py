"""Phase 1 foundation tests: the app builds, serves the frontend, and reports health."""

from fastapi.testclient import TestClient

from claimiq import TRACK_ID, __version__
from claimiq.server import create_app

client = TestClient(create_app(), raise_server_exceptions=False)


def test_health_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["track"] == TRACK_ID == "PS02"
    assert body["version"] == __version__
    assert isinstance(body["gemini_configured"], bool)


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "ClaimIQ" in resp.text


def test_unknown_api_route_is_json_404():
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_port_default_is_8000():
    from claimiq.config import settings

    assert settings.port == 8000


def test_readme_first_line_is_track_id():
    from claimiq.config import BASE_DIR

    first_line = (BASE_DIR / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "TRACK_ID=PS02"
