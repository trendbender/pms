"""Роадмап проекта: период работ, его метрики и связь с волнами.

Роадмап это не ещё один список задач, а обёртка вокруг них: период («месяц 1,
28.10 - 26.11»), чем он согласован с клиентом, таблица «было → цель → стало» и
ссылка на опубликованный отчёт. Сами пункты плана остаются обычными задачами,
волны роадмапа — инициативами (`initiatives.roadmap_id`), поэтому прогресс
считается по задачам и нигде не дублируется.

Метрики хранятся строками, а не числами: в живых роадмапах «было» звучит как
«0 из 165» или «любой регистр отдаёт 200», и приведение такого к числу врёт.
Факт достижения цели фиксируется датой `reached_on`, её ставит человек при сверке.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Roadmap(Base, TimestampMixin):
    __tablename__ = "roadmaps"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Роадмап без периода не роадмап: по нему считаются недели и просрочка.
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # DRAFT / AGREED / ACTIVE / COMPLETED / CANCELLED (app.models.enums.RoadmapStatus)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")

    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Чем согласован: «план из 14 пунктов согласован клиентом 27.10 (K-006)».
    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    agreed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Номер в реестре решений («K-006», «SPD:K-006»), ссылка строится как /d/<код>-<ref>.
    decision_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Исходный план или КП и опубликованный отчёт: файлы живут вне PMS, здесь ссылки.
    plan_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    report_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoadmapMetric(Base, TimestampMixin):
    """Одна строка таблицы «было → цель → стало»."""

    __tablename__ = "roadmap_metrics"

    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    roadmap_id: Mapped[UUID] = mapped_column(
        ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    current: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Чем снято: «краул site-crawl», «Топвизор 20.10», «GSC 3 мес.».
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reached_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
