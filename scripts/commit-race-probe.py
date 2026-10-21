#!/usr/bin/env python3
"""Probe: create -> immediately read on a running PMS backend.

Checks that a 201 means "already committed": after POST lead / POST task the very next
GET must be 200. Before the fix in 0.3.1 (get_db committed after the response was sent)
this gave GET 404 and, with key allocation, POST 409/500 on the following create.

Creates a throwaway project "race-probe" with N leads and N tasks: run it on a demo or
stage stack, not on prod.

    PMS_URL=http://127.0.0.1:8000 PMS_EMAIL=owner@ex.com PMS_PASSWORD=... \
        python3 scripts/commit-race-probe.py [N=100]

PMS_URL is the backend root (with the /api prefix if it goes through nginx).
Exit code 1 if any pair failed.
"""

import os
import sys
import time

import httpx


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    c = httpx.Client(base_url=os.environ["PMS_URL"], timeout=10)
    r = c.post(
        "/auth/login",
        json={"email": os.environ["PMS_EMAIL"], "password": os.environ["PMS_PASSWORD"]},
    )
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    code = f"RP{int(time.time()) % 100000}"
    r = c.post("/projects", headers=h, json={"name": "race-probe", "code": code})
    r.raise_for_status()
    pid = r.json()["id"]
    time.sleep(0.5)  # setup is not what we measure
    c.post(f"/projects/{pid}/leads/enable", headers=h, json={"preset": "basic"}).raise_for_status()
    time.sleep(0.5)

    failed = 0
    for kind, url, body, get in [
        ("lead", f"/projects/{pid}/leads", {"title": "probe"}, "/leads/{}"),
        ("task", "/tasks", {"project_id": pid, "title": "probe"}, "/tasks/{}"),
    ]:
        codes: dict[str, int] = {}
        for _ in range(n):
            r = c.post(url, headers=h, json=body)
            if r.status_code != 201:
                key = f"POST {r.status_code}"
                time.sleep(0.2)
            else:
                key = f"GET {c.get(get.format(r.json()['id']), headers=h).status_code}"
            codes[key] = codes.get(key, 0) + 1
        bad = n - codes.get("GET 200", 0)
        failed += bad
        print(f"{kind}: {codes}  failed {bad}/{n}")
    print(f"project {code} ({pid}) can be deleted")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
