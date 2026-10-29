# PMS — what it is and who it's for

A long-form description of the product: the problem it was built for, the
decisions behind its shape, what each part does and where the limits are.
[README](../README.md) is the short version and the install guide; this page is
for deciding whether PMS fits the way you work.

---

## 1. Who it's for

PMS was built by an agency owner who runs **many projects and many different
people at once**: in-house staff, freelance developers, SEO and marketing
contractors, and — increasingly — AI agents doing mechanical work. The question
that mattered every morning was never *"how many story points did we burn"*.
It was:

> What's happening across all projects, where is it stuck, and what needs **me**
> today?

It fits:

- **Agencies and studios** carrying 10–30 client projects at once, where the
  owner is the bottleneck and the cost of a dropped thread is a client.
- **Small product teams** that want a board with short cycles and no ceremony.
- **Solo operators and freelancers** who juggle several clients and want one
  place where the work, the money and the agreements live.
- **Anyone running AI agents on real work**, who needs the agents' work visible
  on the same board as everyone else's.

It does **not** fit: large organisations needing portfolio governance, custom
workflow engines, time tracking and resource planning. That's Jira's job, and
PMS deliberately doesn't compete for it.

## 2. The problem

Running many small projects fails in a specific way. Each project is simple;
the *set* of them is not. The usual failure modes:

| What goes wrong | What it looks like |
|---|---|
| The state lives in people's heads and chats | The owner asks "where are we on X?" and waits a day for the answer |
| Trackers model one big project well and twenty small ones badly | Twenty boards, no single view, nothing rolls up |
| Agreements with the client drift from the plan | Two months later nobody can say what was actually promised |
| Plans live in documents, work lives in a tracker | The plan is out of date the week after it's written |
| Money is in a spreadsheet nobody opens | Work is delivered, the invoice is never sent |
| Blockers are invisible until the deadline | "We were waiting for the client" surfaces at the demo |

PMS answers each of these with one principle: **only the facts are stored, and
everything else is derived from them.** Progress, overdue, what's blocking the
plan and what the client still owes an answer on are all computed from tasks
and their statuses — never typed in a second time. A number in PMS cannot
disagree with the board, because it *is* the board.

## 3. The method: Scrumban

PMS follows **Scrumban** — a Kanban flow with a light Scrum cadence:

- The **board** is the flow: configurable columns per project, soft WIP limits,
  explicit blockers.
- **Sprints** are short, optional and exist to create a rhythm and a
  conversation, not a contract. Starting one needs a goal; completing one rolls
  unfinished work forward or back to the backlog, with a summary.
- **Initiatives** group work that spans sprints.
- **Roadmaps** hold what was agreed with the client for a period.

No story points ceremony, no velocity charts, no burn-down theatre. Estimates
exist (`story_points`) but nothing in the product forces you to use them.

## 4. The shape of the domain

```
Workspace
└── Project (code: ABC)                      ← the unit of access, workflow and money
    ├── TaskStatus / TaskType                ← configurable per project
    ├── Task (ABC-12)                        ← the unit of work; the key is the shared language
    │   ├── Comment, Attachment, ActivityLog
    │   └── parent / initiative / sprint
    ├── Initiative                           ← a strand of work, optionally a roadmap wave
    ├── Sprint                               ← a timebox with a goal
    ├── Roadmap + RoadmapMetric              ← the agreed period and its baseline → target
    ├── Lead + LeadStage + LeadField         ← an opt-in sales funnel
    ├── Contract + Payment                   ← money, visible to managers only
    └── Decision (a read-only copy)          ← what was decided and what's still open
```

Decisions worth knowing about before you adopt it:

- **Statuses are configurable, categories are not.** Every status a project
  defines maps to one fixed `StatusCategory` (`BACKLOG`, `READY`,
  `IN_PROGRESS`, `BLOCKED`, `REVIEW`, `CHANGES_REQUIRED`, `DONE`). Rename the
  columns however you like; the board logic, dashboards and reports reason
  about the category, so nothing breaks when a column is called "На согласование".
- **Task keys are `CODE-N`**, unique in a workspace, with the counter on the
  project. `ABC-12` is what people say out loud and paste in chat, so it's the
  identifier everywhere, including the short link `/t/abc-12`.
