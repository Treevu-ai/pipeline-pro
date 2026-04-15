"""
test_admin_api.py — Tests de integración contra la API live en Railway.

Requiere:
  PIPELINE_X_URL      = https://agentepyme-api-production.up.railway.app
  ADMIN_API_KEY       = <tu key>

Se saltan automáticamente si las variables no están configuradas.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL  = os.environ.get("PIPELINE_X_URL", "https://agentepyme-api-production.up.railway.app")
API_KEY   = os.environ.get("ADMIN_API_KEY", "")

needs_live = pytest.mark.skipif(
    not API_KEY,
    reason="ADMIN_API_KEY no configurada — tests live omitidos",
)


def _get(path: str, params: str = "") -> tuple[int, dict]:
    import urllib.request, json, urllib.parse
    url = f"{BASE_URL}{path}"
    if params:
        url += f"?{params}"
    req = urllib.request.Request(url)
    req.add_header("X-Admin-Key", API_KEY)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def _post(path: str, body: dict) -> tuple[int, dict]:
    import urllib.request, json
    data = json.dumps(body).encode()
    req  = urllib.request.Request(f"{BASE_URL}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Admin-Key", API_KEY)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def _delete(path: str, params: str = "") -> tuple[int, dict]:
    import urllib.request, json
    url = f"{BASE_URL}{path}"
    if params:
        url += f"?{params}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("X-Admin-Key", API_KEY)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health_ok():
    """El endpoint /health debe responder 200 con db:ok."""
    import urllib.request, json
    r = urllib.request.urlopen(f"{BASE_URL}/health", timeout=10)
    data = json.loads(r.read())
    assert r.status == 200
    assert data["status"] == "ok"
    assert data["checks"]["db"] == "ok"


# ─── Autenticación ────────────────────────────────────────────────────────────

@needs_live
def test_stats_sin_key_returns_403():
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}/admin/stats")
    try:
        urllib.request.urlopen(req, timeout=10)
        pytest.fail("Debería haber lanzado HTTPError 403")
    except urllib.error.HTTPError as e:
        assert e.code in (403, 503)


@needs_live
def test_stats_key_incorrecta_returns_403():
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}/admin/stats")
    req.add_header("X-Admin-Key", "clave-incorrecta")
    try:
        urllib.request.urlopen(req, timeout=10)
        pytest.fail("Debería haber lanzado HTTPError 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403


# ─── Stats ────────────────────────────────────────────────────────────────────

@needs_live
def test_stats_estructura():
    status, data = _get("/admin/stats", "days=7")
    assert status == 200
    assert "searches" in data
    assert "reports_delivered" in data
    assert "upgrade_clicks" in data
    assert "active_subscribers" in data
    assert "conversion" in data
    assert "top_searches" in data


@needs_live
def test_stats_conversion_formato():
    _, data = _get("/admin/stats", "days=30")
    conv = data["conversion"]
    for key in ("search_to_upgrade", "upgrade_to_paid", "search_to_paid"):
        val = conv[key]
        assert val == "—" or val.endswith("%"), f"{key}: {val!r}"


# ─── Subscribers CRUD ─────────────────────────────────────────────────────────

@needs_live
class TestSubscribersCRUD:

    TEST_PHONE = f"519{uuid.uuid4().hex[:8]}"

    def test_activate_subscriber(self):
        status, data = _post("/admin/subscribers/activate", {
            "phone": self.TEST_PHONE,
            "plan":  "starter",
            "days":  7,
            "notes": "pytest live test",
        })
        assert status == 200
        assert data["ok"] is True
        sub = data["subscriber"]
        assert sub["phone"]  == self.TEST_PHONE
        assert sub["plan"]   == "starter"
        assert sub["status"] == "active"
        assert "expires_at" in sub

    def test_get_subscriber(self):
        _post("/admin/subscribers/activate", {
            "phone": self.TEST_PHONE, "plan": "starter", "days": 7,
        })
        status, sub = _get(f"/admin/subscribers/{self.TEST_PHONE}")
        assert status == 200
        assert sub["phone"] == self.TEST_PHONE
        assert sub["status"] == "active"

    def test_get_nonexistent_subscriber(self):
        import urllib.request
        req = urllib.request.Request(f"{BASE_URL}/admin/subscribers/00000000000")
        req.add_header("X-Admin-Key", API_KEY)
        try:
            urllib.request.urlopen(req, timeout=10)
            pytest.fail("Debería haber lanzado 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_cancel_subscriber(self):
        _post("/admin/subscribers/activate", {
            "phone": self.TEST_PHONE, "plan": "starter", "days": 7,
        })
        status, data = _delete(
            f"/admin/subscribers/{self.TEST_PHONE}",
            "reason=pytest_cleanup",
        )
        assert status == 200
        assert data["ok"] is True
        assert data["status"] == "cancelled"

    def test_reactivate_cancelled_subscriber(self):
        _post("/admin/subscribers/activate", {
            "phone": self.TEST_PHONE, "plan": "starter", "days": 7,
        })
        _delete(f"/admin/subscribers/{self.TEST_PHONE}")
        status, data = _post("/admin/subscribers/activate", {
            "phone": self.TEST_PHONE, "plan": "pro", "days": 30,
        })
        assert status == 200
        assert data["subscriber"]["plan"] == "pro"
        assert data["subscriber"]["status"] == "active"
        # Cleanup final
        _delete(f"/admin/subscribers/{self.TEST_PHONE}")
