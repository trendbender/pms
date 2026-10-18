"""Готовые воронки, которыми модуль засевается при включении на проекте.

Этапы и поля после включения правятся в настройках проекта: пресет это только
стартовая точка, а не жёсткая схема.
"""

from typing import Any

# (name, category, color)
Stage = tuple[str, str, str | None]

PRESETS: dict[str, dict[str, Any]] = {
    # Продажи агентства (КлиентЛаб): заявка на услуги -> сделка.
    "sales": {
        "stages": [
            ("Новый", "OPEN", "slate"),
            ("Квалификация", "OPEN", "blue"),
            ("Отклик/КП отправлен", "OPEN", "indigo"),
            ("Переговоры", "OPEN", "violet"),
            ("Аудит оплачен", "OPEN", "amber"),
            ("Выигран", "WON", "green"),
            ("Проигран", "LOST", "red"),
        ],
        "fields": [
            {"key": "budget", "label": "Бюджет покупателя", "type": "money"},
            {"key": "our_price", "label": "Наша цена", "type": "money"},
            {"key": "niche", "label": "Ниша", "type": "text"},
            {"key": "site", "label": "Сайт клиента", "type": "url"},
            {"key": "leads_db_id", "label": "id в leads.db", "type": "number"},
            {"key": "next_step", "label": "Следующий шаг", "type": "text"},
            {"key": "next_step_at", "label": "Срок следующего шага", "type": "date"},
        ],
    },
    # Заказы трансферов (ubo-orders): заказ с площадки -> выполнен и оплачен.
    "orders": {
        "stages": [
            ("Новый", "OPEN", "slate"),
            ("Подтверждён", "OPEN", "blue"),
            ("Водитель назначен", "OPEN", "indigo"),
            ("Выполнен", "OPEN", "amber"),
            ("Оплачен", "WON", "green"),
            ("Отменён", "LOST", "red"),
        ],
        "fields": [
            {
                "key": "platform",
                "label": "Площадка",
                "type": "select",
                "options": ["UBO", "TMT", "Другое"],
                "required": True,
            },
            {"key": "order_id", "label": "id заказа на площадке", "type": "text"},
            {"key": "pickup_at", "label": "Подача", "type": "datetime", "required": True},
            {"key": "from", "label": "Откуда", "type": "text", "required": True},
            {"key": "to", "label": "Куда", "type": "text", "required": True},
            {"key": "passengers", "label": "Пассажиры", "type": "number"},
            {"key": "luggage", "label": "Багаж", "type": "text"},
            {"key": "car_class", "label": "Класс авто", "type": "text"},
            {
                "key": "payment_method",
                "label": "Способ оплаты",
                "type": "select",
                "options": ["Карта", "Наличные", "Счёт"],
            },
            {"key": "driver", "label": "Водитель", "type": "text", "is_pii": True},
            {"key": "client_comment", "label": "Комментарий клиента", "type": "text",
             "is_pii": True},
        ],
    },
    # Пустая воронка: три этапа, полей нет.
    "basic": {
        "stages": [
            ("Новый", "OPEN", "slate"),
            ("В работе", "OPEN", "blue"),
            ("Выигран", "WON", "green"),
            ("Проигран", "LOST", "red"),
        ],
        "fields": [],
    },
}
