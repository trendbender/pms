"""Unit tests for the RBAC matrix (no HTTP)."""

import pytest

from app.models.enums import ProjectRole, SystemRole
from app.models.project import Project, ProjectMember
from app.modules.permissions import service as perms
from app.modules.permissions.constants import Perm
from tests.factories import make_user, make_workspace


@pytest.mark.asyncio
async def test_workspace_owner_is_project_superuser(session):
    ws = await make_workspace(session)
    owner = await make_user(session, ws, "owner@ex.com", SystemRole.OWNER)
    project = Project(workspace_id=ws.id, name="P", code="P")
    session.add(project)
    await session.flush()

    # owner has no explicit project_members row, yet gets full project rights
    p = await perms.project_permissions(session, owner.id, ws.id, project.id)
    assert Perm.PROJECT_DELETE in p
    assert Perm.TASK_CHANGE_STATUS in p


@pytest.mark.asyncio
async def test_no_project_membership_means_no_access(session):
    ws = await make_workspace(session)
    member = await make_user(session, ws, "m@ex.com", SystemRole.MEMBER)
    project = Project(workspace_id=ws.id, name="P", code="P")
    session.add(project)
    await session.flush()

    p = await perms.project_permissions(session, member.id, ws.id, project.id)
    assert p == frozenset()


@pytest.mark.asyncio
async def test_project_viewer_is_read_only(session):
    ws = await make_workspace(session)
    viewer = await make_user(session, ws, "v@ex.com", SystemRole.MEMBER)
    project = Project(workspace_id=ws.id, name="P", code="P")
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectRole.VIEWER.value)
    )
    await session.flush()

    p = await perms.project_permissions(session, viewer.id, ws.id, project.id)
    assert Perm.TASK_VIEW in p
    assert Perm.TASK_CREATE not in p
    assert Perm.TASK_CHANGE_STATUS not in p


@pytest.mark.asyncio
async def test_project_member_can_work_not_manage(session):
    ws = await make_workspace(session)
    dev = await make_user(session, ws, "d@ex.com", SystemRole.MEMBER)
    project = Project(workspace_id=ws.id, name="P", code="P")
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(project_id=project.id, user_id=dev.id, role=ProjectRole.MEMBER.value)
    )
    await session.flush()

    p = await perms.project_permissions(session, dev.id, ws.id, project.id)
    assert Perm.TASK_CREATE in p
    assert Perm.TASK_CHANGE_STATUS in p
    assert Perm.PROJECT_DELETE not in p
    assert Perm.PROJECT_MEMBERS_MANAGE not in p


@pytest.mark.asyncio
async def test_same_user_different_roles_per_project(session):
    ws = await make_workspace(session)
    u = await make_user(session, ws, "multi@ex.com", SystemRole.MEMBER)
    pa = Project(workspace_id=ws.id, name="A", code="A")
    pb = Project(workspace_id=ws.id, name="B", code="B")
    session.add_all([pa, pb])
    await session.flush()
    session.add(ProjectMember(project_id=pa.id, user_id=u.id, role=ProjectRole.MANAGER.value))
    session.add(ProjectMember(project_id=pb.id, user_id=u.id, role=ProjectRole.VIEWER.value))
    await session.flush()

    pa_perms = await perms.project_permissions(session, u.id, ws.id, pa.id)
    pb_perms = await perms.project_permissions(session, u.id, ws.id, pb.id)
    assert Perm.SPRINT_MANAGE in pa_perms
    assert Perm.SPRINT_MANAGE not in pb_perms
