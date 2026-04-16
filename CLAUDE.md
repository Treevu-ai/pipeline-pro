# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install
pip install -r requirements.txt
playwright install chromium --with-deps

# Lint
ruff check --select E9,F .

# Run all tests (mirrors CI)
pytest tests/ -x --ignore=tests/test_admin_api.py --tb=short

# Single test file
pytest tests/test_sdr.py -v

# Single test by name
pytest tests/test_sdr.py::TestNormalize::test_quita_acento_simple -v

# Start API locally
uvicorn api:app --reload --host 127.0.0.1 --port 8000

# CLI pipeline (not used in production)
python pipeline.py "Retail Lima" --limit 20 --report
```

## Architecture

**Stack:** Python 3.11 · FastAPI · PostgreSQL (psycopg2) · Anthropic Claude + Groq · Green API (WhatsApp) · python-telegram-bot · Railway.app

**Entry point:** `api.py` — FastAPI app (~2 900 LOC). All webhooks, REST endpoints, background loops, and startup logic live here.

**Startup sequence** (`lifespan` handler in `api.py`):
1. `logging_config.setup()` → stdout structured logging
2. `db.init()` → create PostgreSQL pool, DDL tables, recover stale jobs
3. `_start_bot_interno()` → Telegram admin bot (polling mode)
4. Background tasks: register Telegram + WhatsApp webhooks, start 6 monitoring loops

**Message flow — WhatsApp:**
```
User → Green API → POST /webhook/whatsapp (api.py)
     → wa_bot.parse_green_api_payload()
     → wa_bot.handle_message(phone, text)  [state machine, per-phone async lock]
     → wa_sender.send_text/buttons/document()  [Green API REST]
```

**Message flow — Telegram:**
```
User → Telegram → POST /webhook/telegram (api.py)
     → _handle_tg_callback() for button presses
     → telegram_bot._get_reply() for free text (Alex LLM sales bot)
     → Bot API response
```

**Pipeline execution (async):**
- User trigger → `asyncio.create_task(_deliver_and_notify_wa())` fire-and-forget
- Inside: `scrape_google_maps()` → `enrich_leads()` → `qualify_row()` → PDF → send
- Job state tracked in `pipeline_jobs` table (pending → running → completed/failed)

**LLM client** (`llm_client.py`): Groq primary (`llama-3.1-8b-instant`) → Claude fallback (`claude-3-5-haiku-20241022`). JSON responses parsed with loose extraction + UTF-8 double-encoding fix. 3 retries with exponential backoff.

**Database** (`db.py`): `ThreadedConnectionPool(1,8)`. Falls back to `.wa_sessions.json` + in-memory dicts when `DATABASE_URL` is absent. No migration framework — DDL runs at startup.

**Key tables:** `wa_sessions` · `pipeline_jobs` · `bot_states` · `subscribers` · `events`

**Scoring:** Pre-score (rule-based, 0–65 pts) + LLM adjustment (±35 pts) = final score 0–100.  
Stages: Calificado (70–100) · En seguimiento (50–69) · Prospección (25–49) · Descartado (0–24).

**Localization:** Spanish LatAm (Peru/Colombia/Mexico). Prompt files: `playbooks/PLAYBOOK_es.md`, `prompts/es_prompts.json`, `templates/messages_es.md`.

## Key Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Recommended | PostgreSQL — falls back to file/memory |
| `ANTHROPIC_API_KEY` | One of two | Claude LLM |
| `GROQ_API_KEY` | One of two | Groq LLM (primary) |
| `TELEGRAM_BOT_TOKEN` | Yes | External Telegram bot |
| `TELEGRAM_BOT_TOKEN_INTERNO` | Yes | Internal admin bot |
| `TELEGRAM_WEBHOOK_SECRET` | Yes | Webhook signature validation |
| `ADMIN_CHAT_ID` | Yes | Admin Telegram ID(s) |
| `GREEN_API_URL` | Yes | Green API base URL |
| `GREEN_API_INSTANCE` | Yes | WhatsApp instance ID |
| `GREEN_API_TOKEN` | Yes | Green API token |
| `GREEN_API_WEBHOOK_URL` | Yes | Public URL for WA webhooks |
| `API_PUBLIC_URL` / `BASE_URL` | Yes | Public API URL |
| `ADMIN_API_KEY` | Yes | HMAC secret for admin endpoints |
| `BANK_TRANSFER_INFO` | Optional | Bank details shown at upgrade |

## Deployment

Deployed on Railway.app. Build via nixpacks (`railway.toml`). Start command:
```
uvicorn api:app --host 0.0.0.0 --port $PORT
```
No Docker. CI runs lint + tests via `.github/workflows/deploy.yml`.
