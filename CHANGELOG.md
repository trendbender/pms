# Changelog

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
