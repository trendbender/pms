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
    pms.py project-add --code AXM --name "Axiom Charter" --group "Клиентские" --site axiom.ru
    pms.py project-edit SSK --site https://skolkoskolko.ru   # пути /lk/… в задачах → ссылки на сайт
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
    pms.py lead enable --project KL --preset sales
    pms.py lead add --project KL --title "Kwork #3267289" --source kwork --external 3267289
    pms.py lead stage KL-L-1 "Переговоры"
    pms.py lead stats --project KL --from 2026-10-01
    pms.py lead token-add --project ORD --label "UBO adapter" --save ~/.config/ord-lead.token
    pms.py lead ingest order.json --token-file ~/.config/ord-lead.token

Add --json to most read commands for machine output.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from decimal import Decimal
import json
import html
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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
        print(f"{p['code']:<6} {p['name']}  ·  {p.get('group_name') or '—'}  [{p['status']}/{p['health']}]"
              + (f"  {p['site_url']}" if p.get("site_url") else ""))
        for p in ps
    ])


def cmd_project_add(client, args):
    """Create a project. The code is permanent: task keys and links hang off it."""
    body = {"name": args.name, "code": args.code.strip().upper()}
    if args.group:
        body["group_name"] = args.group
    if args.goal:
        body["goal"] = args.goal
    if args.site:
        body["site_url"] = args.site
    p = client.call("POST", "/projects", body)

    def human(p):
        print(f"создан проект {p['code']} — {p['name']} · {p.get('group_name') or '—'}")
        print(f"{client.web_base}/projects/{p['code'].lower()}")

    out(p, args.json, human)


def cmd_project_edit(client, args):
    """Поменять поля проекта. Сайт (--site) нужен для ссылок: путь «/lk/…» в задаче
    или комментарии PMS сохраняет абсолютным URL на этот сайт; --site none — снять."""
    project = resolve_project(client, args.code)
    body = {}
    if args.site is not None:
        body["site_url"] = "" if args.site.lower() in ("none", "-") else args.site
    if args.name:
        body["name"] = args.name
    if args.group:
        body["group_name"] = args.group
    if not body:
        sys.exit("нечего менять: --site / --name / --group")
    p = client.call("PATCH", f"/projects/{project['id']}", body)
    out(p, args.json, lambda p: print(
        f"{p['code']} — {p['name']} · {p.get('group_name') or '—'} · сайт: {p.get('site_url') or '—'}"))


def cmd_list(client, args):
    project = resolve_project(client, args.project)
    tasks = client.call("GET", f"/projects/{project['id']}/tasks")
    if args.status:
        low = args.status.lower()
        tasks = [t for t in tasks if low in (t.get("status_name") or "").lower()
                 or low == (t.get("status_category") or "").lower()]
    if getattr(args, "assignee", None):
        who_u = resolve_user(client, args.assignee)
        tasks = [t for t in tasks if t.get("assignee_id") == who_u["id"]]
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


def cmd_inbox(client, args):
    """Очередь исполнителя по всем проектам (конвейер ИИ: conventions/ai-pipeline.md)."""
    user = resolve_user(client, args.assignee)
    projects = client.call("GET", "/projects")
    low = (args.status or "").lower()
    rows = []
    for p in sorted(projects, key=lambda p: p["code"]):
        for t in client.call("GET", f"/projects/{p['id']}/tasks"):
            if t.get("assignee_id") != user["id"]:
                continue
            cat = (t.get("status_category") or "").lower()
            name = (t.get("status_name") or "").lower()
            if low and not (low in name or low == cat):
                continue
            if not low and cat == "done":
                continue
            t["project_code"] = p["code"]
            t["url"] = client.task_url(t["key"])
            rows.append(t)
    prio = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
    rows.sort(key=lambda t: (prio.get(t.get("priority"), 9), t.get("due_at") or "9999", t["key"]))

    def render(ts):
        print(f"# inbox {user['name']} <{user.get('email', '')}> — {len(ts)} задач")
        for t in ts:
            due = fmt_due(t.get("due_at"))
            due = f" ⏰{due}" if due else ""
            print(f"{t['key']:<8} [{t.get('status_name', '?'):<12}] {t['priority']:<8}{due}  {t['title']}")
            print(f"         {t['url']}")
    out(rows, args.json, render)


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


BRIEFS = "/srv/projects/seo-engine/briefs.py"
AI_PROVIDERS = ("antigravity", "chatgpt", "claude-reviewer", "opencode")


def brief_provider(assignee):
    a = (assignee or "").strip().lower().split("@")[0]
    return next((p for p in AI_PROVIDERS if a == p or a.startswith(p)), "any")


def render_brief(args):
    """Описание задачи из хранимого шаблона ТЗ (seo-engine/briefs): шаблон + блоки + уроки провайдера, --desc дописывается."""
    import subprocess
    cmd = ["python3", BRIEFS, "render", args.brief, "--provider", brief_provider(args.assignee),
           "--param", f"title={args.title}"] + [x for p in (args.param or []) for x in ("--param", p)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"briefs.py render {args.brief}: {r.stderr.strip() or r.stdout.strip()}")
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    return r.stdout + (f"\n## Дополнительно к шаблону\n\n{args.desc}\n" if args.desc else "")


