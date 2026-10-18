# PMS — Agile Project Operating System

A self-hostable **Scrumban** system for managing projects, teams and tasks —
Kanban board + short sprints + the Agile practices that matter, without the
weight of a full-blown Jira.

**Built for an agency running many client projects at once.** It's the light,
simple operational layer that answers *"what's happening / where are the blockers
/ what needs me right now"* across dozens of projects — and it's designed so that
**AI agents can see and drive the board and backlog too**, creating, updating and
closing tasks through a tiny CLI and the REST API. The result is one live log of
work across every client, which you can roll up into monthly per-project reports.

Projects that sell can switch on **leads**: a per-project sales funnel with its own
stages and fields, fed by website forms and partner sites through an ingest key,
plus **contracts and payments** to see what's invoiced and what's due.

**License:** MIT · **Stack:** FastAPI · PostgreSQL · Redis · Next.js · TypeScript

> Not another Jira. Minimal moving parts, clear ownership, a visible flow, short
> feedback loops. Everything runs from one `docker compose up`.

<!-- Screenshots live in docs/img/ and are added in the showcase pass. -->
<!-- ![Board](docs/img/board.png) -->

---

## Features

- **Kanban board** — configurable columns (statuses) per project, fractional
  ordering (LexoRank-style, no reindexing), native drag & drop, soft WIP limits.
- **Tasks** — human-readable keys `CODE-N` per project, fast-path create
  (title-only), priorities, assignee/reviewer, acceptance criteria / DoD,
  parent/initiative/sprint links, append-only activity log, comments.
- **Sprints & initiatives** — short sprints with goals and stats, start/complete
  flow (unfinished tasks roll to the next sprint or the backlog), initiatives to
  group tasks with progress rollup, a prioritized backlog.
- **Dashboards** — Portfolio (per-project health + open/overdue/blocked/review
  counters + active sprint), My Tasks, My Reviews, cross-project All Tasks with
  filters and pagination, per-project dashboard.
- **Leads & funnels** (opt-in per project) — a lead is its own entity, not a
  task: per-project stages with an OPEN / WON / LOST meaning, custom fields
  (text, number, money, date, select, phone, email, url), an append-only journal
  with comments, and a linked task for the work a lead needs. Board with drag &
  drop, table with search, funnel stats (conversion by stage and source, open and
  won amounts, days to close). Ready-made presets: sales and orders.
- **Lead intake by key** — website forms and partner adapters post to
  `POST /ingest/leads` with a per-project `X-Lead-Token` (stored as a hash, shown
  once). Repeats with the same `source` + `external_id` never create duplicates;
  data that doesn't fit the field schema is kept, not dropped.
- **Money** — contracts and payments per project (expected / invoiced / paid),
  a payment calendar and forecast; overdue is computed, never stored. Visible to
  managers only.
- **Notifications & search** — in-app notifications on assignment, review
  requests, change requests and comments; full-text-ish search across task keys,
  titles, descriptions and comment bodies.
- **Roles & permissions** — two-level RBAC (workspace roles + per-project roles),
  enforced **entirely on the backend**. No project access → the project is
  invisible (404, not 403).
- **Auth** — email/password with Argon2 hashing, JWT access/refresh with refresh
  rotation.
- **i18n** — interface language per user (`ru` / `en` out of the box; add a
  language with one enum entry + one dictionary).

## Architecture

A **modular monolith** — no microservices. The backend is organized into
self-contained modules under `backend/app/modules/` (auth, users, permissions,
projects, tasks, comments, initiatives, sprints, dashboard, notifications,
search, attachments). All DB changes go through Alembic migrations.

- **Backend:** Python, FastAPI, SQLAlchemy 2 (async), Pydantic 2, PostgreSQL, Redis
- **Frontend:** Next.js (App Router), React, TypeScript, Tailwind

---

## Quick start (Docker)

```bash
git clone https://github.com/trendbender/pms.git
cd pms
cp .env.example .env          # edit secrets: set a strong JWT_SECRET + DB password
docker compose up --build     # backend runs `alembic upgrade head` on boot
docker compose exec backend python -m app.cli seed   # create the first Owner + Workspace
```

- Frontend: http://localhost:3000
- API + OpenAPI docs: http://localhost:8000/docs
- Postgres on `localhost:5433`, Redis on `localhost:6380`

Log in with the bootstrap Owner from your `.env`
(`BOOTSTRAP_OWNER_EMAIL` / `BOOTSTRAP_OWNER_PASSWORD`).

