import pytest

from app.core.links import absolutize_site_paths, normalize_site_url
from app.models.enums import SystemRole
from tests.factories import make_user, make_workspace

SITE = "https://skolkoskolko.ru"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # путь из задачи SSK-262: «&», скобка и точка после адреса
        (
            "Запрос владельца (скрин /lk/turnkey/?admin=1&branch=63680&template=1).",
            "Запрос владельца (скрин https://skolkoskolko.ru/lk/turnkey/?admin=1&branch=63680&template=1).",
        ),
        ("см. /kontakty/, там форма", "см. https://skolkoskolko.ru/kontakty/, там форма"),
        ("/admin/kr — редактор", "https://skolkoskolko.ru/admin/kr — редактор"),
        ("«/lk/claim/»", "«https://skolkoskolko.ru/lk/claim/»"),
        ("[ЛК](/lk/claim/)", "[ЛК](https://skolkoskolko.ru/lk/claim/)"),
        ("док: /admin/architecture/?doc=dgis-collect#top!", "док: https://skolkoskolko.ru/admin/architecture/?doc=dgis-collect#top!"),
    ],
)
def test_site_paths_become_absolute(text, expected):
    assert absolutize_site_paths(text, SITE) == expected


@pytest.mark.parametrize(
    "text",
    [
        "уже готово https://skolkoskolko.ru/lk/turnkey/?a=1",
        "файл /srv/projects/scripts/pms.py и /etc/nginx/sites-available/x",
        "~/Claude/_wiki/projects/pms.md и _wiki/projects/pms/x",
        "команда /clear и /poisk без слеша",
        "в коде `/lk/turnkey/` не трогаем",
        "```\ncurl /lk/turnkey/\n```",
        "дроби 1/2, 26/10/2026 и кол-во / цена",
        "http://46.224.149.23:8444/reports/x.html",
        "файл /backend/app/core/links.py",
        "/tmp/scratch/job/ и /home/claw/logs/",
    ],
)
def test_other_text_untouched(text):
    assert absolutize_site_paths(text, SITE) == text


def test_no_site_url_keeps_text():
    assert absolutize_site_paths("/lk/turnkey/", None) == "/lk/turnkey/"


def test_normalize_site_url():
    assert normalize_site_url("skolkoskolko.ru/") == SITE
    assert normalize_site_url("  ") is None
    with pytest.raises(ValueError):
        normalize_site_url("https://skolkoskolko.ru/lk/")


async def _token(client, email, password="password123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_task_and_comment_store_absolute_links(client, session):
    ws = await make_workspace(session)
    await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    await session.commit()
    h = {"Authorization": f"Bearer {await _token(client, 'owner@ex.com')}"}

    proj = await client.post(
        "/projects", headers=h, json={"name": "S", "code": "SSK", "site_url": "skolkoskolko.ru"}
    )
    assert proj.status_code == 201, proj.text
    proj = proj.json()
    assert proj["site_url"] == SITE

    task = await client.post(
        "/tasks", headers=h,
        json={"project_id": proj["id"], "title": "t", "description": "скрин /lk/turnkey/?a=1"},
    )
    task = task.json()
    assert task["description"] == f"скрин {SITE}/lk/turnkey/?a=1"

    up = await client.patch(
        f"/tasks/{task['id']}", headers=h, json={"description": "см. /admin/kr"}
    )
    assert up.json()["description"] == f"см. {SITE}/admin/kr"

    c = await client.post(
        f"/tasks/{task['id']}/comments", headers=h, json={"body": "выкачено: /kontakty/."}
    )
    assert c.json()["body"] == f"выкачено: {SITE}/kontakty/."

    # очистка сайта: пути снова остаются как есть
    cleared = await client.patch(f"/projects/{proj['id']}", headers=h, json={"site_url": ""})
    assert cleared.json()["site_url"] is None
    c2 = await client.post(
        f"/tasks/{task['id']}/comments", headers=h, json={"body": "/kontakty/"}
    )
    assert c2.json()["body"] == "/kontakty/"
