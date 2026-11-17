# ResolveIQ — AI-assisted IT service desk

[![CI](https://github.com/Shiranul24/ResolveIQ/actions/workflows/ci.yml/badge.svg)](https://github.com/Shiranul24/ResolveIQ/actions/workflows/ci.yml)

A service-desk backend of the kind large IT-services teams run for their clients: employees raise
tickets, the system **routes and prioritises them automatically**, agents work them through a
controlled workflow, and managers watch SLA health on a dashboard.

**Stack:** Python · FastAPI · SQLAlchemy 2 · PostgreSQL · scikit-learn · JWT · Docker Compose · GitHub Actions · Pytest

## What it does

| Area | Details |
|---|---|
| **Auth & RBAC** | bcrypt-hashed passwords, short-lived JWT access tokens, three roles (`employee`, `agent`, `admin`). Roles are checked against the database on every request, so a demotion applies immediately. |
| **Auto-triage** | A TF-IDF + Logistic Regression classifier routes each ticket to one of 6 queues (network, hardware, software, access, database, security). Predictions below 45% confidence go to a `general` queue and are **flagged for human review** instead of being mis-routed. |
| **Priority & SLA** | Transparent keyword rules set priority (an outage beats a how-to question; security is never below *high*). Each priority has a resolution deadline: critical 4h · high 8h · medium 24h · low 72h. |
| **Workflow** | A validated state machine (`open → in_progress → resolved → closed`, with reopen). Requesters can only withdraw, accept a fix, or reopen their own tickets. |
| **Audit trail** | Every status / priority / category / assignee change is stored with who made it and when. |
| **Analytics** | SLA compliance %, average resolution time, active breaches, unassigned and needs-review counts, breakdowns by status / priority / category. |
| **Dashboard** | A dependency-free single-page UI (served by the API) with live triage preview while typing. |

## Architecture

```
Browser dashboard (static HTML + fetch)
        │  JSON over HTTP, Bearer JWT
        ▼
FastAPI app ── routers/auth.py       register · login · users · roles
        │   ── routers/tickets.py    create · search · update · comment
        │   ── routers/analytics.py  desk summary
        │   ── deps.py               current user + role guards
        │   ── triage.py             ML category + rule-based priority
        │   ── sla.py                SLA policy
        ▼
SQLAlchemy ORM ──► PostgreSQL (Docker)  /  SQLite (local dev + tests)
```

Data model: `users`, `tickets` (→ requester, assignee), `comments`, `ticket_events` (audit log).

## Run it

**Docker (API + PostgreSQL):**

```bash
cp .env.example .env        # then set SECRET_KEY
docker compose up --build
```

**Local (SQLite, no Docker needed):**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.seed          # optional: demo users + tickets
uvicorn app.main:app --reload
```

Open <http://localhost:8000> for the dashboard and <http://localhost:8000/docs> for interactive API docs.

Demo accounts created by the seed script (password `Demo@12345`):
`admin@resolveiq.dev`, `agent@resolveiq.dev`, `employee@resolveiq.dev`.
Without the seed, the first account you register becomes the admin.

## API

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | anyone | Create an account |
| POST | `/api/auth/login` | anyone | Get a JWT |
| GET | `/api/auth/me` | signed in | Current user |
| GET | `/api/users` | admin | List users |
| PATCH | `/api/users/{id}/role` | admin | Promote / demote |
| POST | `/api/triage/preview` | signed in | See how a ticket would be routed |
| POST | `/api/tickets` | signed in | Raise a ticket (auto-triaged) |
| GET | `/api/tickets` | signed in | Search: `status`, `priority`, `category`, `q`, `mine`, `breached`, `needs_review`, `limit`, `offset` |
| GET | `/api/tickets/{id}` | owner / staff | Ticket with comments and history |
| PATCH | `/api/tickets/{id}` | owner / staff | Change status, priority, category, assignee |
| POST | `/api/tickets/{id}/comments` | owner / staff | Add a comment |
| GET | `/api/analytics/summary` | staff | Desk health metrics |
| GET | `/health` | anyone | Liveness + DB check |

## Tests and CI

```bash
ruff check .
pytest --cov=app
```

46 tests cover authentication (expired / forged tokens, enumeration-safe login), role boundaries,
ticket visibility, every allowed and forbidden workflow transition, SLA maths, the audit trail,
the triage model and the analytics numbers.

GitHub Actions runs lint + tests on every push, then builds the Docker image, starts it with
PostgreSQL via Compose and runs an end-to-end smoke test against the real database.

## Design decisions

- **Hidden tickets return 404, not 403** — an employee probing other ticket IDs learns nothing about which exist.
- **Login gives the same error for an unknown email and a wrong password** to prevent account enumeration.
- **Confidence threshold with human fallback** — a wrong auto-route costs more than a manual one, so the model abstains when unsure.
- **Priority is rule-based, not learned** — urgency rules must be explainable to the business and adjustable without retraining.
- **SLA breach is computed, not stored** — it depends on the current time, so a stored flag would go stale.
- **State machine in one dictionary** — the allowed transitions are data, so they are easy to read, test and change.

## Limitations and next steps

- The classifier is bootstrapped on a **synthetic, templated dataset** (`ml/generate_data.py`, 1,200 rows) because real
  help-desk exports are confidential. It scores ~100% on its own held-out split, which only shows the pipeline works —
  it is not a real-world accuracy figure. Next step: retrain on a real ticket export and track per-class recall.
- Tables are created at startup; a production deployment would use Alembic migrations.
- SLA hours are wall-clock; business-hours calendars and email / Teams notifications on breach are natural extensions.
- Access tokens are short-lived with no refresh token or revocation list yet.
