"""
test_wa_bot.py — Tests del bot de WhatsApp: state machine, intents, tier enforcement.

Corre sin conexión real a WhatsApp ni a DB (todo mockeado).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import wa_bot


# ─── Fixtures ─────────────────────────────────────────────────────────────────

PHONE = "51999000001"

@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    """
    Reemplaza db con un store en memoria.
    wa_bot importa `db` lazily dentro de las funciones, así que
    parchamos el módulo db directamente.
    """
    import db as _db
    _store: dict[str, dict] = {}

    def fake_get(phone):
        return dict(_store.get(phone, {"state": "idle"}))

    def fake_set(phone, data):
        import time
        data["_ts"] = time.time()
        _store[phone] = data

    monkeypatch.setattr(_db, "get_session", fake_get)
    monkeypatch.setattr(_db, "set_session", fake_set)
    monkeypatch.setattr(_db, "log_event", lambda *a, **kw: None)
    return _store


@pytest.fixture(autouse=True)
def mock_notify(monkeypatch):
    """Silencia notificaciones a Telegram."""
    monkeypatch.setattr("wa_bot._notify_ceo_upgrade", lambda *a, **kw: None)
    monkeypatch.setattr("wa_bot._notify_feedback",    lambda *a, **kw: None)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def handle(phone: str, text: str) -> list[dict]:
    return wa_bot.handle_message(phone, text)

def types(msgs: list[dict]) -> list[str]:
    return [m.get("type") for m in msgs]

def first_text(msgs: list[dict]) -> str:
    for m in msgs:
        if m.get("type") == "text":
            return m["text"]
        if m.get("type") == "buttons":
            return m["body"]
    return ""


# ─── State machine ────────────────────────────────────────────────────────────

class TestStateMachine:

    def test_idle_shows_menu(self):
        msgs = handle(PHONE, "hola")
        assert any(m.get("type") in ("text", "buttons") and "Pipeline_X" in m.get("text", "") for m in msgs)

    def test_saludo_siempre_resetea(self, mock_db):
        mock_db[PHONE] = {"state": "done", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "hola")
        assert any(m.get("type") in ("text", "buttons") and "Pipeline_X" in m.get("text", "") for m in msgs)

    def test_demo_intent_pide_target(self, mock_db):
        mock_db[PHONE] = {"state": "menu_shown", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "demo")
        assert any("rubro" in m.get("text", "").lower() or
                   "ciudad" in m.get("text", "").lower()
                   for m in msgs)

    def test_target_muy_corto_rechazado(self, mock_db):
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "abc")
        assert not any(m.get("type") == "pipeline_request" for m in msgs)

    def test_target_sin_ciudad_rechazado(self, mock_db):
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "ferreterias")
        assert not any(m.get("type") == "pipeline_request" for m in msgs)

    def test_target_valido_lanza_pipeline(self, mock_db):
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert any(m.get("type") == "pipeline_request" for m in msgs)
        pr = next(m for m in msgs if m.get("type") == "pipeline_request")
        assert pr["target"] == "Ferreterías en Lima"

    def test_running_pipeline_bloquea(self, mock_db):
        mock_db[PHONE] = {"state": "running_pipeline", "target": "test",
                          "_ts": __import__("time").time()}
        msgs = handle(PHONE, "cualquier cosa")
        assert all(m.get("type") == "text" for m in msgs)
        assert "proceso" in first_text(msgs).lower() or "revisando" in first_text(msgs).lower()

    def test_done_texto_libre_como_target(self, mock_db):
        mock_db[PHONE] = {"state": "done", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Clínicas en Trujillo")
        assert any(m.get("type") == "pipeline_request" for m in msgs)

    def test_upgrade_prompted_gracias(self, mock_db):
        # Con keyword de pago → confirma
        mock_db[PHONE] = {"state": "upgrade_prompted", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "listo, ya pagué")
        texto = first_text(msgs).lower()
        assert "gracias" in texto or "recibido" in texto

    def test_upgrade_prompted_texto_irrelevante(self, mock_db):
        # Sin keyword de pago → recuerda instrucciones, NO notifica CEO
        mock_db[PHONE] = {"state": "upgrade_prompted", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "cuándo me activan")
        texto = first_text(msgs).lower()
        assert "listo" in texto or "pago" in texto or "comprobante" in texto

    def test_feedback_good_logueado(self, mock_db):
        mock_db[PHONE] = {"state": "feedback_prompted", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "feedback_good")
        texto = first_text(msgs).lower()
        assert "útil" in texto or "bueno" in texto or "qué bueno" in texto

    def test_feedback_bad_agradece(self, mock_db):
        mock_db[PHONE] = {"state": "feedback_prompted", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "feedback_bad")
        assert any(m.get("type") == "text" for m in msgs)


# ─── Detección de intents ──────────────────────────────────────────────────────

class TestIntentDetection:

    @pytest.mark.parametrize("text,expected", [
        ("hola",         "saludo"),
        ("buenas tardes","saludo"),
        ("demo",         "demo"),
        ("quiero probar","demo"),
        ("precios",      "precios"),
        ("cuánto cuesta","precios"),
        ("upgrade",          "upgrade"),
        ("quiero el starter","upgrade"),
        ("garantia",     "garantia"),
        ("contacto",     "contacto"),
    ])
    def test_detect_intent(self, text, expected):
        assert wa_bot._detect_intent(text) == expected

    def test_unknown_returns_none(self):
        # Sin dígitos ni keywords conocidas
        assert wa_bot._detect_intent("qwerty foobar") is None

    def test_feedback_intents(self):
        assert wa_bot._detect_intent("feedback_good") == "feedback_good"
        assert wa_bot._detect_intent("feedback_ok")   == "feedback_ok"
        assert wa_bot._detect_intent("feedback_bad")  == "feedback_bad"


# ─── Constructores de respuesta ───────────────────────────────────────────────

class TestResponseBuilders:

    def test_menu_has_3_options(self):
        msgs = wa_bot._r_menu()
        assert msgs[0]["type"] == "buttons"
        assert len(msgs[0]["buttons"]) == 3

    def test_feedback_has_3_options(self):
        msgs = wa_bot._r_feedback()
        assert msgs[0]["type"] == "text"
        text = msgs[0]["text"]
        assert "1." in text and "2." in text and "3." in text

    def test_upgrade_env_con_bank_info(self, monkeypatch):
        monkeypatch.setenv("BANK_TRANSFER_INFO", "BCP · 1234567890")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN_INTERNO", "")
        msgs = wa_bot._r_upgrade(PHONE)
        assert any("BCP" in m.get("text", "") for m in msgs)

    def test_upgrade_env_sin_bank_info(self, monkeypatch):
        monkeypatch.delenv("BANK_TRANSFER_INFO", raising=False)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN_INTERNO", "")
        msgs = wa_bot._r_upgrade(PHONE)
        assert any("contacto@pipelinex" in m.get("text", "") for m in msgs)

    def test_post_pdf_options_tiene_opciones(self, mock_db):
        msgs = wa_bot._r_post_pdf_options("Ricardo")
        text = msgs[0]["text"]
        assert "Ricardo" in text
        assert any(opt in text for opt in ["A.", "B.", "C.", "D."])


# ─── Rate limiting ────────────────────────────────────────────────────────────

def _mock_sub(plan: str | None, active: bool = True):
    """Helper: devuelve un dict de suscriptor falso o None."""
    if plan is None:
        return None
    from datetime import datetime, timezone, timedelta
    return {
        "phone": PHONE, "plan": plan, "status": "active" if active else "cancelled",
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "notes": "",
    }


class TestRateLimit:

    def test_free_first_search_passes(self, mock_db, monkeypatch):
        """Primera búsqueda free debe lanzar pipeline_request."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: None)
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 0)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 0)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert any(m.get("type") == "pipeline_request" for m in msgs)

    def test_free_second_search_blocked(self, mock_db, monkeypatch):
        """Segunda búsqueda del día para free debe bloquear."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: None)
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 1)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 0)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert not any(m.get("type") == "pipeline_request" for m in msgs)
        assert any("hoy" in m.get("text", "").lower() or "hoy" in m.get("body", "").lower()
                   for m in msgs)

    def test_starter_ignores_daily_limit(self, mock_db, monkeypatch):
        """Suscriptor Starter: sin límite diario ni mensual."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: _mock_sub("starter"))
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 99)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 99)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert any(m.get("type") == "pipeline_request" for m in msgs)

    def test_trial_ignores_limits(self, mock_db, monkeypatch):
        """Trial: sin límite durante los 3 días."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: _mock_sub("trial"))
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 5)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 5)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert any(m.get("type") == "pipeline_request" for m in msgs)

    def test_free_daily_limit(self, mock_db, monkeypatch):
        """Free: bloqueado al llegar al límite diario de 1 búsqueda."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: None)
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 1)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 0)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert not any(m.get("type") == "pipeline_request" for m in msgs)

    def test_basico_under_monthly_limit_passes(self, mock_db, monkeypatch):
        """Básico: dentro del límite mensual → pipeline_request OK."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: _mock_sub("basico"))
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 0)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 5)
        mock_db[PHONE] = {"state": "collecting_target", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Ferreterías en Lima")
        assert any(m.get("type") == "pipeline_request" for m in msgs)

    def test_done_state_also_rate_limited(self, mock_db, monkeypatch):
        """Rate limit aplica también cuando mandan target desde estado 'done'."""
        import db as _db
        monkeypatch.setattr(_db, "get_subscriber", lambda phone: None)
        monkeypatch.setattr(_db, "get_daily_search_count", lambda phone: 1)
        monkeypatch.setattr(_db, "get_monthly_search_count", lambda phone: 0)
        mock_db[PHONE] = {"state": "done", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "Clínicas en Lima")
        assert not any(m.get("type") == "pipeline_request" for m in msgs)


class TestTrial:

    def test_first_upgrade_activates_trial(self, mock_db, monkeypatch):
        """Primer click de upgrade activa trial automático."""
        import db as _db
        activated = []
        monkeypatch.setattr(_db, "has_trialed", lambda phone: False)
        monkeypatch.setattr(_db, "is_active_subscriber", lambda phone: False)
        monkeypatch.setattr(_db, "upsert_subscriber",
                            lambda phone, plan, days, notes: activated.append(plan) or {})
        monkeypatch.setattr(_db, "log_event", lambda *a, **kw: None)
        import wa_bot as _wb
        monkeypatch.setattr(_wb, "_notify_ceo_upgrade", lambda phone: None)
        mock_db[PHONE] = {"state": "menu_shown", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "upgrade")
        assert "trial" in activated
        assert any("trial" in m.get("text", "").lower() for m in msgs)

    def test_second_upgrade_goes_to_payment(self, mock_db, monkeypatch):
        """Quien ya trialó recibe flujo de pago normal."""
        import db as _db
        monkeypatch.setattr(_db, "has_trialed", lambda phone: True)
        monkeypatch.setattr(_db, "is_active_subscriber", lambda phone: False)
        monkeypatch.setattr(_db, "log_event", lambda *a, **kw: None)
        import wa_bot as _wb
        monkeypatch.setattr(_wb, "_notify_ceo_upgrade", lambda phone: None)
        mock_db[PHONE] = {"state": "menu_shown", "_ts": __import__("time").time()}
        msgs = handle(PHONE, "upgrade")
        # No activa trial, va al flujo de pago
        assert not any("trial activado" in m.get("text", "").lower() for m in msgs)


# ─── Session TTL ──────────────────────────────────────────────────────────────

class TestSessionTTL:

    def test_pipeline_atascado_resetea(self, mock_db):
        import time
        mock_db[PHONE] = {
            "state": "running_pipeline", "target": "test",
            "_ts": time.time() - 400,   # 400s > 5min TTL
        }
        session = wa_bot._get_session(PHONE)
        assert session["state"] == "idle"

    def test_sesion_expirada_resetea(self, mock_db):
        import time
        mock_db[PHONE] = {
            "state": "menu_shown",
            "_ts": time.time() - 2000,  # 2000s > 30min TTL
        }
        session = wa_bot._get_session(PHONE)
        assert session["state"] == "idle"
