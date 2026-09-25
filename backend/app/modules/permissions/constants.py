"""Base permission strings (spec §8) and the role -> permission matrix.

Authorization is always evaluated on the backend. Permissions are derived from
roles rather than stored per user, which keeps the MVP simple; the string
vocabulary below is the stable contract the rest of the app checks against.
"""

from enum import StrEnum

from app.models.enums import ProjectRole, SystemRole


class Perm(StrEnum):
    WORKSPACE_VIEW = "workspace.view"
    WORKSPACE_MANAGE = "workspace.manage"

    PROJECT_VIEW = "project.view"
    PROJECT_CREATE = "project.create"
    PROJECT_EDIT = "project.edit"
    PROJECT_ARCHIVE = "project.archive"
    PROJECT_DELETE = "project.delete"

    PROJECT_MEMBERS_VIEW = "project.members.view"
    PROJECT_MEMBERS_MANAGE = "project.members.manage"

    TASK_VIEW = "task.view"
    TASK_CREATE = "task.create"
    TASK_EDIT = "task.edit"
    TASK_DELETE = "task.delete"
    TASK_ASSIGN = "task.assign"
    TASK_CHANGE_STATUS = "task.change_status"

    COMMENT_CREATE = "comment.create"
    COMMENT_EDIT = "comment.edit"
    COMMENT_DELETE = "comment.delete"

    ATTACHMENT_UPLOAD = "attachment.upload"
    ATTACHMENT_DELETE = "attachment.delete"

    SPRINT_VIEW = "sprint.view"
    SPRINT_MANAGE = "sprint.manage"

    BOARD_VIEW = "board.view"
    BOARD_MANAGE = "board.manage"

    # Деньги видит и ведёт только управляющий уровень: суммы клиентов не должны
    # быть видны рядовому исполнителю или подрядчику, добавленному в проект.
    FINANCE_VIEW = "finance.view"
    FINANCE_MANAGE = "finance.manage"


ALL_PERMS: frozenset[Perm] = frozenset(Perm)

# Read-only subset used by Viewer/Guest.
_READ_PERMS: frozenset[Perm] = frozenset(
    {
        Perm.WORKSPACE_VIEW,
        Perm.PROJECT_VIEW,
        Perm.PROJECT_MEMBERS_VIEW,
        Perm.TASK_VIEW,
        Perm.SPRINT_VIEW,
        Perm.BOARD_VIEW,
    }
)

# Member: can do task-level work but not manage the project or its membership.
_MEMBER_PERMS: frozenset[Perm] = _READ_PERMS | frozenset(
    {
        Perm.TASK_CREATE,
        Perm.TASK_EDIT,
        Perm.TASK_ASSIGN,
        Perm.TASK_CHANGE_STATUS,
        Perm.COMMENT_CREATE,
        Perm.COMMENT_EDIT,
        Perm.ATTACHMENT_UPLOAD,
    }
)

# Manager: everything a Member has + project/sprint/board/member management.
_MANAGER_PERMS: frozenset[Perm] = _MEMBER_PERMS | frozenset(
    {
        Perm.PROJECT_EDIT,
        Perm.PROJECT_ARCHIVE,
        Perm.PROJECT_MEMBERS_MANAGE,
        Perm.TASK_DELETE,
        Perm.COMMENT_DELETE,
        Perm.ATTACHMENT_DELETE,
        Perm.SPRINT_MANAGE,
        Perm.BOARD_MANAGE,
        Perm.FINANCE_VIEW,
        Perm.FINANCE_MANAGE,
    }
)

# Owner (of a project): manager + delete the project.
_PROJECT_OWNER_PERMS: frozenset[Perm] = _MANAGER_PERMS | frozenset(
    {Perm.PROJECT_DELETE, Perm.PROJECT_CREATE}
)

# ---- Project-level role -> permissions ----
PROJECT_ROLE_PERMS: dict[ProjectRole, frozenset[Perm]] = {
    ProjectRole.OWNER: _PROJECT_OWNER_PERMS,
    ProjectRole.MANAGER: _MANAGER_PERMS,
    ProjectRole.MEMBER: _MEMBER_PERMS,
    ProjectRole.VIEWER: _READ_PERMS,
    ProjectRole.GUEST: _READ_PERMS,
}

# ---- System (workspace) role -> permissions ----
# Owner/Admin are workspace-wide superusers; Manager can create projects.
SYSTEM_ROLE_PERMS: dict[SystemRole, frozenset[Perm]] = {
    SystemRole.OWNER: ALL_PERMS,
    SystemRole.ADMIN: ALL_PERMS,
    SystemRole.MANAGER: frozenset({Perm.WORKSPACE_VIEW, Perm.PROJECT_CREATE}),
    SystemRole.MEMBER: frozenset({Perm.WORKSPACE_VIEW}),
    SystemRole.VIEWER: frozenset({Perm.WORKSPACE_VIEW}),
    SystemRole.GUEST: frozenset(),
}
