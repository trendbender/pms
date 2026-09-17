"""Import all models so that Base.metadata is fully populated (Alembic, create_all)."""

from app.models.attachment import Attachment
from app.models.audit import ActivityLog, AuditLog
from app.models.base import Base
from app.models.comment import Comment
from app.models.initiative import Initiative
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.sprint import Sprint
from app.models.task import Task, TaskStatus, TaskType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "Base",
    "Workspace",
    "WorkspaceMember",
    "User",
    "Project",
    "ProjectMember",
    "Initiative",
    "Sprint",
    "Task",
    "TaskType",
    "TaskStatus",
    "Comment",
    "Attachment",
    "Notification",
    "ActivityLog",
    "AuditLog",
]
