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
    pms.py list --project ABC
    pms.py show ABC-26
    pms.py add --project ABC --title "Check the forms" --priority HIGH
    pms.py add --project ABC --title "Update the block" --desc "..." --attach /tmp/shot.jpg
    pms.py attach ABC-26 /tmp/screenshot.jpg
    pms.py comment ABC-26 "done, waiting for review"
    pms.py status ABC-26 "In Progress"
    pms.py done ABC-26
    pms.py assign ABC-26 --to teammate@example.com
    pms.py rm ABC-26 --yes

Add --json to most read commands for machine output.
"""

from __future__ import annotations

import argparse
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

# Back-compat: honour the older PMS_BOT_* env names if they are set.
CONFIG_PATH = os.environ.get("PMS_CONFIG") or os.environ.get(
    "PMS_BOT_CONFIG", str(Path.home() / ".config/pms.json")
)
CACHE_PATH = Path(
    os.environ.get("PMS_CACHE")
    or os.environ.get("PMS_BOT_CACHE", str(Path.home() / ".cache/pms_token.json"))
)


# --------------------------------------------------------------------------- #
# HTTP + auth
# --------------------------------------------------------------------------- #


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
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
    ps = client.call("GET", "/projects")
    ps.sort(key=lambda p: (p.get("group_name") or "", p["code"]))
    out(ps, args.json, lambda ps: [
        print(f"{p['code']:<6} {p['name']}  ·  {p.get('group_name') or '—'}  [{p['status']}/{p['health']}]")
        for p in ps
    ])


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
            print(f"{t['key']:<8} [{t.get('status_name','?'):<12}] {t['priority']:<8} @{who}{blk}  {t['title']}")
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
    task = client.call("POST", "/tasks", body)
    if args.assignee:
        user = resolve_user(client, args.assignee)
        client.call("PATCH", f"/tasks/{task['id']}", {"assignee_id": user["id"]})
    attached = [client.upload(task["id"], fp) for fp in (args.attach or [])]

    def human(t):
        print(f"создана {t['key']}: {t['title']}")
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
    if not body:
        die("nothing to change (pass --title / --desc / --priority)")
    t = client.call("PATCH", f"/tasks/{task['id']}", body)
    out(t, args.json, lambda t: print(f"обновлена {t['key']}\n{client.task_url(t['key'])}"))


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


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pms.py", description="PMS task control CLI")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami").set_defaults(fn=cmd_whoami)
    sub.add_parser("projects").set_defaults(fn=cmd_projects)

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
    sp.add_argument("--assignee", help="email or name")
    sp.add_argument("--attach", action="append", metavar="FILE",
                    help="прикрепить файл к задаче (можно повторять), напр. скриншот")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("edit", help="update title/description/priority of an existing task")
    sp.add_argument("key")
    sp.add_argument("--title")
    sp.add_argument("--desc")
    sp.add_argument("--priority", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"])
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

    sp = sub.add_parser("rm", help="delete a task")
    sp.add_argument("key")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(fn=cmd_rm)

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