def cmd_add(client, args):
    project = resolve_project(client, args.project)
    body = {"project_id": project["id"], "title": args.title}
    if args.brief:
        args.desc = render_brief(args)
    elif brief_provider(args.assignee) != "any":
        print(f"ВНИМАНИЕ: задача ИИ-исполнителю без шаблона ТЗ. Шаблоны: python3 {BRIEFS} list, "
              f"постановка: --brief ШАБЛОН --param k=v (канон conventions/ai-briefs.md)", file=sys.stderr)
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
    if args.brief:
        import subprocess
        d = next((p.split("=", 1)[1] for p in (args.param or []) if p.startswith("dir=")), "")
        r = subprocess.run(["python3", BRIEFS, "use", args.brief, "--task", task["key"],
                            "--provider", brief_provider(args.assignee), "--dir", d], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ВНИМАНИЕ: применение шаблона не записано: {r.stderr.strip()}", file=sys.stderr)

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
    body = {"status_id": st["id"]}
    # Правило 8: блокировка видна с причиной, иначе в роадмапе стоит пункт без объяснения.
    if st["category"] == "BLOCKED":
        if not args.reason:
            die("статус категории BLOCKED требует --reason: что именно держит задачу")
        body["reason"] = args.reason
    t = client.call("PATCH", f"/tasks/{task['id']}/status", body)
    out(t, args.json, lambda t: print(f"{t['key']} → {t.get('status_name')}"
        + (f" ({t['blocked_reason']})" if t.get("blocked_reason") else "")
        + f"\n{client.task_url(t['key'])}"))


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


# --------------------------------------------------------------------------- #
# Лиды (модуль включается на проекте: pms.py lead enable)
# --------------------------------------------------------------------------- #


def lead_url(client: Client, key: str) -> str:
    return f"{client.web_base}/l/{key.lower()}"


def resolve_lead(client: Client, key: str) -> dict:
    return client.call("GET", f"/leads/by-key/{key.strip()}")


def _parse_fields(pairs: list[str] | None) -> dict:
    data = {}
    for pair in pairs or []:
        if "=" not in pair:
            die(f"--field expects key=value, got: {pair}")
        k, v = pair.split("=", 1)
        data[k.strip()] = v
    return data


def _lead_line(ld: dict) -> str:
    amount = f" · {Decimal(ld['amount']):,.0f} {ld['currency']}".replace(",", " ") if ld.get("amount") else ""
    who = f" · {ld['contact_name']}" if ld.get("contact_name") and ld["contact_name"] != ld["title"] else ""
    return f"{ld['key']:<10} [{ld['stage_name']:<18}] {ld['source']:<8}{amount}{who}  {ld['title']}"


# ---- roadmap: роадмап проекта -------------------------------------------- #

_RM_STATUS_RU = {
    "DRAFT": "черновик",
    "AGREED": "согласован",
    "ACTIVE": "в работе",
    "COMPLETED": "закрыт",
    "CANCELLED": "отменён",
}


def _roadmap_call(client, method, path, body=None):
    """Модуль роадмапов может быть ещё не выкачен: 404 объясняем словами."""
    try:
        return client.call(method, path, body)
    except ApiError as e:
        if e.status == 404 and "roadmap" in path:
            die("модуль роадмапов не отвечает на этом инстансе PMS (не выкачен на прод?)")
        raise


def _roadmap_of(client, args):
    """Роадмап по --id или текущий роадмап проекта (--project)."""
    if getattr(args, "id", None):
        return _roadmap_call(client, "GET", f"/roadmaps/{args.id}")
    if not getattr(args, "project", None):
        die("нужен --project CODE или --id роадмапа")
    project = resolve_project(client, args.project)
    try:
        return client.call("GET", f"/projects/{project['id']}/roadmap")
    except ApiError as e:
        if e.status == 404:
            die(f"у проекта {project['code']} нет роадмапа: pms.py roadmap add --project "
                f"{project['code']} --title \"Месяц 1\" --start 2026-11-01")
        raise


def _rm_period(r) -> str:
    start = _rm_day(r["period_start"])
    return f"{start} - {_rm_day(r['period_end'])}" if r.get("period_end") else f"с {start}"


def _rm_day(value) -> str:
    if not value:
        return "—"
    d = str(value)[:10].split("-")
    return f"{d[2]}.{d[1]}.{d[0]}" if len(d) == 3 else str(value)


def _rm_body(args, *, creating: bool) -> dict:
    body = {}
    if getattr(args, "title", None):
        body["title"] = args.title
    if getattr(args, "start", None):
        body["period_start"] = _due_date_only(args.start)
    if getattr(args, "end", None):
        body["period_end"] = _due_date_only(args.end)
    if getattr(args, "status", None):
        body["status"] = args.status
    for field, attr in (
        ("goal", "goal"),
        ("scope_note", "scope"),
        ("decision_ref", "decision"),
        ("plan_url", "plan_url"),
        ("report_url", "report_url"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            body[field] = "" if value.lower() in ("none", "-") else value
    if getattr(args, "agreed", None):
        body["agreed_on"] = _due_date_only(args.agreed)
    if creating and not body.get("period_start"):
        die("нужен --start: роадмап без периода не роадмап")
    return body


def cmd_roadmap_list(client, args):
    if args.project:
        project = resolve_project(client, args.project)
        path = f"/projects/{project['id']}/roadmaps"
        if args.archived:
            path += "?include_archived=true"
        rows = _roadmap_call(client, "GET", path)
    else:
        rows = _roadmap_call(client, "GET", "/roadmap")
    if args.json:
        out(rows, True, None)
        return
    if not rows:
        print("роадмапов нет")
        return
    for r in rows:
        done = f"{r['done_count']}/{r['task_count']}"
        tail = f" · метрики {r['metric_reached_count']}/{r['metric_count']}" if r["metric_count"] else ""
        print(f"{(r.get('project_code') or '—'):<6} {_rm_period(r):<23} {r['title']}  "
              f"[{_RM_STATUS_RU.get(r['status'], r['status'])}] пункты {done}{tail}")


def cmd_roadmap_show(client, args):
    r = _roadmap_of(client, args)
    if args.json:
        out(r, True, None)
        return
    print(f"{r['title']} — {r.get('project_name') or ''} ({r.get('project_code') or '—'})")
    print(f"{_rm_period(r)} · {_RM_STATUS_RU.get(r['status'], r['status'])} · "
          f"пункты {r['done_count']}/{r['task_count']}"
          + (f", просрочено {r['overdue_count']}" if r["overdue_count"] else "")
          + (f", заблокировано {r['blocked_count']}" if r["blocked_count"] else ""))
    if r.get("goal"):
        print(f"Цель: {r['goal']}")
    if r.get("scope_note"):
        print(f"Согласовано: {r['scope_note']}")
    if r.get("report_url"):
        print(f"Отчёт: {r['report_url']}")
    for wave in r.get("waves", []):
        print(f"\n— {wave['name']} · до {_rm_day(wave.get('due_date'))} · "
              f"{wave['done_count']}/{wave['task_count']} —")
        for t in wave.get("tasks", []):
            mark = "✓" if t["status_category"] == "DONE" else ("!" if t["is_blocked"] else " ")
            who = f" · {t['assignee_name']}" if t.get("assignee_name") else ""
            print(f"  {mark} {t['key']:<9} {t['title']}{who} · {_rm_day(t.get('due_at'))}")
    if r.get("metrics"):
        print("\n— было → цель → сейчас —")
        for m in r["metrics"]:
            mark = "✓" if m.get("reached_on") else " "
            print(f"  {mark} {m['name']}: {m.get('baseline') or '—'} → {m.get('target') or '—'}"
                  f" → {m.get('current') or 'пока нет'}  [{m['id'][:8]}]")
    if r.get("waiting") or r.get("open_decisions"):
        print("\n— держит роадмап —")
        for t in r.get("waiting", []):
            print(f"  ! {t['key']} {t['title']}: {t.get('blocked_reason') or 'без причины'}")
        for d in r.get("open_decisions", []):
            print(f"  ? {d['ref']} {d['question']}")


def cmd_roadmap_add(client, args):
    project = resolve_project(client, args.project)
    body = _rm_body(args, creating=True)
    r = _roadmap_call(client, "POST", f"/projects/{project['id']}/roadmaps", body)
    print(f"создан роадмап {r['title']} ({_rm_period(r)}) для {project['code']}")
    print(f"{client.web_base}/projects/{project['code'].lower()}/roadmap")


def cmd_roadmap_edit(client, args):
    r = _roadmap_of(client, args)
    if args.archive:
        _roadmap_call(client, "POST", f"/roadmaps/{r['id']}/archive")
        print(f"роадмап {r['title']} в архиве")
        return
    body = _rm_body(args, creating=False)
    if not body:
        die("нечего менять")
    r = _roadmap_call(client, "PATCH", f"/roadmaps/{r['id']}", body)
    print(f"{r['title']} · {_rm_period(r)} · {_RM_STATUS_RU.get(r['status'], r['status'])}")


def cmd_roadmap_wave_add(client, args):
    r = _roadmap_of(client, args)
    body = {"name": args.name, "roadmap_id": r["id"]}
    if args.due:
        body["due_date"] = _due_date_only(args.due)
    if args.desc:
        body["description"] = args.desc
    wave = client.call("POST", f"/projects/{r['project_id']}/initiatives", body)
    print(f"волна «{wave['name']}» в роадмапе {r['title']}")
    for key in [k.strip() for k in (args.tasks or "").split(",") if k.strip()]:
        task = resolve_task(client, key)
        client.call("PATCH", f"/tasks/{task['id']}", {"initiative_id": wave["id"]})
        print(f"  + {task['key']} {task['title']}")


def cmd_roadmap_metric_add(client, args):
    r = _roadmap_of(client, args)
    body = {"name": args.name}
    for field, attr in (
        ("baseline", "baseline"),
        ("target", "target"),
        ("current", "current"),
        ("source", "source"),
    ):
        if getattr(args, attr, None):
            body[field] = getattr(args, attr)
    for field, attr in (
        ("baseline_on", "baseline_on"),
        ("measured_on", "measured_on"),
        ("reached_on", "reached_on"),
    ):
        if getattr(args, attr, None):
            body[field] = _due_date_only(getattr(args, attr))
    m = _roadmap_call(client, "POST", f"/roadmaps/{r['id']}/metrics", body)
    print(f"метрика {m['name']}: {m.get('baseline') or '—'} → {m.get('target') or '—'}  [{m['id']}]")


def cmd_roadmap_metric_set(client, args):
    body = {}
    for field, attr in (
        ("current", "current"),
        ("baseline", "baseline"),
        ("target", "target"),
        ("source", "source"),
        ("name", "name"),
    ):
        if getattr(args, attr, None):
            body[field] = getattr(args, attr)
    for field, attr in (
        ("measured_on", "measured_on"),
        ("reached_on", "reached_on"),
        ("baseline_on", "baseline_on"),
    ):
        if getattr(args, attr, None):
            body[field] = _due_date_only(getattr(args, attr))
    if not body:
        die("нечего менять: --current / --target / --reached-on …")
    m = _roadmap_call(client, "PATCH", f"/roadmap-metrics/{args.metric}", body)
    print(f"{m['name']}: {m.get('baseline') or '—'} → {m.get('target') or '—'} → "
          f"{m.get('current') or 'пока нет'}"
          + (f" ✓ {_rm_day(m['reached_on'])}" if m.get("reached_on") else ""))


_RM_CSS = """
  body{background:#fff;color:#1d2330;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;margin:0;padding:24px 16px}
  main{max-width:1060px;margin:0 auto}
  h1{font-size:24px;margin:0 0 4px}
  h2{font-size:18px;margin:32px 0 10px;padding-top:12px;border-top:1px solid #e3e6ec}
  .sub{color:#5b6475;margin:0 0 18px}
  table{border-collapse:collapse;width:100%;margin:8px 0 4px;font-size:14px}
  th,td{border:1px solid #e3e6ec;padding:6px 8px;text-align:left;vertical-align:top}
  th{background:#f5f7fa;font-weight:600}
  .wrap{overflow-x:auto}
  a{color:#1f5fbf}
  .tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:10px;margin:1px 2px 1px 0;white-space:nowrap}
  .done{background:#e6f6ec;color:#1e6b3a}.work{background:#e8f0fe;color:#1a4a9c}
  .block{background:#fde8e8;color:#9b1c1c}.wait{background:#eef0f3;color:#3b4252}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:12px 0}
  .tile{border:1px solid #e3e6ec;border-radius:8px;padding:10px 12px}
  .tile b{display:block;font-size:20px}
  .tile span{color:#5b6475;font-size:13px}
  ul{margin:6px 0 6px 20px;padding:0}
  .note{background:#f7f8fa;border-left:3px solid #9aa4b5;padding:8px 12px;margin:10px 0}
  .foot{color:#5b6475;font-size:13px;margin-top:28px}
"""


def _rm_esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _rm_task_row(client, t) -> str:
    """Строка пункта плана: ключ ссылкой, что сделать, кто, срок, состояние."""
    category = t.get("status_category")
    if category == "DONE":
        state = '<span class="tag done">сделано</span>'
    elif t.get("is_blocked"):
        reason = _rm_esc(t.get("blocked_reason") or "")
        state = f'<span class="tag block">держит</span> {reason}'
    elif category in ("REVIEW", "CHANGES_REQUIRED"):
        state = f'<span class="tag wait">{_rm_esc(t.get("status_name"))}</span>'
    elif category in ("IN_PROGRESS", "READY"):
        state = f'<span class="tag work">{_rm_esc(t.get("status_name"))}</span>'
    else:
        state = _rm_esc(t.get("status_name"))
    return (
        f'<tr><td><a href="{client.task_url(t["key"])}">{_rm_esc(t["key"])}</a></td>'
        f"<td>{_rm_esc(t['title'])}</td>"
        f"<td>{_rm_esc(t.get('assignee_name') or '—')}</td>"
        f"<td>{_rm_day(t.get('due_at'))}</td><td>{state}</td></tr>"
    )


def _rm_decision_url(client, project_code: str, ref: str) -> str:
    """Решение из реестра: /d/<код проекта>-<номер>, кросс-проектные — как есть."""
    ref = (ref or "").strip()
    if ":" in ref:
        registry, number = ref.split(":", 1)
        slug = f"{registry}-{number}" if registry != "_global" else f"g-{number}"
    else:
        slug = f"{project_code}-{ref}"
    return f"{client.web_base}/d/{slug.lower()}"


def _roadmap_html(client, r) -> str:
    code = (r.get("project_code") or "").lower()
    title = f"{r.get('project_name') or code}: {r['title']}"
    sub = [_rm_period(r), _RM_STATUS_RU.get(r["status"], r["status"])]
    if r.get("scope_note"):
        sub.append(_rm_esc(r["scope_note"]))
    if r.get("decision_ref"):
        url = _rm_decision_url(client, code, r["decision_ref"])
        sub.append(f'решение <a href="{url}">{_rm_esc(r["decision_ref"])}</a>')

    parts = [
        "<!doctype html>", '<html lang="ru">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_rm_esc(title)}</title>", f"<style>{_RM_CSS}</style>", "</head>",
        "<body><main>", f"<h1>{_rm_esc(title)}</h1>",
        f'<p class="sub">{" · ".join(sub)}</p>',
    ]
    if r.get("goal"):
        parts.append(f'<p class="note">{_rm_esc(r["goal"])}</p>')

    tiles = [
        (f"{r['done_count']}/{r['task_count']}", "пунктов плана сделано"),
        (str(r["wave_count"]), "волн в периоде"),
    ]
    if r["metric_count"]:
        tiles.append((
            f"{r['metric_reached_count']}/{r['metric_count']}",
            "метрик «было → цель» достигнуто",
        ))
    if r.get("period_end"):
        tiles.append((_rm_day(r["period_end"]), "конец периода, отчёт со сверкой по пунктам"))
    if r["blocked_count"] or r["overdue_count"]:
        tiles.append((
            f"{r['blocked_count']} + {r['overdue_count']}",
            "заблокировано и просрочено",
        ))
    parts.append('<div class="tiles">')
    for big, small in tiles:
        parts.append(f'<div class="tile"><b>{_rm_esc(big)}</b><span>{_rm_esc(small)}</span></div>')
    parts.append("</div>")

    for wave in r.get("waves", []):
        head = f"{wave['name']}"
        if wave.get("due_date"):
            head += f" · до {_rm_day(wave['due_date'])}"
        head += f" · {wave['done_count']}/{wave['task_count']}"
        parts.append(f"<h2>{_rm_esc(head)}</h2>")
        if wave.get("description"):
            parts.append(f"<p>{_rm_esc(wave['description'])}</p>")
        if not wave.get("tasks"):
            parts.append("<p>пунктов пока нет</p>")
            continue
        parts.append('<div class="wrap"><table>')
        parts.append("<tr><th>Задача</th><th>Что</th><th>Исполнитель</th><th>Срок</th>"
                     "<th>Состояние</th></tr>")
        parts.extend(_rm_task_row(client, t) for t in wave["tasks"])
        parts.append("</table></div>")

    if r.get("metrics"):
        parts.append("<h2>Было → цель → стало</h2>")
        parts.append('<div class="wrap"><table>')
        parts.append("<tr><th>Пункт</th><th>Было</th><th>Цель</th><th>Сейчас</th>"
                     "<th>Чем снято</th></tr>")
        for m in r["metrics"]:
            was = _rm_esc(m.get("baseline") or "—")
            if m.get("baseline_on"):
                was += f' <span class="tag wait">{_rm_day(m["baseline_on"])}</span>'
            now = _rm_esc(m.get("current") or "пока нет")
            if m.get("reached_on"):
                now += ' <span class="tag done">цель</span>'
            source = _rm_esc(m.get("source") or "—")
            if m.get("measured_on"):
                source += f", {_rm_day(m['measured_on'])}"
            parts.append(f"<tr><td>{_rm_esc(m['name'])}</td><td>{was}</td>"
                         f"<td>{_rm_esc(m.get('target') or '—')}</td><td>{now}</td>"
                         f"<td>{source}</td></tr>")
        parts.append("</table></div>")

    if r.get("waiting") or r.get("open_decisions"):
        parts.append("<h2>Нужно от владельца и клиента</h2><ul>")
        for t in r.get("waiting", []):
            parts.append(
                f'<li><a href="{client.task_url(t["key"])}">{_rm_esc(t["key"])}</a>: '
                f"{_rm_esc(t['title'])} — {_rm_esc(t.get('blocked_reason') or 'без причины')}</li>"
            )
        for d in r.get("open_decisions", []):
            url = _rm_decision_url(client, code, d["ref"])
            parts.append(f'<li><a href="{url}">{_rm_esc(d["ref"])}</a>: '
                         f"{_rm_esc(d['question'])}</li>")
        parts.append("</ul>")

    if r.get("plan_url"):
        parts.append(f'<p class="foot">Исходный план: '
                     f'<a href="{_rm_esc(r["plan_url"])}">{_rm_esc(r["plan_url"])}</a></p>')
    board = f"{client.web_base}/projects/{code}/roadmap" if code else client.web_base
    parts.append(
        f'<p class="foot">Собрано из PMS {_rm_day(_dt.date.today().isoformat())} — '
        f'правки вносятся в задачи и метрики роадмапа, отчёт пересобирается: '
        f'<a href="{board}">{board}</a></p>'
    )
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def cmd_roadmap_report(client, args):
    """Отчёт роадмапа — рендер данных PMS, а не отдельный рукописный файл.

    Поэтому сверка по пунктам всегда совпадает с доской: правки вносятся в
    задачи и метрики, отчёт пересобирается этой же командой и выкладывается
    скиллом publish-report.
    """
    r = _roadmap_of(client, args)
    page = _roadmap_html(client, r)
    code = (r.get("project_code") or "roadmap").lower()
    path = Path(args.out) if args.out else Path(
        f"reports/{code}-roadmap-{_dt.date.today().isoformat()}.html"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    print(f"{path}  ({len(page)} байт)")
    print("выложить: bash ~/.claude/skills/publish-report/publish.sh "
          f"{path} {code}")


def cmd_lead_list(client, args):
    project = resolve_project(client, args.project)
    q = []
    if args.stage:
        settings = client.call("GET", f"/projects/{project['id']}/leads/settings")
        st = next((s for s in settings["stages"] if s["name"].lower() == args.stage.lower()), None)
        if st is None:
            die(f"unknown stage: {args.stage}")
        q.append(f"stage_id={st['id']}")
    if args.category:
        q.append(f"category={args.category}")
    if args.source:
        q.append(f"source={urllib.parse.quote(args.source)}")
    if args.q:
        q.append(f"q={urllib.parse.quote(args.q)}")
    path = f"/projects/{project['id']}/leads" + (f"?{'&'.join(q)}" if q else "")
    leads = client.call("GET", path)

    def render(ls):
        print(f"# {project['code']} лиды — {len(ls)}")
        for ld in ls:
            print(_lead_line(ld))
            print(f"           {lead_url(client, ld['key'])}")

    out(leads, args.json, render)


def cmd_lead_add(client, args):
    project = resolve_project(client, args.project)
    body = {"title": args.title, "source": args.source}
    for attr, field in (("external", "external_id"), ("contact", "contact_name"),
                        ("phone", "phone"), ("email", "email"), ("amount", "amount"),
                        ("url", "source_url")):
        if getattr(args, attr):
            body[field] = getattr(args, attr)
    if args.field:
        body["data"] = _parse_fields(args.field)
    if args.stage:
        settings = client.call("GET", f"/projects/{project['id']}/leads/settings")
        st = next((s for s in settings["stages"] if s["name"].lower() == args.stage.lower()), None)
        if st is None:
            die(f"unknown stage: {args.stage}")
        body["stage_id"] = st["id"]
    if args.owner:
        body["owner_id"] = resolve_user(client, args.owner)["id"]
    ld = client.call("POST", f"/projects/{project['id']}/leads", body)
    out(ld, args.json, lambda ld: print(f"создан {ld['key']}: {ld['title']}\n{lead_url(client, ld['key'])}"))


def cmd_lead_show(client, args):
    ld = resolve_lead(client, args.key)
    events = client.call("GET", f"/leads/{ld['id']}/events")
    ld["events"] = events

    def human(ld):
        print(f"{ld['key']} — {ld['title']}")
        print(lead_url(client, ld["key"]))
        print(f"этап: {ld['stage_name']} ({ld['stage_category']}) · источник: {ld['source']}"
              + (f" #{ld['external_id']}" if ld.get("external_id") else ""))
        for label, k in (("контакт", "contact_name"), ("телефон", "phone"), ("email", "email"),
                         ("сумма", "amount"), ("ссылка", "source_url"), ("причина", "lost_reason"),
                         ("задача", "task_key")):
            if ld.get(k):
                print(f"{label}: {ld[k]}")
        if ld.get("data"):
            print("поля:")
            for k, v in ld["data"].items():
                print(f"  {k}: {v}")
        print(f"\nЖурнал ({len(events)}):")
        for e in events:
            d = e.get("data") or {}
            if e["action"] == "comment":
                info = d.get("text", "")
            elif e["action"] == "stage.changed":
                info = f"{d.get('from')} → {d.get('to')}"
            else:
                info = ", ".join(f"{k}={v}" for k, v in d.items())
            print(f"  · {e['created_at'][:16].replace('T', ' ')} {e['action']}: {info}")

    out(ld, args.json, human)


def cmd_lead_stage(client, args):
    ld = resolve_lead(client, args.key)
    body = {"stage": args.stage}
    if args.reason:
        body["lost_reason"] = args.reason
    ld = client.call("PATCH", f"/leads/{ld['id']}/stage", body)
    out(ld, args.json, lambda ld: print(f"{ld['key']} → {ld['stage_name']}\n{lead_url(client, ld['key'])}"))


def cmd_lead_edit(client, args):
    ld = resolve_lead(client, args.key)
    body = {}
    for attr, field in (("title", "title"), ("contact", "contact_name"), ("phone", "phone"),
                        ("email", "email"), ("amount", "amount"), ("url", "source_url")):
        if getattr(args, attr) is not None:
            body[field] = getattr(args, attr)
    if args.field:
        body["data"] = _parse_fields(args.field)
    if args.owner:
        body["owner_id"] = resolve_user(client, args.owner)["id"]
    if not body:
        die("nothing to change")
    ld = client.call("PATCH", f"/leads/{ld['id']}", body)
    out(ld, args.json, lambda ld: print(f"{ld['key']} обновлён\n{lead_url(client, ld['key'])}"))


def cmd_lead_comment(client, args):
    ld = resolve_lead(client, args.key)
    c = client.call("POST", f"/leads/{ld['id']}/comments", {"text": args.text})
    out(c, args.json, lambda _: print(f"комментарий добавлен к {ld['key']}\n{lead_url(client, ld['key'])}"))


def cmd_lead_task(client, args):
    ld = resolve_lead(client, args.key)
    body = {"priority": args.priority}
    if args.title:
        body["title"] = args.title
    if args.to:
        body["assignee_id"] = resolve_user(client, args.to)["id"]
    ld = client.call("POST", f"/leads/{ld['id']}/task", body)
    out(ld, args.json, lambda ld: print(
        f"{ld['key']} → задача {ld['task_key']}\n{client.task_url(ld['task_key'])}"))


def cmd_lead_stats(client, args):
    project = resolve_project(client, args.project)
    q = []
    def period(value: str, end: bool) -> str:
        # голая дата: «с» = начало дня, «по» = конец дня (по Москве)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return f"{value.strip()}T{'23:59:59' if end else '00:00:00'}+03:00"
        return parse_due(value)

    if args.date_from:
        q.append(f"from={urllib.parse.quote(period(args.date_from, False))}")
    if args.date_to:
        q.append(f"to={urllib.parse.quote(period(args.date_to, True))}")
    s = client.call("GET", f"/projects/{project['id']}/leads/stats" + (f"?{'&'.join(q)}" if q else ""))

    def human(s):
        rate = f"{s['win_rate'] * 100:.0f}%" if s.get("win_rate") is not None else "—"
        print(f"# {project['code']} лиды {s['period_from'][:10]} … {s['period_to'][:10]}")
        print(f"всего {s['total']} · в работе {s['open']} · выиграно {s['won']} · проиграно {s['lost']}"
              f" · win rate {rate}")
        print(f"в работе на {s['open_amount']} · выиграно на {s['won_amount']}"
              + (f" · до закрытия в среднем {s['avg_days_to_close']} дн." if s.get("avg_days_to_close") else ""))
        print("\nЭтапы (сейчас / побывали):")
        for st in s["stages"]:
            print(f"  {st['name']:<22} {st['count']:>4} / {st['reached']:<4} {st['category']}")
        print("\nИсточники (всего / выиграно):")
        for src in s["sources"]:
            print(f"  {src['source']:<12} {src['count']:>4} / {src['won']}")

    out(s, args.json, human)


def cmd_lead_enable(client, args):
    project = resolve_project(client, args.project)
    s = client.call("POST", f"/projects/{project['id']}/leads/enable", {"preset": args.preset})
    out(s, args.json, lambda s: print(
        f"лиды включены в {project['code']}: этапов {len(s['stages'])}, полей {len(s['fields'])}\n"
        + " → ".join(st["name"] for st in s["stages"])))


def cmd_lead_tokens(client, args):
    project = resolve_project(client, args.project)
    s = client.call("GET", f"/projects/{project['id']}/leads/settings")
    toks = s.get("tokens") or []
    out(toks, args.json, lambda ts: [
        print(f"{t['id'][:8]}  {t['prefix']}…  {t['label']:<24} "
              f"{'отозван' if t.get('revoked_at') else 'активен'}"
              f"{'  · последний раз ' + t['last_used_at'][:16] if t.get('last_used_at') else ''}")
        for t in ts] or print("ключей нет"))


def cmd_lead_token_add(client, args):
    project = resolve_project(client, args.project)
    t = client.call("POST", f"/projects/{project['id']}/lead-tokens", {"label": args.label})
    if args.save:
        path = Path(args.save).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(t["token"] + "\n")
        os.chmod(path, 0o600)
        print(f"ключ «{t['label']}» ({t['prefix']}…) сохранён в {path} (chmod 600); значение больше не показывается")
        return
    out(t, args.json, lambda t: print(
        f"ключ «{t['label']}»: {t['token']}\nсохраните его сейчас: повторно значение не показывается"))


def cmd_lead_ingest(_client, args):
    """Приём по ключу проекта, без логина пользователя (для скриптов и адаптеров)."""
    token = os.environ.get("PMS_LEAD_TOKEN")
    if args.token_file:
        token = Path(args.token_file).expanduser().read_text().strip()
    if not token:
        die("need --token-file FILE or PMS_LEAD_TOKEN")
    api = args.api
    if not api:
        try:
            api = json.loads(Path(CONFIG_PATH).read_text()).get("api_base")
        except (OSError, ValueError):
            api = None
    if not api:
        die("need --api https://pms.example.com/api (or api_base in the config)")
    body = json.loads(Path(args.json_file).read_text()) if args.json_file != "-" else json.load(sys.stdin)
    req = urllib.request.Request(
        f"{api.rstrip('/')}/ingest/leads",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-Lead-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        die(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    out(r, args.json, lambda r: print(
        f"{'создан' if r['created'] else 'уже был'} {r['key']} [{r['stage_name']}]\n{r['url']}"))


def cmd_decisions_sync(client, args):
    """Залить копию реестра решений из вики (decisions.py pms-export). KL-226."""
    body = json.loads(Path(args.json_file).read_text()) if args.json_file != "-" else json.load(sys.stdin)
    r = client.call("PUT", "/decisions/sync", body)

    def show(r):
        for x in r["registries"]:
            if x.get("skipped"):
                print(f"{x['registry']:24} пропущен: {x['skipped']}")
            elif x["created"] or x["updated"] or x["deleted"]:
                print(f"{x['registry']:24} {x['total']:4}  +{x['created']} ~{x['updated']} -{x['deleted']}")
        print("реестров:", len(r["registries"]), "· записей:", sum(x["total"] for x in r["registries"]))

    out(r, args.json, show)


# --------------------------------------------------------------------------- #
# Напоминания и каналы проекта (движок PMS, а не cron)
# --------------------------------------------------------------------------- #

SCHEDULE_WORDS = {"once": "ONCE", "daily": "DAILY", "weekdays": "WEEKDAYS", "weekly": "WEEKLY"}
WEEKDAY_WORDS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
                 "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
SCHEDULE_RU = {"ONCE": "один раз", "DAILY": "каждый день",
               "WEEKDAYS": "по рабочим дням", "WEEKLY": "раз в неделю"}


def _remind_day(value: str) -> str:
    """«04.11» | «2026-11-04» | «завтра» | «+3d» → YYYY-MM-DD (время берётся из --at)."""
    iso = parse_due(value)
    if iso is None:
        die("дата напоминания не может быть пустой")
    return iso[:10]


def _remind_time(value: str) -> str:
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", (value or "").strip())
    if not m:
        die(f"не понимаю время: {value} (пример: 10:00)")
    return f"{int(m.group(1)):02d}:{m.group(2)}:00"


def resolve_channel(client, project_id: str, ref: str) -> dict:
    channels = client.call("GET", f"/projects/{project_id}/channels")
    if not channels:
        die("у проекта нет каналов: заведи его командой channel add")
    low = ref.strip().lower()
    if low in ("project", "проект", "default", "по умолчанию"):
        for c in channels:
            if c["is_default"]:
                return c
        if len(channels) == 1:
            return channels[0]
        die("у проекта нет канала по умолчанию: укажи его по имени или пометь --default")
    for c in channels:
        if c["name"].lower() == low or c["address"] == ref.strip():
            return c
    for c in channels:
        if low in c["name"].lower():
            return c
    die(f"канал не найден: {ref}")


def resolve_reminder(client, key: str, ref: str | None) -> dict:
    """Напоминание адресуется задачей: обычно оно у неё одно."""
    task = resolve_task(client, key)
    items = client.call("GET", f"/tasks/{task['id']}/reminders")
    if ref:
        matched = [r for r in items if r["id"].startswith(ref)]
        if not matched:
            die(f"напоминание не найдено: {ref}")
        return matched[0]
    active = [r for r in items if r["status"] == "ACTIVE"]
    if not active:
        die(f"у {task['key']} нет действующих напоминаний")
    if len(active) > 1:
        die(f"у {task['key']} их {len(active)}: укажи --id (первые знаки) — "
            + ", ".join(r["id"][:8] for r in active))
    return active[0]


def _remind_line(r: dict) -> str:
    when = fmt_due(r.get("next_fire_at"), long=False) or "—"
    every = SCHEDULE_RU.get(r["schedule"], r["schedule"])
    at = str(r["at_time"])[:5]
    bits = [f"{r.get('task_key') or '':8} {r['id'][:8]}  {every} в {at}  → {when}"]
    if r["fire_count"]:
        bits.append(f"напомнили {r['fire_count']}")
    if r["status"] != "ACTIVE":
        bits.append(f"{r['status'].lower()}: {r.get('stop_reason') or ''}".strip(": "))
    return "  · ".join(bits)


def cmd_remind_add(client, args):
    task = resolve_task(client, args.key)
    body = {
        "schedule": args.schedule,
        "at_time": _remind_time(args.at),
        "stop_on_done": not args.ignore_done,
        "comment_on_task": bool(args.comment),
    }
    if args.before_due is not None:
        body["due_offset_days"] = -args.before_due
    if getattr(args, "from_day", None):
        body["start_on"] = _remind_day(args.from_day)
    elif args.before_due is None:
        body["start_on"] = _remind_day("сегодня")
    if args.until:
        body["until_on"] = _remind_day(args.until)
    if args.times:
        body["max_fires"] = args.times
    if args.weekday:
        low = args.weekday.strip().lower()
        if low not in WEEKDAY_WORDS:
            die(f"не понимаю день недели: {args.weekday} (пн вт ср чт пт сб вс)")
        body["weekday"] = WEEKDAY_WORDS[low]
    if args.mention:
        body["mention"] = args.mention
    if args.message:
        body["message"] = args.message
    if args.to:
        body["notify_user_id"] = resolve_user(client, args.to)["id"]
    if args.escalate_after:
        body["escalate_after_fires"] = args.escalate_after
        body["escalate_to_id"] = resolve_user(client, args.escalate_to or args.to or "").get("id") \
            if (args.escalate_to or args.to) else None
    if args.channel:
        body["channel_id"] = resolve_channel(client, task["project_id"], args.channel)["id"]

    r = client.call("POST", f"/tasks/{task['id']}/reminders", body)
    out(r, args.json, lambda r: print(
        f"напоминание по {task['key']}: {SCHEDULE_RU.get(r['schedule'], r['schedule'])} "
        f"в {str(r['at_time'])[:5]}, первое — {fmt_due(r['next_fire_at'], long=True)}"
        + ("\nостановится само, когда задачу закроют" if r["stop_on_done"] else "")
        + f"\n{client.task_url(task['key'])}"))


def cmd_remind_list(client, args):
    if args.key:
        task = resolve_task(client, args.key)
        items = client.call("GET", f"/tasks/{task['id']}/reminders")
    else:
        path = "/reminders?active_only=" + ("false" if args.all else "true")
        if args.project:
            path += "&project_id=" + resolve_project(client, args.project)["id"]
        items = client.call("GET", path)
    out(items, args.json, lambda items: print(
        "\n".join(_remind_line(r) for r in items) if items else "напоминаний нет"))


def cmd_remind_snooze(client, args):
    r = resolve_reminder(client, args.key, args.id)
    if args.until:
        day = _dt.date.fromisoformat(_remind_day(args.until))
        moment = _dt.time.fromisoformat(_remind_time(args.at or "10:00"))
        # Время переноса — московское: без явного пояса сервер взял бы своё.
        body = {"until": _dt.datetime.combine(day, moment, MSK).isoformat()}
    else:
        body = {"days": args.days}
    r = client.call("POST", f"/reminders/{r['id']}/snooze", body)
    out(r, args.json, lambda r: print(f"перенесено на {fmt_due(r['next_fire_at'], long=True)}"))


def cmd_remind_stop(client, args):
    r = resolve_reminder(client, args.key, args.id)
    r = client.call("POST", f"/reminders/{r['id']}/stop")
    out(r, args.json, lambda r: print(f"снято: {r['stop_reason']}"))


def cmd_remind_log(client, args):
    r = resolve_reminder(client, args.key, args.id)
    r = client.call("GET", f"/reminders/{r['id']}")

    def show(r):
        print(f"{r.get('task_key')}  {SCHEDULE_RU.get(r['schedule'], r['schedule'])} "
              f"в {str(r['at_time'])[:5]}  · напомнили {r['fire_count']}")
        if r["next_fire_at"]:
            print("следующее:", fmt_due(r["next_fire_at"], long=True))
        if r["stop_reason"]:
            print("остановлено:", r["stop_reason"])
        for m in r["log"]:
            print(f"  {fmt_due(m['scheduled_for'], long=True):22} {m['status']:8} {m['address']}"
                  + (f"  ошибка: {m['error']}" if m.get("error") else ""))

    out(r, args.json, show)


def cmd_channel_list(client, args):
    project = resolve_project(client, args.project)
    items = client.call("GET", f"/projects/{project['id']}/channels")
    out(items, args.json, lambda items: print("\n".join(
        f"{'*' if c['is_default'] else ' '} {c['name']:24} {c['kind']:9} {c['address']}"
        + ("" if c["enabled"] else "  (выключен)") for c in items) or "каналов нет"))


def cmd_channel_add(client, args):
    project = resolve_project(client, args.project)
    body = {"name": args.name, "address": args.address, "is_default": args.default}
    if args.thread:
        body["thread_id"] = args.thread
    c = client.call("POST", f"/projects/{project['id']}/channels", body)
    out(c, args.json, lambda c: print(
        f"канал «{c['name']}» {c['address']}" + (" (по умолчанию)" if c["is_default"] else "")))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pms.py", description="PMS task control CLI")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami").set_defaults(fn=cmd_whoami)
    sp = sub.add_parser("decisions-sync", help="залить копию реестра решений (JSON-файл или - для stdin)")
    sp.add_argument("json_file")
    sp.set_defaults(fn=cmd_decisions_sync)
    sp = sub.add_parser("projects", help="list projects")
    sp.add_argument("--archived", action="store_true", help="include archived projects")
    sp.set_defaults(fn=cmd_projects)

    sp = sub.add_parser("project-add", help="create a project")
    sp.add_argument("--code", required=True,
                    help="short key, e.g. AXM — becomes task keys AXM-1 and the /projects/axm link; cannot be changed later")
    sp.add_argument("--name", required=True)
    sp.add_argument("--group", help="portfolio group, e.g. Клиентские")
    sp.add_argument("--goal")
    sp.add_argument("--site", help="сайт проекта (https://example.ru): пути /lk/… в задачах станут ссылками")
    sp.set_defaults(fn=cmd_project_add)

    sp = sub.add_parser("project-edit", help="поменять поля проекта (сайт, название, группа)")
    sp.add_argument("code")
    sp.add_argument("--site", help="https://example.ru; none — снять")
    sp.add_argument("--name")
    sp.add_argument("--group")
    sp.set_defaults(fn=cmd_project_edit)

    sp = sub.add_parser("list", help="list tasks in a project")
    sp.add_argument("--project", required=True)
    sp.add_argument("--status", help="filter by status name or category")
    sp.add_argument("--assignee", help="filter by assignee email or name")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("inbox", help="tasks assigned to a user across all projects (AI provider queue)")
    sp.add_argument("--assignee", required=True, help="email or name, e.g. antigravity")
    sp.add_argument("--status", help="filter by status name or category, e.g. Ready")
    sp.set_defaults(fn=cmd_inbox)

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
    sp.add_argument("--brief", metavar="TEMPLATE",
                    help="ТЗ из хранимого шаблона seo-engine/briefs (briefs.py list): описание = шаблон + --desc")
    sp.add_argument("--param", action="append", metavar="K=V", help="параметр шаблона --brief (можно повторять)")
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
    sp.add_argument("--reason", help="чем задача заблокирована (обязательно для BLOCKED)")
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

    # ---- roadmap: роадмап проекта ----------------------------------------
    sp = sub.add_parser("roadmap", help="роадмап проекта: период, волны, метрики, отчёт")
    rsub = sp.add_subparsers(dest="roadmap_cmd", required=True)

    m = rsub.add_parser("list", help="роадмапы проекта или таймлайн портфеля")
    m.add_argument("--project", help="код проекта; без него — по одному на каждый проект")
    m.add_argument("--archived", action="store_true", help="включая архивные")
    m.set_defaults(fn=cmd_roadmap_list)

    m = rsub.add_parser("show", help="роадмап целиком: волны, пункты, метрики, блокеры")
    m.add_argument("--project")
    m.add_argument("--id", help="id роадмапа, если у проекта их несколько")
    m.set_defaults(fn=cmd_roadmap_show)

    m = rsub.add_parser("add", help="завести роадмап на период")
    m.add_argument("--project", required=True)
    m.add_argument("--title", required=True, help='например "Месяц 1"')
    m.add_argument("--start", required=True, metavar="WHEN", help=DUE_HELP)
    m.add_argument("--end", metavar="WHEN", help=DUE_HELP)
    m.add_argument("--status", choices=["DRAFT", "AGREED", "ACTIVE", "COMPLETED", "CANCELLED"])
    m.add_argument("--goal", help="цель периода")
    m.add_argument("--scope", help="чем согласован: «план из 14 пунктов, клиент 27.10 (K-006)»")
    m.add_argument("--agreed", metavar="WHEN", help="дата согласования")
    m.add_argument("--decision", help="номер в реестре решений: K-006, _global:P-040")
    m.add_argument("--plan-url", dest="plan_url", help="ссылка на исходный план или КП")
    m.add_argument("--report-url", dest="report_url", help="ссылка на опубликованный отчёт")
    m.set_defaults(fn=cmd_roadmap_add)

    m = rsub.add_parser("edit", help="поменять период, статус, согласование, ссылки")
    m.add_argument("--project")
    m.add_argument("--id")
    m.add_argument("--title")
    m.add_argument("--start", metavar="WHEN", help=DUE_HELP)
    m.add_argument("--end", metavar="WHEN", help=DUE_HELP)
    m.add_argument("--status", choices=["DRAFT", "AGREED", "ACTIVE", "COMPLETED", "CANCELLED"])
    m.add_argument("--goal")
    m.add_argument("--scope")
    m.add_argument("--agreed", metavar="WHEN")
    m.add_argument("--decision")
    m.add_argument("--plan-url", dest="plan_url")
    m.add_argument("--report-url", dest="report_url")
    m.add_argument("--archive", action="store_true", help="в архив")
    m.set_defaults(fn=cmd_roadmap_edit)

    m = rsub.add_parser("wave-add", help="волна роадмапа (неделя, пакет, выкладка)")
    m.add_argument("--project")
    m.add_argument("--id", help="id роадмапа")
    m.add_argument("--name", required=True)
    m.add_argument("--due", metavar="WHEN", help=DUE_HELP)
    m.add_argument("--desc")
    m.add_argument("--tasks", help="ключи уже существующих задач через запятую: SPD-6,SPD-19")
    m.set_defaults(fn=cmd_roadmap_wave_add)

    m = rsub.add_parser("metric-add", help="строка «было → цель»")
    m.add_argument("--project")
    m.add_argument("--id", help="id роадмапа")
    m.add_argument("--name", required=True)
    m.add_argument("--baseline", help="как есть сейчас: «0 из 165»")
    m.add_argument("--baseline-on", dest="baseline_on", metavar="WHEN", help="когда снято «было»")
    m.add_argument("--target", help="цель: «165 из 165»")
    m.add_argument("--current", help="текущее значение, если уже меряли")
    m.add_argument("--measured-on", dest="measured_on", metavar="WHEN")
    m.add_argument("--reached-on", dest="reached_on", metavar="WHEN", help="когда цель достигнута")
    m.add_argument("--source", help="чем снято: краул, Топвизор, GSC")
    m.set_defaults(fn=cmd_roadmap_metric_add)

    m = rsub.add_parser("metric-set", help="обновить метрику при сверке")
    m.add_argument("metric", help="id метрики (виден в roadmap show)")
    m.add_argument("--name")
    m.add_argument("--baseline")
    m.add_argument("--baseline-on", dest="baseline_on", metavar="WHEN")
    m.add_argument("--target")
    m.add_argument("--current")
    m.add_argument("--measured-on", dest="measured_on", metavar="WHEN")
    m.add_argument("--reached-on", dest="reached_on", metavar="WHEN")
    m.add_argument("--source")
    m.set_defaults(fn=cmd_roadmap_metric_set)

    m = rsub.add_parser("report", help="собрать HTML-отчёт роадмапа из данных PMS")
    m.add_argument("--project")
    m.add_argument("--id")
    m.add_argument("--out", help="путь файла; по умолчанию reports/<код>-roadmap-<дата>.html")
    m.set_defaults(fn=cmd_roadmap_report)

    # ---- lead: лиды проекта ----------------------------------------------
    sp = sub.add_parser("lead", help="лиды проекта (модуль включается: lead enable)")
    lsub = sp.add_subparsers(dest="lead_cmd", required=True)

    m = lsub.add_parser("list", help="лиды проекта")
    m.add_argument("--project", required=True)
    m.add_argument("--stage", help="имя этапа")
    m.add_argument("--category", choices=["OPEN", "WON", "LOST"])
    m.add_argument("--source")
    m.add_argument("--q", help="поиск по названию, контакту, телефону, email, внешнему id")
    m.set_defaults(fn=cmd_lead_list)

    m = lsub.add_parser("add", help="завести лид вручную")
    m.add_argument("--project", required=True)
    m.add_argument("--title", required=True)
    m.add_argument("--source", default="manual", help="kwork, fl, site, telegram, …")
    m.add_argument("--external", help="внешний id (номер проекта Kwork, id заказа)")
    m.add_argument("--contact")
    m.add_argument("--phone")
    m.add_argument("--email")
    m.add_argument("--amount")
    m.add_argument("--url", help="ссылка на источник")
    m.add_argument("--stage", help="имя этапа (по умолчанию первый)")
    m.add_argument("--owner", help="ответственный: email или имя")
    m.add_argument("--field", action="append", metavar="KEY=VALUE", help="своё поле, можно повторять")
    m.set_defaults(fn=cmd_lead_add)

    m = lsub.add_parser("show", help="карточка лида и журнал")
    m.add_argument("key", help="например KL-L-3")
    m.set_defaults(fn=cmd_lead_show)

    m = lsub.add_parser("stage", help="перевести на этап")
    m.add_argument("key")
    m.add_argument("stage", help="имя этапа")
    m.add_argument("--reason", help="причина проигрыша (обязательна для LOST)")
    m.set_defaults(fn=cmd_lead_stage)

    m = lsub.add_parser("edit", help="поменять поля лида")
    m.add_argument("key")
    m.add_argument("--title")
    m.add_argument("--contact")
    m.add_argument("--phone")
    m.add_argument("--email")
    m.add_argument("--amount")
    m.add_argument("--url")
    m.add_argument("--owner")
    m.add_argument("--field", action="append", metavar="KEY=VALUE", help="пустое значение стирает поле")
    m.set_defaults(fn=cmd_lead_edit)

    m = lsub.add_parser("comment", help="комментарий к лиду")
    m.add_argument("key")
    m.add_argument("text")
    m.set_defaults(fn=cmd_lead_comment)

    m = lsub.add_parser("task", help="создать задачу по лиду (ссылка в обе стороны)")
    m.add_argument("key")
    m.add_argument("--title")
    m.add_argument("--to", help="исполнитель: email или имя")
    m.add_argument("--priority", default="MEDIUM",
                   choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"])
    m.set_defaults(fn=cmd_lead_task)

    m = lsub.add_parser("stats", help="воронка: этапы, конверсия, источники")
    m.add_argument("--project", required=True)
    m.add_argument("--from", dest="date_from", help=DUE_HELP)
    m.add_argument("--to", dest="date_to")
    m.set_defaults(fn=cmd_lead_stats)

    m = lsub.add_parser("enable", help="включить лиды на проекте")
    m.add_argument("--project", required=True)
    m.add_argument("--preset", default="basic", choices=["sales", "orders", "basic"])
    m.set_defaults(fn=cmd_lead_enable)

    m = lsub.add_parser("tokens", help="ключи приёма проекта")
    m.add_argument("--project", required=True)
    m.set_defaults(fn=cmd_lead_tokens)

    m = lsub.add_parser("token-add", help="выпустить ключ приёма (значение показывается один раз)")
    m.add_argument("--project", required=True)
    m.add_argument("--label", required=True)
    m.add_argument("--save", metavar="FILE", help="записать ключ в файл (chmod 600) и не печатать")
    m.set_defaults(fn=cmd_lead_token_add)

    m = lsub.add_parser("ingest", help="приём лида по ключу проекта (JSON-файл или - для stdin)")
    m.add_argument("json_file")
    m.add_argument("--token-file", help="файл с ключом; иначе env PMS_LEAD_TOKEN")
    m.add_argument("--api", help="адрес API, если нет конфига")
    m.set_defaults(fn=cmd_lead_ingest, no_auth=True)

    sp = sub.add_parser("remind", help="напоминания по задаче (движок PMS, не cron)")
    rsub = sp.add_subparsers(dest="sub", required=True)

    m = rsub.add_parser("add", help="завести напоминание")
    m.add_argument("key", help="задача, например SSK-415")
    m.add_argument("--from", dest="from_day", help="с какого дня: 04.11, 2026-11-04, завтра, +3d")
    m.add_argument("--at", default="10:00", help="во сколько (по Москве), по умолчанию 10:00")
    m.add_argument("--once", dest="schedule", action="store_const", const="ONCE", default="ONCE")
    m.add_argument("--daily", dest="schedule", action="store_const", const="DAILY")
    m.add_argument("--weekdays", dest="schedule", action="store_const", const="WEEKDAYS",
                   help="по рабочим дням")
    m.add_argument("--weekly", dest="schedule", action="store_const", const="WEEKLY")
    m.add_argument("--weekday", help="для --weekly: пн вт ср чт пт сб вс")
    m.add_argument("--before-due", type=int, metavar="N",
                   help="за N дней до срока задачи; перенос срока двигает напоминание")
    m.add_argument("--until", help="до какой даты напоминать")
    m.add_argument("--times", type=int, help="сколько раз максимум")
    m.add_argument("--ignore-done", action="store_true",
                   help="не останавливаться, когда задачу закроют (по умолчанию останавливается)")
    m.add_argument("--channel", help="канал проекта: project (по умолчанию) или имя канала")
    m.add_argument("--mention", help="кого упомянуть в чате, например @vanstallin")
    m.add_argument("--message", help="свой текст вместо собранного из задачи")
    m.add_argument("--to", help="кого уведомлять в PMS (email или имя); по умолчанию исполнителя")
    m.add_argument("--escalate-after", type=int, metavar="N",
                   help="после N безответных напоминаний сообщить владельцу")
    m.add_argument("--escalate-to", help="кому эскалировать (email или имя)")
    m.add_argument("--comment", action="store_true", help="писать каждое напоминание комментарием")
    m.set_defaults(fn=cmd_remind_add)

    m = rsub.add_parser("list", help="напоминания задачи, проекта или все")
    m.add_argument("key", nargs="?", help="задача; без неё — по проекту или все")
    m.add_argument("--project")
    m.add_argument("--all", action="store_true", help="включая снятые и отработавшие")
    m.set_defaults(fn=cmd_remind_list)

    m = rsub.add_parser("snooze", help="перенести ближайшее напоминание")
    m.add_argument("key")
    m.add_argument("--id", help="первые знаки, если напоминаний несколько")
    m.add_argument("--days", type=int, default=1)
    m.add_argument("--until", help="на конкретную дату")
    m.add_argument("--at", help="во сколько при --until")
    m.set_defaults(fn=cmd_remind_snooze)

    m = rsub.add_parser("stop", help="снять напоминание")
    m.add_argument("key")
    m.add_argument("--id")
    m.set_defaults(fn=cmd_remind_stop)

    m = rsub.add_parser("log", help="когда и куда напоминали")
    m.add_argument("key")
    m.add_argument("--id")
    m.set_defaults(fn=cmd_remind_log)

    sp = sub.add_parser("channel", help="каналы проекта: куда ему разрешено писать")
    csub = sp.add_subparsers(dest="sub", required=True)

    m = csub.add_parser("list", help="каналы проекта")
    m.add_argument("--project", required=True)
    m.set_defaults(fn=cmd_channel_list)

    m = csub.add_parser("add", help="завести канал (чат проекта)")
    m.add_argument("--project", required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--address", required=True, help="для Telegram — chat_id")
    m.add_argument("--thread", help="топик внутри чата")
    m.add_argument("--default", action="store_true", help="канал проекта по умолчанию")
    m.set_defaults(fn=cmd_channel_add)

    return p


def main() -> None:
    args = build_parser().parse_args()
    client = None if getattr(args, "no_auth", False) else Client(_load_config())
    try:
        args.fn(client, args)
    except ApiError as e:
        die(str(e))


if __name__ == "__main__":
    main()
