# Changelog

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
