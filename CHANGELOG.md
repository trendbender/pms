# Changelog

## Unreleased

**Inbox.** One trough for everything incoming (decision P-002). AI agents, bots
and reports drop raw material into a project's inbox; the chat is left for what
needs the owner's decision now. An inbox item is deliberately *not* a task: it
never reaches the board, it gets no `CODE-N` key, and clarifying it is what
turns "look at the October report sometime" into a next action.

- Table `inbox_items`; migration `c9d0e1f2a3b4`. `project_id` is nullable — a
  thought does not have to know its project to be written down; an item without
  one is personal and visible to its author and addressee only, so §7 still holds.
- **Six outcomes, no seventh:** did it myself (under two minutes) / task with a
  next concrete action / delegated / calendar — *only* with a commitment
  datetime / reference, with where it landed / trash. The outcome is written
  once and stays: re-resolving is a 409 and a resolved item is not editable, so
  "what became of this" keeps its answer.
- The rules are enforced by the API, not suggested: the outcomes that create a
  task require their own `title` (the raw subject is never copied into it, since
  formulating the action *is* the clarify step), delegating requires an
  assignee, and the calendar outcome requires `start_at` — a calendar where half
  the entries can be skipped stops being a calendar.
- API: `POST /inbox` and `POST /projects/{id}/inbox` (idempotent on
  `source` + `external_id`, so a report run twice does not double the queue),
  `GET /inbox` (open items across visible projects plus one's own personal
  ones), `/inbox/count` for the nav badge and the morning digest, `PATCH` while
  unresolved, `POST /inbox/{id}/resolve`. Permissions `inbox.view` /
  `inbox.manage` start at project member: a viewer or guest — usually the
  client — does not see raw internal material.
- No ingest token, unlike leads (decision T-006): agents call PMS under their
  own accounts (P-004), so every item records who put it there.
- CLI: `pms.py in add|list|count|show|edit|resolve`. The command is `in`, not
  `inbox` — `pms.py inbox --assignee opencode` is the AI pipeline's executor
  queue and its callers stay unbroken (decision P-005: the name stays, renaming the
  pipeline queue would break its scripts for three characters).
- Tests `tests/test_inbox.py` (15), the parallel-repeat one among them: eight bots
  posting the same report at once get one item, not a 500 — the losing insert goes
  through a savepoint, so it doesn't poison the request's transaction.
  **165 pytest** in all.


**Roadmaps.** A roadmap is the wrapper a plan needs and the board does not
have: the agreed period, what it was agreed by, the waves inside it, the
baseline → target → current table and a link to the published report.

- Tables `roadmaps` + `roadmap_metrics`, waves are initiatives
  (`initiatives.roadmap_id`); migration `a7b8c9d0e1f2`.
- Nothing derivable is stored: progress, overdue and blocked counts come from
  the tasks of the waves, and "waiting on the owner or client" from blocked
  tasks plus the open questions of the decision registry copy. Metric values
  are text, not numbers — real baselines read "0 of 165".
- API: `GET /projects/{id}/roadmap` (the current one), `/roadmaps/{id}` with
  waves, metrics and blockers, `/roadmap` as one portfolio timeline, metric
  CRUD; `roadmap.view` for anyone who sees the project, `roadmap.manage` from
  manager up.
- Frontend: a **Roadmap** tab per project and `/roadmap` across projects, where
  the progress bar carries a tick for where the period calendar stands today.
- CLI: `pms.py roadmap list|show|add|edit|wave-add|metric-add|metric-set|report`.
  `report` renders the same white-background HTML the published roadmaps use,
  from PMS data — the report becomes a render, not a second copy of the truth.
  `pms.py status` now takes `--reason` (required for a BLOCKED status, Rule 8).
- Tests `tests/test_roadmaps.py` (6). **129 pytest** in all.

**Docs.** [docs/PRODUCT.md](docs/PRODUCT.md) — the long-form product
description: who it's for, the problem, the domain decisions, AI agents as
first-class users, and what PMS deliberately is not.

**Repository.** The 0.4.0 decision log (running on prod since 21.10) and the
0.4.1 links feature (built live on 26.10, never committed) are now both in
`main` together with the two fixes that had been committed but not deployed.
`pms.py project-edit` and `decisions-sync` came back from the server the same
way.

**Fix: commit before the response.** The request session (`get_db`) committed in
the dependency's exit, and since FastAPI 0.121 a yield dependency exits only
after the response has been sent. A client that got `201` and called right away
could read `404` on the new row; the next create in a row could also hit the
not-yet-committed counter (`POST 409` on leads, `500` on tasks), and a commit
failure was invisible to a client that already had `201`. Seen on pmsdemo
19.10.2026 (2 of 5 attempts); hits `site-leads-api.py` (ingest → comment) and
`pms.py` (add → status).

- The session is injected only via `DbSession = Depends(get_db, scope="function")`
  (`app/core/database.py`): commit / rollback runs after serialization and
  before the response is sent. All call sites switched, `fastapi>=0.121`.
- Tests `tests/test_commit_before_response.py`: order `commit` →
  `http.response.start` on POST lead / task (red before the fix), every
  `get_db` in all routes is `scope="function"`, create → immediate read.
  `httpx.ASGITransport` waits for the whole ASGI call, so the 404 race itself
  is not visible there.