- **Ordering is fractional** (LexoRank-style): dragging a card computes a
  position between its neighbours and never reindexes the column.
- **Roles are two-level**: a workspace role (Owner / Admin / Manager / Member /
  Viewer / Guest) plus a per-project role, so a contractor can be a Member on
  one project and absent from the rest.
- **No access means the project does not exist**: the API answers `404`, not
  `403`. A 403 confirms the project is there, which is itself a leak.
- **Logs are append-only**: an activity log per task, an audit log for admin
  actions. Nothing rewrites history.
- **Modular monolith, no microservices.** One backend process with
  self-contained modules under `backend/app/modules/`. Every schema change goes
  through an Alembic migration.

## 5. What it does

### Board and tasks

Per-project columns, drag & drop, soft WIP limits (a warning, never a block —
a hard limit just teaches people to lie to the tracker). Fast-path create: a
title is enough, everything else is optional and fills in later. Priorities,
assignee and reviewer, acceptance criteria and definition of done, subtasks,
comments, attachments, and an activity log of every change.

Two rules are enforced rather than documented: moving a task to a `DONE`
status stamps `completed_at` (and clears it on reopen), and moving it to a
`BLOCKED` status requires a reason, which then shows up in the roadmap and the
dashboards. A blocker nobody can name isn't a blocker, it's an excuse.

### Sprints, initiatives, backlog

Short sprints with a goal and live stats; one active sprint per project.
Completing a sprint moves unfinished work to the next sprint or the backlog and
returns a summary. Initiatives group tasks across sprints and roll their
progress up. The backlog is everything unsprinted and not done, by priority.

### Roadmaps

A roadmap is the wrapper a plan needs and a board does not have: the **agreed
period** ("month 1, 28.10 – 26.11"), **what it was agreed by** (a date, a note,
a reference to the decision registry), the **waves** inside it, the
**baseline → target → current** table, and a link to the published report.

The parts that could drift are not stored:

- Plan items are ordinary **tasks**; waves are **initiatives** with a roadmap
  id, so progress, overdue and blocked counts come off the board.
- *Waiting on the owner or client* is derived from blocked tasks (with their
  reasons) and the open questions in the decision registry.
- Metric values are **text, not numbers**: real baselines read "0 of 165" or
  "any case returns 200", and forcing them into numbers invents a precision
  nobody has. Reaching a target is a date a human sets during the review.

`pms.py roadmap report` renders the whole thing as a standalone HTML page —
the same page an agency would otherwise write by hand for the client. Because
it's a *render* of PMS, the end-of-period review and the board always agree,
and re-checking is one command rather than an afternoon.

### Dashboards

Portfolio (health, open / overdue / blocked / in-review counters per project,
active sprint, totals), My Tasks, My Reviews, a cross-project task list with
filters and pagination, and a per-project dashboard. Every query is scoped to
the projects you may see.

### Leads and funnels (opt-in per project)

A lead is **not** a task: it has its own funnel stages (each mapped to `OPEN` /
`WON` / `LOST`), its own custom fields, a contact, an append-only journal, and
a linked task for the work it needs. Switch it on per project with a preset
(`sales`, `orders`, `basic`) and edit stages and fields afterwards.

Intake needs no user account: a website form or a marketplace adapter posts to
`POST /ingest/leads` with the project's `X-Lead-Token` (stored as a hash, shown
once). Repeats with the same `source` + `external_id` never duplicate, and data
that doesn't match the field schema is kept in `data._extra` rather than
dropped — losing a real lead to a schema mismatch is the one failure a funnel
can't afford.

### Money

Contracts and payments per project: a payment is its own row (kind, amount,
planned date, actual date, invoice and act numbers, status `EXPECTED` →
`INVOICED` → `PAID` / `CANCELLED`, optional link to a milestone). A payment
calendar and a forecast fall out of those rows. **Overdue is computed, never
stored** — a nightly job that rewrites statuses lies the first time it fails.
Amounts are visible to managers and above; a contractor on the project sees the
work, not the money.

### Decisions

