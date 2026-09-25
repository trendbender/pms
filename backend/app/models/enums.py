"""String enums used across the domain.

Task *types* and *statuses* are configurable per project and live in their own
tables (task_types / task_statuses). The enums here are fixed vocabularies that
the spec defines as constants.
"""

from enum import StrEnum


class SystemRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"
    GUEST = "GUEST"


class ProjectRole(StrEnum):
    """A user's role *within a single project* (may differ per project)."""

    OWNER = "OWNER"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"
    GUEST = "GUEST"


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class ProjectHealth(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    OFF_TRACK = "OFF_TRACK"


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ContractType(StrEnum):
    """Как устроена оплата по договору."""

    FIXED = "FIXED"          # разовая работа под фиксированную сумму
    MILESTONE = "MILESTONE"  # этапами: каждый этап оплачивается отдельно
    RETAINER = "RETAINER"    # абонентская плата за период
    HOURLY = "HOURLY"        # почасовая ставка


class PaymentKind(StrEnum):
    PREPAY = "PREPAY"        # предоплата
    MILESTONE = "MILESTONE"  # оплата этапа или вехи
    RETAINER = "RETAINER"    # абонентский платёж за месяц
    HOURLY = "HOURLY"        # оплата отработанных часов
    EXTRA = "EXTRA"          # доплата за работы вне договора


class PaymentStatus(StrEnum):
    """Просрочка не хранится: она считается из due_date и текущего статуса."""

    EXPECTED = "EXPECTED"    # запланирован, счёт ещё не выставлен
    INVOICED = "INVOICED"    # счёт выставлен, деньги не пришли
    PAID = "PAID"
    CANCELLED = "CANCELLED"  # отменён или списан


class SprintStatus(StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Status *category* — lets the board/logic reason about configurable statuses
# without hardcoding names. Each project's task_statuses row maps to one category.
class StatusCategory(StrEnum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    DONE = "DONE"


# Default task statuses seeded for every new project (name -> category).
DEFAULT_STATUSES: list[tuple[str, StatusCategory]] = [
    ("Backlog", StatusCategory.BACKLOG),
    ("Ready", StatusCategory.READY),
    ("In Progress", StatusCategory.IN_PROGRESS),
    ("Blocked", StatusCategory.BLOCKED),
    ("Review", StatusCategory.REVIEW),
    ("Changes Required", StatusCategory.CHANGES_REQUIRED),
    ("Done", StatusCategory.DONE),
]

# Default task types seeded for every new project.
DEFAULT_TYPES: list[str] = ["TASK", "BUG", "FEATURE", "IMPROVEMENT", "RESEARCH"]


# UI languages a user may pick in their settings. The interface renders in the
# user's chosen language; add a code here (and a frontend dictionary) to extend.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "en"})
DEFAULT_LANGUAGE: str = "ru"
