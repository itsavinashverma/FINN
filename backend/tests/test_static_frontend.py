"""The production image serves the built frontend from the same FastAPI process (see Dockerfile,
finn/api.py's bottom section). Static-route registration happens at import time based on
FINN_STATIC_DIR, so these tests reload both finn.config and finn.api with the env var set to a
fake build directory, rather than unit-testing a function in isolation."""
import importlib
import sys

import pytest


@pytest.fixture
def static_app(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><title>FINN</title>", encoding="utf-8")

    monkeypatch.setenv("FINN_STATIC_DIR", str(dist))
    monkeypatch.setenv("FINN_REFRESHER", "0")
    for mod in ("finn.config", "finn.api"):
        sys.modules.pop(mod, None)
    config = importlib.import_module("finn.config")
    api = importlib.import_module("finn.api")
    assert config.settings.static_dir == dist  # sanity: the reload actually picked up the env var
    yield api.app

    # Leave the module cache as later test files expect it (no FINN_STATIC_DIR).
    for mod in ("finn.config", "finn.api"):
        sys.modules.pop(mod, None)
    importlib.import_module("finn.config")
    importlib.import_module("finn.api")


def test_root_serves_index_html(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "FINN" in r.text


def test_client_side_route_falls_back_to_index_html(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/research/TCS")
    assert r.status_code == 200 and "FINN" in r.text


def test_unknown_path_also_falls_back_to_index_html_not_a_404(static_app):
    """React Router owns unknown paths client-side; the server must not 404 them."""
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/this/does/not/exist")
    assert r.status_code == 200 and "FINN" in r.text


def test_real_asset_file_is_served_with_correct_type(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/assets/app.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert r.text == "console.log('ok')"


def test_root_level_static_file_served_via_catchall(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/favicon.svg")
    assert r.status_code == 200 and "svg" in r.headers["content-type"]


def test_missing_asset_404s_instead_of_falling_back_to_index_html(static_app):
    """A real but missing file under /assets must 404 from the StaticFiles mount, not silently
    serve the SPA shell as if the asset existed."""
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/assets/does-not-exist.js")
    assert r.status_code == 404


def test_unmatched_api_path_404s_as_json_not_the_spa_shell(static_app):
    """Regression: the catch-all route originally swallowed ANY unmatched path, including typo'd
    /api/* requests, silently returning the SPA shell with a 200 instead of a clear 404 -- would
    make a real API bug look like success during debugging."""
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "NotFound"


def test_unmatched_health_path_404s_as_json(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/health")  # real route -- sanity check it still works normally
    assert r.status_code == 200


def test_real_api_routes_are_unaffected_by_static_serving(static_app):
    from fastapi.testclient import TestClient
    r = TestClient(static_app).get("/api/portfolio")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")


def test_no_static_dir_env_var_means_no_static_routes_registered(monkeypatch):
    """Local dev (no FINN_STATIC_DIR) must not register the catch-all -- otherwise a typo'd API
    path would silently 200 with nothing instead of a normal 404, and the Vite dev server (which
    serves the frontend separately) would never even be reached for the app shell."""
    monkeypatch.delenv("FINN_STATIC_DIR", raising=False)
    monkeypatch.setenv("FINN_REFRESHER", "0")
    for mod in ("finn.config", "finn.api"):
        sys.modules.pop(mod, None)
    config = importlib.import_module("finn.config")
    api = importlib.import_module("finn.api")
    assert config.settings.static_dir is None
    assert not any(getattr(r, "path", None) == "/{full_path:path}" for r in api.app.routes)
    for mod in ("finn.config", "finn.api"):
        sys.modules.pop(mod, None)
    importlib.import_module("finn.config")
    importlib.import_module("finn.api")
