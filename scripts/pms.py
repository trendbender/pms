#!/usr/bin/env python3
"""pms.py — a dependency-free CLI over the PMS REST API, for scripts and bots.

Stdlib only. Talks to a running PMS backend over HTTP. Auth uses a dedicated
service account whose credentials live in a local config file (chmod 600) —
never on the command line.

Config, default ~/.config/pms.json (override with PMS_CONFIG):
    {"api_base": "http://localhost:8000", "email": "...", "password": "..."}

The access token is cached under ~/.cache and refreshed automatically.

Examples:
    pms.py projects
    pms.py project-add --code AXM --name "Axiom Charter" --group "Клиентские"
    pms.py list --project ABC
    pms.py show ABC-26
    pms.py add --project ABC --title "Check the forms" --priority HIGH
    pms.py add --project ABC --title "Update the block" --desc "..." --attach /tmp/shot.jpg
    pms.py add --project ABC --title "Send the questions" --due завтра
    pms.py edit ABC-26 --due 2026-10-14      # снять срок: --due none
    pms.py attach ABC-26 /tmp/screenshot.jpg
    pms.py comment ABC-26 "done, waiting for review"
    pms.py status ABC-26 "In Progress"
    pms.py done ABC-26
    pms.py assign ABC-26 --to teammate@example.com
    pms.py members --project ABC
    pms.py member-add --user agent@example.com --role MEMBER          # all projects
    pms.py member-add --user agent@example.com --project ABC --role VIEWER
    pms.py rm ABC-26 --yes

Add --json to most read commands for machine output.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from decimal import Decimal
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Back-compat: honour the older PMS_BOT_* env names and the older config path
# (~/.config/pms_bot.json), which deployed bots still use.
CONFIG_PATH = os.environ.get("PMS_CONFIG") or os.environ.get(
    "PMS_BOT_CONFIG", str(Path.home() / ".config/pms.json")
)
LEGACY_CONFIG_PATH = str(Path.home() / ".config/pms_bot.json")
CACHE_PATH = Path(
    os.environ.get("PMS_CACHE")
    or os.environ.get("PMS_BOT_CACHE", str(Path.home() / ".cache/pms_token.json"))
)


# --------------------------------------------------------------------------- #
# HTTP + auth
# --------------------------------------------------------------------------- #


def _load_config() -> dict:
    paths = [CONFIG_PATH]
    if LEGACY_CONFIG_PATH not in paths:
        paths.append(LEGACY_CONFIG_PATH)
    for path in paths:
        try:
            with open(path) as fh:
                cfg = json.load(fh)
            break
        except FileNotFoundError:
            continue
    else:
        die(f"config not found: {CONFIG_PATH} (create it, chmod 600)")
    cfg.setdefault("api_base", "http://localhost:8000")
    if not cfg.get("email") or not cfg.get("password"):
        die(f"config {CONFIG_PATH} must contain email + password")
    return cfg


def _request(method: str, url: str, token: str | None, body=None, is_json=True):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.status == 204 or not raw:
                return None
            return json.loads(raw) if is_json else raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except Exception:
            detail = raw
        raise ApiError(e.code, detail if isinstance(detail, str) else json.dumps(detail))


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _encode_multipart(field_name: str, filename: str, content_type: str, data: bytes):
    """Build a minimal multipart/form-data body for one file field (stdlib only)."""
    boundary = f"----pmsBoundary{uuid.uuid4().hex}"
    crlf = b"\r\n"
    disp = f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'
    body = b"".join([
        f"--{boundary}".encode(), crlf,
        disp.encode(), crlf,
        f"Content-Type: {content_type}".encode(), crlf, crlf,
        data, crlf,
        f"--{boundary}--".encode(), crlf,
    ])
    return boundary, body


class Client:
    def __init__(self, cfg: dict):
        self.base = cfg["api_base"].rstrip("/")
        # Web base for human task links: api_base without the trailing /api.
        self.web_base = self.base[:-4] if self.base.endswith("/api") else self.base
        self.cfg = cfg
        self.token: str | None = None

    def task_url(self, key: str) -> str:
        # Short, word-like share link (/t/ssk-23) — avoids the phishing heuristics
        # that flag long random UUID paths (/tasks/<uuid>). Lowercased for tidy
        # URLs; the backend resolves keys case-insensitively. UUID links still work.
        return f"{self.web_base}/t/{key.lower()}"

    def _login(self) -> None:
        tok = _request(
            "POST",
            f"{self.base}/auth/login",
            None,
            {"email": self.cfg["email"], "password": self.cfg["password"]},
        )
        self.token = tok["access_token"]
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps({"access": self.token, "ts": time.time()}))
            os.chmod(CACHE_PATH, 0o600)
        except OSError:
            pass

    def _load_cached(self) -> None:
        try:
            c = json.loads(CACHE_PATH.read_text())
            # access tokens live 30 min; refresh a bit early
            if time.time() - c.get("ts", 0) < 25 * 60:
                self.token = c.get("access")
        except (OSError, ValueError):
            pass

    def call(self, method: str, path: str, body=None, is_json=True):
        if self.token is None:
            self._load_cached()
        if self.token is None:
            self._login()
        try:
            return _request(method, f"{self.base}{path}", self.token, body, is_json)
        except ApiError as e:
            if e.status == 401:  # token expired/invalid — log in fresh and retry once
                self._login()
                return _request(method, f"{self.base}{path}", self.token, body, is_json)
            raise

    def upload(self, task_id: str, file_path: str) -> dict:
        """Upload a local file as a task attachment (multipart POST)."""
        p = Path(file_path)
        if not p.is_file():
            die(f"file not found: {file_path}")
        data = p.read_bytes()
        if not data:
            die(f"file is empty: {file_path}")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        boundary, payload = _encode_multipart("file", p.name, ctype, data)
        url = f"{self.base}/tasks/{task_id}/attachments"

        def send() -> dict:
            headers = {
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {self.token}",
            }
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                raw = e.read().decode(errors="replace")
                try:
                    detail = json.loads(raw).get("detail", raw)
                except Exception:
                    detail = raw
                raise ApiError(e.code, detail if isinstance(detail, str) else json.dumps(detail))

        if self.token is None:
            self._load_cached()
        if self.token is None:
            self._login()
        try:
            return send()
        except ApiError as e:
            if e.status == 401:  # token expired/invalid — refresh and retry once
                self._login()
                return send()
            raise


# --------------------------------------------------------------------------- #
# Resolvers
# --------------------------------------------------------------------------- #

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
KEY_RE = re.compile(r"^([A-Za-z]+)[-–—]?(\d+)$")


def resolve_project(client: Client, ref: str) -> dict:
    projects = client.call("GET", "/projects")
    if UUID_RE.match(ref):
        for p in projects:
            if p["id"] == ref:
                return p
    low = ref.strip().lower()
    for p in projects:
        if p.get("code", "").lower() == low:
            return p
    for p in projects:
        if low in p.get("name", "").lower():
            return p
    die(f"project not found: {ref} (known codes: {', '.join(sorted(p['code'] for p in projects))})")


def resolve_task(client: Client, key: str) -> dict:
    m = KEY_RE.match(key.strip())
    if not m:
        die(f"bad task key: {key} (expected e.g. SSK-26)")
    code, num = m.group(1), int(m.group(2))
    project = resolve_project(client, code)
    tasks = client.call("GET", f"/projects/{project['id']}/tasks")
    want = f"{code.upper()}-{num}"
    for tsk in tasks:
        if tsk["key"].upper() == want:
            return tsk
    die(f"task not found: {want}")


def resolve_user(client: Client, ref: str) -> dict:
    users = client.call("GET", "/users")
    low = ref.strip().lower()
    for u in users:
        if u.get("email", "").lower() == low:
            return u
    for u in users:
        if low in u.get("name", "").lower():
            return u
    die(f"user not found: {ref}")


def project_statuses(client: Client, project_id: str) -> list[dict]:
    return client.call("GET", f"/projects/{project_id}/statuses")


def pick_status(statuses: list[dict], query: str) -> dict | None:
    low = query.strip().lower()
    for s in statuses:  # exact name
        if s["name"].lower() == low:
            return s
    for s in statuses:  # category (BACKLOG/IN_PROGRESS/DONE/…)
        if s["category"].lower() == low:
            return s
    for s in statuses:  # partial name
        if low in s["name"].lower():
            return s
    return None


# --------------------------------------------------------------------------- #
# Сроки (due_at)
# --------------------------------------------------------------------------- #

# PMS живёт по Москве, перехода на летнее время в РФ нет — фиксированный сдвиг
# честнее зависимости от tzdata на машине, где крутится бот.
MSK = _dt.timezone(_dt.timedelta(hours=3))

DUE_HELP = ("срок: 2026-09-24, 24.09, завтра, +3b (рабочих дней, канон для клиентских "
            "проектов), +3d (календарных), '2026-09-24 18:00'. Дата без времени = конец дня "
            "по Москве; относительный срок, выпавший на выходной, переносится вперёд")

# Рабочие дни (вики conventions/business-days.md). Helper лежит рядом со скриптом;
# нет его — считаем по календарю и говорим об этом вслух, молча врать сроком нельзя.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from workdays import add_workdays as _add_workdays, next_workday as _next_workday
except Exception:  # noqa: BLE001 — helper необязателен, деградируем предсказуемо
    _add_workdays = None
    _next_workday = None


_DUE_CLEAR = {"", "none", "нет", "-", "null", "снять"}
_DUE_REL = {"today": 0, "сегодня": 0, "tomorrow": 1, "завтра": 1, "послезавтра": 2}
_DUE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m %H:%M", "%d.%m")


def _end_of_day(d: _dt.date) -> str:
    return _dt.datetime.combine(d, _dt.time(23, 59), MSK).isoformat()


def _roll(d):
    """Относительный срок, выпавший на выходной или праздник, двигаем вперёд.

    Явно названную дату не трогаем: она обычно приходит извне (площадка, договор)
    и подмена такого срока хуже, чем дедлайн в субботу.
    """
    return _next_workday(d) if _next_workday else d


def parse_due(value: str) -> str | None:
    """'2026-09-24' | '24.09' | 'завтра' | '+3d' | '2026-09-24 18:00' → ISO +03:00.

    Голая дата означает конец дня (23:59 МСК): иначе задача со сроком «сегодня»
    сразу считается просроченной. Возвращает None для none/нет/- — вызывающий
    код должен отправить null и снять срок.
    """
    raw = (value or "").strip().lower()
    if raw in _DUE_CLEAR:
        return None

    now = _dt.datetime.now(MSK)
    if raw in _DUE_REL:
        return _end_of_day(_roll((now + _dt.timedelta(days=_DUE_REL[raw])).date()))

    m = re.fullmatch(r"\+?(\d+)\s*(рд|b|р|[dдwнmм])", raw)
    if m:
        unit, n = m.group(2), int(m.group(1))
        if unit in ("b", "р", "рд"):  # рабочие дни — канон для клиентских проектов
            if _add_workdays is None:
                die("рабочие дни недоступны: рядом с pms.py нет workdays.py "
                    "(вики conventions/business-days.md). Поставь срок датой или в +Nd")
            return _end_of_day(_add_workdays(now.date(), n))
        step = {"d": 1, "д": 1, "w": 7, "н": 7, "m": 30, "м": 30}[unit]
        return _end_of_day(_roll((now + _dt.timedelta(days=n * step)).date()))

    for fmt in _DUE_FORMATS:
        try:
            dt = _dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:  # «24.09» — текущий год
            dt = dt.replace(year=now.year)
        if "%H" not in fmt:  # дата без времени — конец дня
            dt = dt.replace(hour=23, minute=59)
        return dt.replace(tzinfo=MSK).isoformat()

    die(f"не понимаю срок: {value} "
        f"(примеры: 2026-09-24, 24.09, завтра, +3d, '2026-09-24 18:00', none)")


def fmt_due(value: str | None, *, long: bool = False) -> str:
    """ISO из API → «24.09», «24.09 (завтра)», «24.09 (просрочено)». Пусто, если срока нет."""
    if not value:
        return ""
    try:
        dt = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    local = dt.astimezone(MSK)
    days = (local.date() - _dt.datetime.now(MSK).date()).days
    label = {0: "сегодня", 1: "завтра", 2: "послезавтра", -1: "вчера"}.get(days)
    if days < 0 and label is None:
        label = f"просрочено на {-days} дн."
    elif days < 0:
        label = f"{label}, просрочено"
    date = local.strftime("%d.%m.%Y" if long else "%d.%m")
    if local.hour != 23 or local.minute != 59:
        date += local.strftime(" %H:%M")
    return f"{date} ({label})" if label else date


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def out(data, as_json: bool, human) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        human(data)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_whoami(client, args):
    me = client.call("GET", "/auth/me")
    out(me, args.json, lambda m: print(f"{m['name']} <{m['email']}> · role={m.get('system_role')}"))


def cmd_projects(client, args):
    # the API hides archived projects unless asked
    ps = client.call("GET", "/projects?include_archived=true" if args.archived else "/projects")
    ps.sort(key=lambda p: (p.get("group_name") or "", p["code"]))
    out(ps, args.json, lambda ps: [
        print(f"{p['code']:<6} {p['name']}  ·  {p.get('group_name') or '—'}  [{p['status']}/{p['health']}]")
        for p in ps
    ])


def cmd_project_add(client, args):
    """Create a project. The code is permanent: task keys and links hang off it."""
    body = {"name": args.name, "code": args.code.strip().upper()}
    if args.group:
        body["group_name"] = args.group
    if args.goal:
        body["goal"] = args.goal
    p = client.call("POST", "/projects", body)

    def human(p):
        print(f"создан проект {p['code']} — {p['name']} · {p.get('group_name') or '—'}")
        print(f"{client.web_base}/projects/{p['code'].lower()}")

    out(p, args.json, human)


def cmd_list(client, args):
    project = resolve_project(client, args.project)
    tasks = client.call("GET", f"/projects/{project['id']}/tasks")
    if args.status:
        low = args.status.lower()
        tasks = [t for t in tasks if low in (t.get("status_name") or "").lower()
                 or low == (t.get("status_category") or "").lower()]
    users = {u["id"]: u["name"] for u in client.call("GET", "/users")}

    def render(ts):
        print(f"# {project['code']} {project['name']} — {len(ts)} задач")
        for t in ts:
            who = users.get(t.get("assignee_id"), "—")
            blk = " ⛔" if t.get("is_blocked") else ""
            due = fmt_due(t.get("due_at"))
            due = f" ⏰{due}" if due else ""
            print(f"{t['key']:<8} [{t.get('status_name','?'):<12}] {t['priority']:<8} @{who}{blk}{due}  {t['title']}")
            print(f"         {client.task_url(t['key'])}")
    out(tasks, args.json, render)


def cmd_show(client, args):
    task = resolve_task(client, args.key)
    full = client.call("GET", f"/tasks/{task['id']}")
    comments = client.call("GET", f"/tasks/{task['id']}/comments")
    users = {u["id"]: u["name"] for u in client.call("GET", "/users")}
    if args.json:
        out({"task": full, "comments": comments}, True, None)
        return
    print(f"{full['key']} — {full['title']}")
    print(client.task_url(full["key"]))
    print(f"статус: {full.get('status_name')} ({full.get('status_category')}) · приоритет: {full['priority']}")
    print(f"исполнитель: {users.get(full.get('assignee_id'),'—')} · проверяющий: {users.get(full.get('reviewer_id'),'—')}")
    if full.get("due_at"):
        print(f"срок: {fmt_due(full['due_at'], long=True)}")
    if full.get("description"):
        print(f"\n{full['description']}")
    if full.get("is_blocked"):
        print(f"\n⛔ заблокирована: {full.get('blocked_reason') or ''}")
    if comments:
        print(f"\nКомментарии ({len(comments)}):")
        for c in comments:
            print(f"  · {users.get(c.get('author_id'),'?')}: {c['body']}")


def cmd_add(client, args):
    project = resolve_project(client, args.project)
    body = {"project_id": project["id"], "title": args.title}
    if args.desc:
        body["description"] = args.desc
    if args.priority:
        body["priority"] = args.priority.upper()
    if args.due:
        due = parse_due(args.due)
        if due:
            body["due_at"] = due
    task = client.call("POST", "/tasks", body)
    if args.assignee:
        user = resolve_user(client, args.assignee)
        client.call("PATCH", f"/tasks/{task['id']}", {"assignee_id": user["id"]})
    attached = [client.upload(task["id"], fp) for fp in (args.attach or [])]

    def human(t):
        print(f"создана {t['key']}: {t['title']}")
        if t.get("due_at"):
            print(f"срок: {fmt_due(t['due_at'], long=True)}")
        if attached:
            print(f"вложений: {len(attached)} ({', '.join(a.get('filename', '?') for a in attached)})")
        print(client.task_url(t["key"]))

    out(task, args.json, human)


def cmd_attach(client, args):
    task = resolve_task(client, args.key)
    results = [client.upload(task["id"], fp) for fp in args.files]

    def human(atts):
        for a in atts:
            print(f"вложение добавлено к {task['key']}: {a.get('filename')} ({a.get('size_bytes', '?')} b)")
        print(client.task_url(task["key"]))

    out(results, args.json, human)


def cmd_edit(client, args):
    task = resolve_task(client, args.key)
    body = {}
    if args.title:
        body["title"] = args.title
    if args.desc is not None:
        body["description"] = args.desc
    if args.priority:
        body["priority"] = args.priority.upper()
    if args.due is not None:
        body["due_at"] = parse_due(args.due)  # None снимает срок
    if not body:
        die("nothing to change (pass --title / --desc / --priority / --due)")
    t = client.call("PATCH", f"/tasks/{task['id']}", body)

    def human(t):
        print(f"обновлена {t['key']}")
        if "due_at" in body:
            print(f"срок: {fmt_due(t.get('due_at'), long=True) or 'снят'}")
        print(client.task_url(t["key"]))

    out(t, args.json, human)


def cmd_comment(client, args):
    task = resolve_task(client, args.key)
    c = client.call("POST", f"/tasks/{task['id']}/comments", {"body": args.text})
    out(c, args.json, lambda _: print(f"комментарий добавлен к {task['key']}\n{client.task_url(task['key'])}"))


def cmd_status(client, args):
    task = resolve_task(client, args.key)
    statuses = project_statuses(client, task["project_id"])
    st = pick_status(statuses, args.status)
    if st is None:
        die(f"status not found: {args.status} (available: {', '.join(s['name'] for s in statuses)})")
    t = client.call("PATCH", f"/tasks/{task['id']}/status", {"status_id": st["id"]})
    out(t, args.json, lambda t: print(f"{t['key']} → {t.get('status_name')}\n{client.task_url(t['key'])}"))


def cmd_done(client, args):
    task = resolve_task(client, args.key)
    statuses = project_statuses(client, task["project_id"])
    st = next((s for s in statuses if s["category"] == "DONE"), None)
    if st is None:
        die("no DONE-category status configured for this project")
    t = client.call("PATCH", f"/tasks/{task['id']}/status", {"status_id": st["id"]})
    out(t, args.json, lambda t: print(f"{t['key']} закрыта → {t.get('status_name')}\n{client.task_url(t['key'])}"))


def cmd_assign(client, args):
    task = resolve_task(client, args.key)
    user = resolve_user(client, args.to)
    t = client.call("PATCH", f"/tasks/{task['id']}", {"assignee_id": user["id"]})
    out(t, args.json, lambda t: print(f"{t['key']} назначена на {user['name']}\n{client.task_url(t['key'])}"))


def cmd_rm(client, args):
    task = resolve_task(client, args.key)
    if not args.yes:
        die(f"refusing to delete {task['key']} without --yes")
    client.call("DELETE", f"/tasks/{task['id']}")
    print(f"{task['key']} удалена")


PROJECT_ROLES = ["OWNER", "MANAGER", "MEMBER", "VIEWER", "GUEST"]


def _target_projects(client, args) -> list[dict]:
    """The projects a member command applies to: one (--project) or all of them."""
    if args.project:
        return [resolve_project(client, args.project)]
    return client.call(
        "GET", "/projects?include_archived=true" if args.archived else "/projects"
    )


def cmd_members(client, args):
    project = resolve_project(client, args.project)
    ms = client.call("GET", f"/projects/{project['id']}/members")
    out(ms, args.json, lambda ms: [
        print(f"{m['role']:<8} {m['name']} <{m['email']}>") for m in ms
    ])


def cmd_member_add(client, args):
    """Grant a user access to one project or to every project at once.

    The API upserts, so re-running on a project the user already has only
    changes the role — safe to repeat after new projects appear.
    """
    user = resolve_user(client, args.user)
    body = {"user_id": user["id"], "role": args.role}
    done = []
    for project in _target_projects(client, args):
        client.call("POST", f"/projects/{project['id']}/members", body)
        done.append({"code": project["code"], "name": project["name"], "role": args.role})

    def human(done):
        for d in done:
            print(f"{d['code']:<6} {d['name']}  ·  {d['role']}")
        print(f"{user['name']} <{user['email']}> — доступ в {len(done)} проект(ов)")

    out(done, args.json, human)


def cmd_member_rm(client, args):
    user = resolve_user(client, args.user)
    targets = _target_projects(client, args)
    if not args.project and not args.yes:
        die(f"refusing to drop {user['email']} from {len(targets)} projects without --yes")
    done = []
    for project in targets:
        try:
            client.call("DELETE", f"/projects/{project['id']}/members/{user['id']}")
        except ApiError as e:
            if e.status == 404:  # not a member of this one — nothing to do
                continue
            raise
        done.append({"code": project["code"], "name": project["name"]})

    def human(done):
        for d in done:
            print(f"{d['code']:<6} {d['name']}")
        print(f"{user['name']} <{user['email']}> — убран из {len(done)} проект(ов)")

    out(done, args.json, human)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Деньги (договоры и платежи). Канон процесса — вики projects/klientlab/portfolio-management
# --------------------------------------------------------------------------- #


def _money_fmt(v) -> str:
    """15000.00 -> «15 000 руб.» (в отчётах и чатах пишем руб., не знак валюты)."""
    try:
        n = Decimal(str(v))
    except Exception:  # noqa: BLE001
        return str(v)
    whole = f"{n:,.0f}".replace(",", " ")
    return f"{whole} руб."


def _due_date_only(value: str) -> str | None:
    """Срок платежа это дата, без времени. Понимает и +3b (рабочие дни)."""
    iso = parse_due(value)
    return iso[:10] if iso else None


def _finance_call(client, method, path, body=None):
    """Финансовый модуль может быть ещё не выкачен: 404 объясняем словами."""
    try:
        return client.call(method, path, body)
    except ApiError as e:
        if e.status == 404 and ("/finance" in path or "payments" in path):
            die("финансовый модуль не отвечает на этом инстансе PMS "
                "(не выкачен на прод? см. задачу KL-8)")
        raise


def _payments(client, project=None, include_paid=True, status=None):
    q = []
    if project:
        q.append(f"project_id={project['id']}")
    if status:
        q.append(f"status={status}")
    if not include_paid:
        q.append("include_paid=false")
    path = "/finance/payments" + ("?" + "&".join(q) if q else "")
    return _finance_call(client, "GET", path)


def resolve_payment(client, ref: str) -> dict:
    """Платёж по началу id (8 знаков достаточно) или по точному id."""
    ref = ref.strip().lower()
    rows = _payments(client)
    exact = [p for p in rows if p["id"] == ref]
    if exact:
        return exact[0]
    hits = [p for p in rows if p["id"].startswith(ref)]
    if not hits:
        die(f"платёж не найден: {ref} (смотри pms.py money list)")
    if len(hits) > 1:
        die(f"неоднозначно: {ref} подходит под {len(hits)} платежей, дай больше знаков id")
    return hits[0]


def _print_payment_line(p: dict) -> None:
    mark = "ПРОСРОЧЕН" if p.get("is_overdue") else p["status"]
    due = p.get("due_date") or "без срока"
    proj = p.get("project_code") or ""
    print(f"{p['id'][:8]}  {proj:<5} {_money_fmt(p['amount']):>14}  {due}  [{mark}]  {p['title']}")
    for extra, label in ((p.get("invoice_no"), "счёт"), (p.get("act_no"), "акт")):
        if extra:
            print(f"{'':10}  {label} {extra}")


def cmd_money_list(client, args):
    project = resolve_project(client, args.project) if args.project else None
    rows = _payments(client, project, include_paid=args.all, status=args.status)
    if args.json:
        out(rows, True, None)
        return
    if not rows:
        print("платежей нет" + (f" по проекту {project['code']}" if project else ""))
        return
    head = f"Платежи{' — ' + project['code'] if project else ''}: {len(rows)}"
    print(head)
    for p in rows:
        _print_payment_line(p)
    open_sum = sum(Decimal(str(p["amount"])) for p in rows if p["status"] in ("EXPECTED", "INVOICED"))
    if open_sum:
        print(f"Открыто: {_money_fmt(open_sum)}")


def cmd_money_calendar(client, args):
    cal = _finance_call(client, "GET", f"/finance/calendar?weeks={args.weeks}")
    if args.json:
        out(cal, True, None)
        return
    print(f"Календарь платежей на {cal['today']}")
    blocks = (
        ("Просрочено", cal["overdue"]),
        ("Ближайшие 7 дней", cal["due_soon"]),
        (f"Дальше, до {cal['forecast_until']}", cal["upcoming"]),
        ("Вехи без счёта", cal["unbilled_milestones"]),
        ("Оплачено за неделю", cal["recently_paid"]),
    )
    for title, rows in blocks:
        if not rows:
            continue
        print(f"\n— {title} —")
        for p in rows:
            _print_payment_line(p)
    print()
    print(f"Просрочено всего: {_money_fmt(cal['total_overdue'])}")
    print(f"Открыто всего: {_money_fmt(cal['total_open'])}")
    print(f"Прогноз до {cal['forecast_until']}: {_money_fmt(cal['forecast_amount'])}")


def cmd_money_add(client, args):
    project = resolve_project(client, args.project)
    body = {"title": args.title, "amount": str(args.amount), "kind": args.kind}
    if args.due:
        body["due_date"] = _due_date_only(args.due)
    if args.note:
        body["note"] = args.note
    if args.invoice:
        body["invoice_no"] = args.invoice
    if args.doc:
        body["doc_url"] = args.doc
    if args.initiative:
        body["initiative_id"] = args.initiative
    if args.contract:
        body["contract_id"] = args.contract
    p = _finance_call(client, "POST", f"/projects/{project['id']}/payments", body)

    def human(p):
        print(f"платёж заведён: {p['id'][:8]} · {project['code']} · {_money_fmt(p['amount'])}"
              f" · срок {p.get('due_date') or 'не задан'} · {p['title']}")
    out(p, args.json, human)


def cmd_money_invoice(client, args):
    p = resolve_payment(client, args.id)
    body = {}
    if args.no:
        body["invoice_no"] = args.no
    if args.date:
        body["invoiced_at"] = _due_date_only(args.date)
    if args.due:
        body["due_date"] = _due_date_only(args.due)
    r = client.call("POST", f"/finance/payments/{p['id']}/invoice", body)
    out(r, args.json, lambda r: print(
        f"счёт выставлен: {r['id'][:8]} · {_money_fmt(r['amount'])} · счёт {r.get('invoice_no') or '—'}"
        f" · срок {r.get('due_date') or 'не задан'}"))


def cmd_money_paid(client, args):
    p = resolve_payment(client, args.id)
    body = {}
    if args.date:
        body["paid_at"] = _due_date_only(args.date)
    if args.amount:
        body["amount"] = str(args.amount)
    if args.act:
        body["act_no"] = args.act
    r = client.call("POST", f"/finance/payments/{p['id']}/paid", body)
    out(r, args.json, lambda r: print(
        f"оплачен: {r['id'][:8]} · {_money_fmt(r['amount'])} · {r['paid_at']}"))


def cmd_money_rm(client, args):
    p = resolve_payment(client, args.id)
    if not args.yes:
        die(f"добавь --yes, чтобы убрать платёж {p['id'][:8]} ({_money_fmt(p['amount'])}, {p['title']})")
    client.call("DELETE", f"/finance/payments/{p['id']}")
    print(f"платёж убран: {p['id'][:8]} · {p['title']}")


def cmd_money_contract_add(client, args):
    project = resolve_project(client, args.project)
    body = {"title": args.title, "kind": args.kind}
    for field, value in (("amount", args.amount), ("rate", args.rate)):
        if value is not None:
            body[field] = str(value)
    for field, value in (("signed_at", args.signed), ("start_date", args.start), ("end_date", args.end)):
        if value:
            body[field] = _due_date_only(value)
    if args.doc:
        body["doc_url"] = args.doc
    if args.note:
        body["note"] = args.note
    c = client.call("POST", f"/projects/{project['id']}/contracts", body)
    out(c, args.json, lambda c: print(
        f"договор заведён: {c['id'][:8]} · {project['code']} · {c['title']} · {c['kind']}"))


def cmd_money_contracts(client, args):
    project = resolve_project(client, args.project)
    rows = client.call("GET", f"/projects/{project['id']}/contracts")
    if args.json:
        out(rows, True, None)
        return
    if not rows:
        print(f"договоров нет: {project['code']}")
        return
    for c in rows:
        amount = _money_fmt(c["amount"]) if c.get("amount") else (
            _money_fmt(c["rate"]) + "/ед." if c.get("rate") else "сумма не задана")
        print(f"{c['id'][:8]}  {c['kind']:<9} {amount:>16}  {c['title']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pms.py", description="PMS task control CLI")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami").set_defaults(fn=cmd_whoami)
    sp = sub.add_parser("projects", help="list projects")
    sp.add_argument("--archived", action="store_true", help="include archived projects")
    sp.set_defaults(fn=cmd_projects)

    sp = sub.add_parser("project-add", help="create a project")
    sp.add_argument("--code", required=True,
                    help="short key, e.g. AXM — becomes task keys AXM-1 and the /projects/axm link; cannot be changed later")
    sp.add_argument("--name", required=True)
    sp.add_argument("--group", help="portfolio group, e.g. Клиентские")
    sp.add_argument("--goal")
    sp.set_defaults(fn=cmd_project_add)

    sp = sub.add_parser("list", help="list tasks in a project")
    sp.add_argument("--project", required=True)
    sp.add_argument("--status", help="filter by status name or category")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("show", help="task detail + comments")
    sp.add_argument("key")
    sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser("add", help="create a task")
    sp.add_argument("--project", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--desc")
    sp.add_argument("--priority", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"])
    sp.add_argument("--due", metavar="WHEN", help=DUE_HELP)
    sp.add_argument("--assignee", help="email or name")
    sp.add_argument("--attach", action="append", metavar="FILE",
                    help="прикрепить файл к задаче (можно повторять), напр. скриншот")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("edit", help="update title/description/priority/due of an existing task")
    sp.add_argument("key")
    sp.add_argument("--title")
    sp.add_argument("--desc")
    sp.add_argument("--priority", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"])
    sp.add_argument("--due", metavar="WHEN", help=DUE_HELP + ". none — снять срок")
    sp.set_defaults(fn=cmd_edit)

    sp = sub.add_parser("attach", help="attach file(s) to an existing task")
    sp.add_argument("key")
    sp.add_argument("files", nargs="+", metavar="FILE")
    sp.set_defaults(fn=cmd_attach)

    sp = sub.add_parser("comment", help="add a comment")
    sp.add_argument("key")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_comment)

    sp = sub.add_parser("status", help="change status by name/category")
    sp.add_argument("key")
    sp.add_argument("status")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("done", help="move task to a DONE status")
    sp.add_argument("key")
    sp.set_defaults(fn=cmd_done)

    sp = sub.add_parser("assign", help="set assignee")
    sp.add_argument("key")
    sp.add_argument("--to", required=True, help="email or name")
    sp.set_defaults(fn=cmd_assign)

    sp = sub.add_parser("members", help="list project members")
    sp.add_argument("--project", required=True)
    sp.set_defaults(fn=cmd_members)

    sp = sub.add_parser("member-add", help="give a user access to a project (or to all of them)")
    sp.add_argument("--user", required=True, help="email or name")
    sp.add_argument("--project", help="one project; omit to apply to every project")
    sp.add_argument("--role", default="MEMBER", choices=PROJECT_ROLES,
                    help="role inside the project (default MEMBER)")
    sp.add_argument("--archived", action="store_true",
                    help="with no --project: cover archived projects too")
    sp.set_defaults(fn=cmd_member_add)

    sp = sub.add_parser("member-rm", help="revoke a user's access to a project (or to all)")
    sp.add_argument("--user", required=True, help="email or name")
    sp.add_argument("--project", help="one project; omit to apply to every project")
    sp.add_argument("--archived", action="store_true")
    sp.add_argument("--yes", action="store_true", help="required when no --project is given")
    sp.set_defaults(fn=cmd_member_rm)

    sp = sub.add_parser("rm", help="delete a task")
    sp.add_argument("key")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(fn=cmd_rm)

    # ---- money: деньги проектов -------------------------------------------
    sp = sub.add_parser("money", help="деньги: платежи, счета, договоры")
    msub = sp.add_subparsers(dest="money_cmd", required=True)

    m = msub.add_parser("list", help="платежи проекта или всего портфеля")
    m.add_argument("--project", help="код проекта; без него — все проекты")
    m.add_argument("--status", choices=["EXPECTED", "INVOICED", "PAID", "CANCELLED"])
    m.add_argument("--all", action="store_true", help="включая оплаченные")
    m.set_defaults(fn=cmd_money_list)

    m = msub.add_parser("calendar", help="календарь платежей и прогноз")
    m.add_argument("--weeks", type=int, default=4, help="горизонт прогноза, недель")
    m.set_defaults(fn=cmd_money_calendar)

    m = msub.add_parser("add", help="завести ожидаемый платёж")
    m.add_argument("--project", required=True)
    m.add_argument("--title", required=True)
    m.add_argument("--amount", required=True)
    m.add_argument("--kind", default="MILESTONE",
                   choices=["PREPAY", "MILESTONE", "RETAINER", "HOURLY", "EXTRA"])
    m.add_argument("--due", metavar="WHEN", help=DUE_HELP)
    m.add_argument("--initiative", help="id вехи, к которой привязан платёж")
    m.add_argument("--contract", help="id договора")
    m.add_argument("--invoice", help="номер счёта, если уже выставлен")
    m.add_argument("--doc", help="ссылка на документ в Drive")
    m.add_argument("--note")
    m.set_defaults(fn=cmd_money_add)

    m = msub.add_parser("invoice", help="отметить, что счёт выставлен")
    m.add_argument("id", help="первые знаки id платежа")
    m.add_argument("--no", help="номер счёта")
    m.add_argument("--date", help="дата выставления (по умолчанию сегодня)")
    m.add_argument("--due", help="срок оплаты")
    m.set_defaults(fn=cmd_money_invoice)

    m = msub.add_parser("paid", help="отметить оплату")
    m.add_argument("id")
    m.add_argument("--date", help="дата оплаты (по умолчанию сегодня)")
    m.add_argument("--amount", help="если пришла другая сумма")
    m.add_argument("--act", help="номер акта")
    m.set_defaults(fn=cmd_money_paid)

    m = msub.add_parser("rm", help="убрать платёж (мягко, история остаётся)")
    m.add_argument("id")
    m.add_argument("--yes", action="store_true")
    m.set_defaults(fn=cmd_money_rm)

    m = msub.add_parser("contracts", help="договоры проекта")
    m.add_argument("--project", required=True)
    m.set_defaults(fn=cmd_money_contracts)

    m = msub.add_parser("contract-add", help="завести договор")
    m.add_argument("--project", required=True)
    m.add_argument("--title", required=True)
    m.add_argument("--kind", default="FIXED", choices=["FIXED", "MILESTONE", "RETAINER", "HOURLY"])
    m.add_argument("--amount")
    m.add_argument("--rate", help="ставка за час или месяц")
    m.add_argument("--signed", help="дата подписания")
    m.add_argument("--start")
    m.add_argument("--end")
    m.add_argument("--doc", help="ссылка на документ в Drive")
    m.add_argument("--note")
    m.set_defaults(fn=cmd_money_contract_add)

    return p


def main() -> None:
    args = build_parser().parse_args()
    client = Client(_load_config())
    try:
        args.fn(client, args)
    except ApiError as e:
        die(str(e))


if __name__ == "__main__":
    main()
