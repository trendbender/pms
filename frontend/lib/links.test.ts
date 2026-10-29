// npm test: tsc собирает этот файл во временную папку и гоняет node --test.
import assert from "node:assert/strict";
import { test } from "node:test";

import { linkifyMarkdown, splitLinks } from "./links";

const ctx = {
  projectCode: "SSK",
  siteUrl: "https://skolkoskolko.ru",
  taskCodes: new Set(["SSK", "PMS", "KL"]),
};

const links = (text: string) =>
  splitLinks(text, ctx)
    .filter((p) => p.href)
    .map((p) => [p.text, p.href]);

test("путь сайта из SSK-262: «&», скобка и точка после адреса", () => {
  const text = "Запрос владельца (скрин /lk/turnkey/?admin=1&branch=63680&template=1).";
  assert.deepEqual(links(text), [
    [
      "/lk/turnkey/?admin=1&branch=63680&template=1",
      "https://skolkoskolko.ru/lk/turnkey/?admin=1&branch=63680&template=1",
    ],
  ]);
  const parts = splitLinks(text, ctx);
  assert.equal(parts[parts.length - 1].text, ").");
  assert.equal(parts.map((p) => p.text).join(""), text);
});

test("голые адреса: хвостовая пунктуация и скобки не входят", () => {
  assert.deepEqual(links("см. https://pms.klientlab.ru/t/ssk-262."), [
    ["https://pms.klientlab.ru/t/ssk-262", "https://pms.klientlab.ru/t/ssk-262"],
  ]);
  assert.deepEqual(links("(отчёт http://46.224.149.23:8444/r/x.html?a=1&b=2)"), [
    ["http://46.224.149.23:8444/r/x.html?a=1&b=2", "http://46.224.149.23:8444/r/x.html?a=1&b=2"],
  ]);
  assert.deepEqual(links("https://ru.wikipedia.org/wiki/A_(b)"), [
    ["https://ru.wikipedia.org/wiki/A_(b)", "https://ru.wikipedia.org/wiki/A_(b)"],
  ]);
});

test("ключи задач и номера решений", () => {
  assert.deepEqual(links("после SSK-261, KL-177 и P-041, _global:P-022"), [
    ["SSK-261", "/t/ssk-261"],
    ["KL-177", "/t/kl-177"],
    ["P-041", "/d/ssk-p-041"],
    ["_global:P-022", "/d/g-p-022"],
  ]);
  // не проекты и части адресов — не ссылки
  assert.deepEqual(links("UC-001, ISO-9001, UTF-8, ops/ssk261-pkg"), []);
  assert.deepEqual(links("https://pms.klientlab.ru/t/SSK-262"), [
    ["https://pms.klientlab.ru/t/SSK-262", "https://pms.klientlab.ru/t/SSK-262"],
  ]);
});

test("файлы и команды не превращаются в ссылки сайта", () => {
  for (const text of [
    "/srv/projects/scripts/pms.py",
    "~/Claude/_wiki/projects/pms.md",
    "_wiki/projects/pms/x",
    "/clear и /poisk",
    "1/2, 26/10/2026, кол-во / цена",
    "/backend/app/core/links.py",
    "/home/claw/logs/ и /tmp/scratch/",
  ]) {
    assert.deepEqual(links(text), [], text);
  }
});

test("без site_url путь остаётся текстом", () => {
  assert.deepEqual(splitLinks("/lk/turnkey/", { projectCode: "PMS" }), [{ text: "/lk/turnkey/" }]);
});

test("Markdown: путь и ключ оборачиваются, готовое не трогаем", () => {
  assert.equal(
    linkifyMarkdown("скрин /lk/turnkey/?admin=1&branch=63680&template=1).", ctx),
    "скрин [/lk/turnkey/?admin=1&branch=63680&template=1](<https://skolkoskolko.ru/lk/turnkey/?admin=1&branch=63680&template=1>)).",
  );
  assert.equal(linkifyMarkdown("см. SSK-262", ctx), "см. [SSK-262](</t/ssk-262>)");
  for (const text of [
    "[кабинет](/lk/claim/) и [SSK-1](https://pms.klientlab.ru/t/ssk-1)",
    "<https://skolkoskolko.ru/lk/>",
    "https://skolkoskolko.ru/lk/turnkey/?a=1",
    "в коде `/lk/turnkey/ SSK-262` не трогаем",
    "```\ncurl /lk/turnkey/\n```",
  ]) {
    assert.equal(linkifyMarkdown(text, ctx), text, text);
  }
  assert.equal(linkifyMarkdown("/lk/turn_key/", ctx), "[/lk/turn\\_key/](<https://skolkoskolko.ru/lk/turn_key/>)");
});