## Configuration

All configuration is via environment variables — see [`.env.example`](.env.example)
for the full list. Key ones:

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Signing secret — **set a long random value**. |
| `POSTGRES_*` / `DATABASE_URL` | Database connection. |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API. |
| `BOOTSTRAP_OWNER_*` | First Owner account created by `app.cli seed`. |
| `NEXT_PUBLIC_API_URL` | Where the frontend reaches the API. |
| `NEXT_PUBLIC_BRAND_NAME` / `_BADGE` / `_URL` | Optional branding on the login screen (defaults to a neutral "PMS"). |
| `STORAGE_*` | S3-compatible object storage for attachments (optional). |
| `SMTP_*` | Outgoing mail for invitations / notifications (optional). |

## Deployment

Self-host with Docker Compose behind a reverse proxy that terminates TLS. A
generic guide (compose, nginx vhost example, TLS, backups) is in
[`docs/DEPLOY.md`](docs/DEPLOY.md), with a starting nginx config in
[`deploy/nginx.example.conf`](deploy/nginx.example.conf).

---

## Local development (without Docker)

**Backend**

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL="postgresql+asyncpg://USER@127.0.0.1:5432/pms"
export JWT_SECRET="dev_secret"
alembic upgrade head
python -m app.cli seed
uvicorn app.main:app --reload
```

Tests (need a `pms_test` database):

```bash
export TEST_DATABASE_URL="postgresql+asyncpg://USER@127.0.0.1:5432/pms_test"
pytest -q
ruff check .
```

**Frontend**

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

**Migrations** — models live in `backend/app/models/`. After a change:

```bash
cd backend && alembic revision --autogenerate -m "description"
alembic upgrade head
```

---

## Project structure

```
pms/
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── core/        # config, database, security (Argon2/JWT), redis, deps
│   │   ├── models/      # SQLAlchemy — the full domain schema
│   │   └── modules/     # auth, users, permissions, projects, tasks, finance, leads, ...
│   ├── alembic/         # migrations
│   └── tests/
├── frontend/            # Next.js (App Router)
├── scripts/             # pms.py — a stdlib-only CLI over the REST API
└── docs/
```

## CLI — and AI agents

`scripts/pms.py` is a dependency-free (stdlib-only) command-line client for the
REST API — handy for automation, scripts, bots and **AI coding agents**. Point
an agent at it and it can read a project's board and backlog, open a task for the
work it's about to do, keep the status current, comment, and close it when done —
so every project has one live log a human and an agent share:

```bash
pms.py projects
pms.py project-add --code ABC --name "Acme website" --group Clients
pms.py add --project ABC --title "Fix the contact form" --priority HIGH
pms.py status ABC-12 "In Progress"
pms.py comment ABC-12 "deployed, waiting for review"
pms.py done ABC-12

# leads, for projects that have them switched on
pms.py lead enable --project ABC --preset sales
pms.py lead add --project ABC --title "Acme: SEO audit" --source website --amount 1500
pms.py lead stage ABC-L-1 "Переговоры"   # stage names come from the preset (Russian)
pms.py lead stats --project ABC --from 2026-10-01
```

A website form or a marketplace adapter needs no user account, only the
project's ingest key:

```bash
curl -X POST https://pms.example.com/api/ingest/leads \
  -H "X-Lead-Token: $LEAD_TOKEN" -H "Content-Type: application/json" \
  -d '{"source": "website", "external_id": "form-4812", "contact_name": "Jane",
       "email": "jane@example.com", "data": {"budget": 3000}}'
```

Point it at your instance and give it a service account via a small JSON config
(see the docstring at the top of the file).

## Roadmap

Core Scrumban (board, tasks, sprints, initiatives, dashboards, notifications,
search, i18n), money (contracts, payments) and leads with funnels are
implemented, plus daily database backups. On the list next: project hierarchy
(sub-projects under one parent), moving tasks between projects,
object-storage-backed attachments and email delivery for invitations and
notifications. See [CHANGELOG.md](CHANGELOG.md).

## Contributing

Issues and pull requests are welcome. Please keep changes focused, run
`pytest` and `ruff check .` for backend changes and `npm run build` for the
frontend before opening a PR. All permission checks belong on the backend, and
all schema changes go through Alembic migrations.

## License

[MIT](LICENSE) © 2026 KlientLab
