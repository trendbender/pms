#!/usr/bin/env python3
"""Релей исходящей очереди PMS → Telegram (решение T-003, задача PMS-29).

Весь смысл этого скрипта в том, чего в нём нет. Он не знает ни расписаний, ни
условий остановки, ни того, закрыта ли задача: PMS уже всё решил и положил
готовое сообщение в очередь. Релей только забирает его и отдаёт боту.

Поэтому его можно снести, переписать или остановить на час — напоминания от
этого не пропадут и не сдвинутся, очередь просто подождёт. Ровно это и
отличает его от прежнего ssk-edpol-remind.sh, который держал всю логику у
себя и умирал вместе с кроном.

Живёт на Hetzner (там же, где бот и его токен), ходит в прод-API служебным
аккаунтом pms-bot. Запуск раз в минуту из crontab:

    * * * * * flock -n /tmp/pms-outbox-relay.lock python3 /srv/projects/scripts/pms-outbox-relay.py >> /home/claw/logs/pms-outbox-relay.log 2>&1

Отправкой занимается tg-hub (`tghub_send`) — у него свои секрет-гейт, нарезка
длинных сообщений и дедуп; дублировать их здесь нечем и незачем.
"""

import importlib
import sys
import urllib.parse

sys.path.insert(0, "/srv/projects/scripts")

pms = importlib.import_module("pms")
from tghub_send import tg_send  # noqa: E402  (путь добавляется выше)

BATCH = 20


def main() -> int:
    client = pms.Client(pms._load_config())
    queue = client.call("GET", f"/outbox/pending?limit={BATCH}")
    if not queue:
        return 0

    sent = 0
    for message in queue:
        try:
            ok, _ = tg_send(
                message["address"],
                message["body"],
                kind="alert",
                # Дедуп по строке очереди: даже два одновременных релея не
                # отправят одно и то же сообщение дважды.
                dedup=f"pms-outbox-{message['id']}",
                topic=message.get("thread_id"),
            )
            error = "" if ok else "tg_send отказался отправлять"
        except Exception as exc:  # сеть, хаб лежит, что угодно
            ok, error = False, f"{type(exc).__name__}: {exc}"

        if ok:
            client.call("POST", f"/outbox/{message['id']}/sent")
            sent += 1
        else:
            client.call(
                "POST",
                f"/outbox/{message['id']}/failed?error={urllib.parse.quote(error[:500])}",
            )
            print(f"не ушло {message['id'][:8]} → {message['address']}: {error}", file=sys.stderr)

    print(f"отправлено {sent} из {len(queue)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