A read-only copy of the decision registries that live in the owner's wiki
(YAML with its own CLI and git history). PMS receives the set via
`PUT /decisions/sync` and shows it: a tab per project, a cross-project page,
short links `/d/ssk-p-030`, decision numbers in task text turned into links,
and the tasks a decision is attached to. The source of truth stays where it is
edited; PMS is the place it gets read.

### Notifications, search, i18n

In-app notifications on assignment, review requests, change requests and
comments (never to the actor). Search across task keys, titles, descriptions
and comments, scoped to what you can see. The interface language is per user
(`ru` / `en` out of the box); adding one is an enum entry and a dictionary.

## 6. AI agents are first-class users

The reason the CLI exists at the quality it does: **agents work the same board
as people.** An agent gets a service account, a project role and
`scripts/pms.py` — a stdlib-only client over the REST API, no dependencies to
install:

```bash
pms.py inbox --assignee opencode          # the agent's queue across all projects
pms.py show ABC-12                        # the task, its criteria and comments
pms.py status ABC-12 "In Progress"
pms.py comment ABC-12 "done, artefacts in reports/"
pms.py status ABC-12 Blocked --reason "waiting for GSC access"
```

Because permissions are enforced on the backend, an agent is constrained by its
project role like any other user — it cannot read a project it wasn't added to,
and it cannot see money. Because the activity log is append-only, every move an
agent made is auditable afterwards. And because the agent's work lands on the
same board, a human reviewing the week sees one flow, not an "AI section".

The pattern that makes it work in practice: a human (or an orchestrating agent)
files the task with acceptance criteria, the agent picks it up from its inbox
and reports back in comments, and **only a human moves it to DONE** after
checking the artefacts.

## 7. Security and data

- Passwords hashed with **Argon2**; JWT access + refresh with refresh rotation.
- **All** permission checks on the backend. The frontend hides what you can't
  use; the API refuses it regardless.
- Project visibility is enforced at the query level: invisible projects are
  absent from every list, dashboard, search result and export.
- Secrets only through environment variables, never in the repository.
- Attachments stored on a mounted volume and streamed through the API with the
  same checks (S3-compatible storage is configurable).
- `deploy/backup-db.sh` takes a daily `pg_dump` plus the attachments volume
  with retention, and deletes old copies only after a new one verifies.
- Self-hosted by design: the data stays on your server, and there is no
  telemetry.

## 8. What it is not

- **Not a Jira replacement** for large organisations: no custom workflow
  engine, no portfolio governance, no plugin marketplace.
- **No time tracking or billing by the hour.** Money is about agreements and
  payments, not timesheets.
- **No Gantt chart.** Roadmaps model what was agreed for a period, not a
  dependency graph of 300 bars.
- **No public demo instance.** Clone it and run `docker compose up`; the whole
  stack is four containers.
- **Not multi-tenant SaaS.** The data model has workspaces, but one deployment
  is meant for one organisation.

## 9. Running it

One `docker compose up --build` brings up frontend, backend, Postgres and Redis;
the backend runs its migrations on boot and `python -m app.cli seed` creates the
first Owner. Behind a reverse proxy with TLS, it's the same compose file.
See [README](../README.md#quick-start-docker) and
[docs/DEPLOY.md](DEPLOY.md).

Stack: Python / FastAPI / SQLAlchemy 2 (async) / Pydantic 2 / PostgreSQL /
Redis on the backend, Next.js (App Router) / React / TypeScript / Tailwind on
the frontend. **MIT licensed** — fork it, rename it, run it for your clients.

## 10. Questions people ask

**Can I use it for one project?** Yes, though most of the point is the
cross-project view.

**Do clients get access?** The intended answer is no: clients get reports and
links, the board stays internal. There is a Guest project role if you want
otherwise, but there's no client portal.

**Can I rename the columns to our process?** Yes — statuses and types are
per-project. Only their category is fixed, and that's what keeps the board
logic honest.

**Does it work in English?** Yes, per user. Some built-in presets (the lead
funnel stages) are seeded in Russian and are editable after creation.

**How do I get data out?** It's your Postgres. The REST API covers everything
the UI does, `pms.py --json` prints machine-readable output, and
`pms.py roadmap report` renders a client-ready HTML page.

**Is it stable?** It runs a real agency day to day. The API is not versioned
yet, so pin a commit if you build on it.