- Live check on uvicorn (local Postgres, +50 ms commit latency to match the
  demo), create → immediate GET, 100 pairs each: before, lead GET 404 50 +
  POST 409 50, task GET 404 50 + POST 500 50; after, 100/100 GET 200 for both
  (and 200/200 each without the added latency). Probe for a stage/demo stack:
  `scripts/commit-race-probe.py`.

**Fix: lead and task numbers under parallel creates.** `lead_counter` /
`task_counter` were incremented in Python, so two simultaneous creates in one
project got the same number: `409 "source and external_id exists"` on leads
(any IntegrityError was reported that way), `500` on tasks. In ingest without
`external_id` the fallback looked up `external_id IS NULL` and could return
someone else's existing lead as `created=False`, losing the new one; with the
same `external_id` the dedup branch itself crashed (`MissingGreenlet` on the
project expired by the savepoint rollback).

- The number comes from one `UPDATE projects SET counter = counter + 1 ...
  RETURNING`: a parallel create waits on the project row lock and gets the
  next number. A losing ingest rolls back its savepoint and does not consume one.
- Only `uq_lead_external` maps to 409 / the ingest dedup; other integrity
  errors are raised as they are.
- Tests `tests/test_key_counters_concurrency.py` (12 parallel creates via
  `asyncio.gather`, each on its own connection): leads, tasks, ingest without
  and with the same `external_id`. All 4 were red before the fix, green 5/5 runs after.

## 0.4.1 — 2026-10-26

**Clickable absolute links** in task descriptions and comments.

- Projects get a website field (`projects.site_url`, migration `f6a7b8c9d0e1`,
  project settings → "Project website"). A site path in a task or comment
  (`/lk/turnkey/?admin=1&branch=63680`) is saved as an absolute URL on that
  site, so the link stays absolute in the database, notifications and the CLI
  (`backend/app/core/links.py`, on task create/update and comment create/edit).
- Rendering (`frontend/lib/links.ts`): bare `https://…` URLs, site paths, task
  keys (`SSK-262` → `/t/ssk-262`, existing project codes only) and decision
  numbers become links. Trailing `.`, `,` and an unbalanced `)` stay outside a
  link; `&` and `?` stay inside. Code spans, file paths (`/srv/…`, `~/…`,
  `*.py`), single-segment slash commands (`/clear`) and ready Markdown links
  are left alone.
- Tests: `backend/tests/test_links.py`, `frontend` → `npm test` (node --test).

## 0.4.0 — 2026-10-21

**Decision log**, a read-only copy of the per-project decision registries.

- The registries stay where they are edited (YAML files with their own CLI and
  git history); PMS receives the whole set via `PUT /decisions/sync` (workspace
  admins only) and replaces each registry it is sent: new records are created,
  changed ones updated, missing ones deleted. Table `decisions` (migration
  `e5f6a7b8c9d0`).
- Every decision has a short link `/d/<project code>-<id>` (`/d/ssk-p-030`);
  cross-project rules live in the `_global` registry under prefix `G`
  (`/d/g-p-022`) and are visible to workspace owners and admins only. Project
  decisions follow project visibility.
- A **Decisions** tab on every project (search, status and area filters, open
  questions on top) and a cross-project page `/decisions`.
- Decision numbers in task descriptions and comments become links: `P-030` for
  the task's own project, `SSK:P-030` or `_global:P-022` for another registry.
  Task keys (`SSK-203`) are not touched.
- Task keys mentioned in a decision (its `tasks` list or links in `source`) are
  shown on the decision page with their status, and the task page lists the
  decisions that reference it (`GET /decisions/by-task/{key}`).
- Tests `tests/test_decisions.py` (sync, re-sync, refs, visibility).

## 0.3.0 — 2026-10-18

**Leads & funnels**, opt-in per project.

- A lead is its own entity with per-project funnel stages (OPEN / WON / LOST),
  custom fields validated into `leads.data`, an append-only journal with
  comments and a linked task for the work it needs. Moving a lead to a LOST
  stage requires a reason.
- Presets on enable: `sales` (new → qualification → proposal sent →
  negotiation → audit paid → won / lost), `orders` (new → confirmed → driver
  assigned → done → paid / cancelled) and `basic`. Stages and fields stay
  editable afterwards.
- Lead intake: `POST /ingest/leads` with a per-project `X-Lead-Token` (sha256
  in the database, the value is shown once). Idempotent on `source` +
  `external_id`; a repeat can move the stage or, with `update: true`, update
  fields. Values that don't match the field schema land in `data._extra`
  instead of being rejected.
- Board with drag & drop, table with search and filters, funnel stats
  (`/projects/{id}/leads/stats`), short lead links `/l/<key>`, funnel settings
  page with stages, fields and ingest keys.
- Permissions: `lead.view` / `lead.manage` for project members,
  `lead.delete` for managers, `lead.settings` for project owners.
- CLI: `pms.py lead list|add|show|stage|edit|comment|task|stats|enable|tokens|token-add|ingest`.
- Migration `d4e5f6a7b8c9`. Next.js 15.5.28.

## 0.2.0 — 2026-10-03

- **Money**: contracts and payments per project (expected / invoiced / paid /
  cancelled), payment calendar and forecast, milestone due dates; `pms.py money`.
- Project settings page, unarchive, readable project URLs (`/projects/abc`).
- Daily database and attachments backup script with retention.
- New tasks go to the bottom of their column; navigation fixes.

## 0.1.0 — 2026-09-17

- Open-source release (MIT): Kanban / Scrumban board, tasks, sprints,
  initiatives, dashboards, notifications, search, two-level RBAC, i18n, CLI.
