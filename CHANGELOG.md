# Changelog

## Unreleased

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
