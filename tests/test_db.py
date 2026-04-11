"""
test_db.py — Tests de la capa de persistencia db.py.

Corre en modo fallback (sin DATABASE_URL) usando stores en memoria/archivo.
Los tests de PostgreSQL real se saltan automáticamente si no hay DB.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db


# ─── Helpers ──────────────────────────────────────────────────────────────────

def fresh_phone() -> str:
    return f"519{uuid.uuid4().hex[:8]}"


# ─── Sesiones WA (fallback archivo) ───────────────────────────────────────────

class TestSessionsFallback:
    """Prueba sesiones usando el fallback de archivo (sin Postgres)."""

    def test_get_session_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_SESSIONS_FILE", tmp_path / ".wa_sessions.json")
        phone = fresh_phone()
        session = db.get_session(phone)
        assert session == {"state": "idle"}

    def test_set_and_get_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_SESSIONS_FILE", tmp_path / ".wa_sessions.json")
        phone = fresh_phone()
        db.set_session(phone, {"state": "menu_shown", "foo": "bar"})
        result = db.get_session(phone)
        assert result["state"] == "menu_shown"
        assert result["foo"] == "bar"

    def test_overwrite_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_SESSIONS_FILE", tmp_path / ".wa_sessions.json")
        phone = fresh_phone()
        db.set_session(phone, {"state": "idle"})
        db.set_session(phone, {"state": "done"})
        assert db.get_session(phone)["state"] == "done"


# ─── Jobs en memoria ──────────────────────────────────────────────────────────

class TestJobsFallback:

    def test_new_job_returns_id(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_mem_jobs", {})
        job_id = db.new_job("pipeline", {"query": "test"})
        assert isinstance(job_id, str) and len(job_id) == 36  # UUID

    def test_get_job_pending(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_mem_jobs", {})
        job_id = db.new_job("pipeline", {"query": "test"})
        job = db.get_job(job_id)
        assert job["status"] == "pending"
        assert job["kind"] == "pipeline"

    def test_update_job_done(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_mem_jobs", {})
        job_id = db.new_job("pipeline", {})
        db.update_job(job_id, "running")
        db.update_job(job_id, "done", result={"leads": 5})
        job = db.get_job(job_id)
        assert job["status"] == "done"
        assert job["result"]["leads"] == 5
        assert job["finished_at"] is not None

    def test_update_job_failed(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_mem_jobs", {})
        job_id = db.new_job("pipeline", {})
        db.update_job(job_id, "failed", error="timeout")
        job = db.get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "timeout"

    def test_get_nonexistent_job(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_mem_jobs", {})
        assert db.get_job("nonexistent-id") is None


# ─── Bot states en memoria ────────────────────────────────────────────────────

class TestBotStatesFallback:

    def test_get_empty_state(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_bot_states_mem", {})
        assert db.get_bot_state(12345) == {}

    def test_set_and_get_bot_state(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_bot_states_mem", {})
        db.set_bot_state(12345, {"step": "asking_query"})
        assert db.get_bot_state(12345)["step"] == "asking_query"

    def test_delete_bot_state(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        monkeypatch.setattr(db, "_bot_states_mem", {})
        db.set_bot_state(12345, {"step": "asking_query"})
        db.delete_bot_state(12345)
        assert db.get_bot_state(12345) == {}


# ─── Subscribers (solo con DB real) ───────────────────────────────────────────

@pytest.mark.skipif(not db._USE_DB, reason="Requiere PostgreSQL")
class TestSubscribersDB:

    def test_is_active_subscriber_unknown(self):
        assert db.is_active_subscriber("51000000000") is False

    def test_upsert_and_is_active(self):
        phone = fresh_phone()
        result = db.upsert_subscriber(phone, plan="starter", days=30, notes="test")
        assert result["status"] == "active"
        assert db.is_active_subscriber(phone) is True
        db.cancel_subscriber(phone, "test cleanup")

    def test_cancel_subscriber(self):
        phone = fresh_phone()
        db.upsert_subscriber(phone, plan="starter", days=30)
        db.cancel_subscriber(phone, "test")
        assert db.is_active_subscriber(phone) is False

    def test_get_subscriber_none(self):
        assert db.get_subscriber("51000000000") is None

    def test_get_subscriber_fields(self):
        phone = fresh_phone()
        db.upsert_subscriber(phone, plan="pro", days=7, notes="nota test")
        sub = db.get_subscriber(phone)
        assert sub["plan"] == "pro"
        assert sub["status"] == "active"
        assert "activated_at" in sub
        assert "expires_at" in sub
        db.cancel_subscriber(phone)


# ─── Events (solo con DB real) ────────────────────────────────────────────────

@pytest.mark.skipif(not db._USE_DB, reason="Requiere PostgreSQL")
class TestEventsDB:

    def test_log_event_no_crash(self):
        phone = fresh_phone()
        # fire-and-forget — no debe lanzar
        db.log_event(phone, db.EventType.WA_SEARCH, {"target": "test"})
        db.log_event(phone, db.EventType.WA_REPORT_DELIVERED, {"leads": 5})
        db.log_event(phone, db.EventType.WA_UPGRADE_CLICK)

    def test_get_stats_returns_dict(self):
        stats = db.get_stats(7)
        assert isinstance(stats, dict)
        assert "searches" in stats
        assert "reports_delivered" in stats
        assert "upgrade_clicks" in stats
        assert "active_subscribers" in stats
        assert "conversion" in stats
        assert "top_searches" in stats

    def test_get_stats_conversion_pct_format(self):
        stats = db.get_stats(7)
        conv = stats["conversion"]
        for key in ("search_to_upgrade", "upgrade_to_paid", "search_to_paid"):
            val = conv[key]
            assert val == "—" or val.endswith("%"), f"{key}: {val!r}"

    def test_get_followup_candidates_returns_list(self):
        result = db.get_followup_candidates()
        assert isinstance(result, list)


# ─── EventType constants ──────────────────────────────────────────────────────

class TestEventTypeConstants:

    def test_all_event_types_defined(self):
        assert db.EventType.WA_SEARCH            == "wa_search"
        assert db.EventType.WA_REPORT_DELIVERED  == "wa_report_delivered"
        assert db.EventType.WA_UPGRADE_CLICK     == "wa_upgrade_click"
        assert db.EventType.WA_FEEDBACK          == "wa_feedback"
        assert db.EventType.WA_FOLLOWUP_SENT     == "wa_followup_sent"
        assert db.EventType.SUBSCRIBER_ACTIVATED == "subscriber_activated"
        assert db.EventType.SUBSCRIBER_CANCELLED == "subscriber_cancelled"


# ─── log_event fallback (sin DB) ──────────────────────────────────────────────

class TestLogEventFallback:

    def test_log_event_noop_without_db(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        # No debe lanzar excepción
        db.log_event("51999", db.EventType.WA_SEARCH, {"target": "test"})

    def test_get_stats_empty_without_db(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        assert db.get_stats(7) == {}

    def test_is_active_subscriber_false_without_db(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        assert db.is_active_subscriber("51999") is False

    def test_get_followup_candidates_empty_without_db(self, monkeypatch):
        monkeypatch.setattr(db, "_USE_DB", False)
        assert db.get_followup_candidates() == []
