from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlmodel import Session, SQLModel, select

from app.auth_api import PrincipalDep
from app.database import get_session
from app.errors import ApiError, ErrorCode, ErrorResponse, conflict, not_found, unauthorized
from app.models import (
    OrgMembership,
    Project,
    ProjectActivityEvent,
    ProjectApprovalRequest,
    ProjectComment,
    ProjectMembership,
    User,
)

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]

ROLE_VALUES = ("viewer", "editor", "admin", "owner")
ROLE_RANK = {role: idx for idx, role in enumerate(ROLE_VALUES)}


class ProjectMemberView(SQLModel):
    user_id: UUID
    email: str
    display_name: Optional[str] = None
    role: str
    added_at: datetime


class ProjectMemberUpsertRequest(SQLModel):
    user_id: Optional[UUID] = None
    email: Optional[str] = None
    role: str = "viewer"


class ProjectMemberRoleUpdateRequest(SQLModel):
    role: str


class ProjectCommentView(SQLModel):
    id: UUID
    project_id: UUID
    author_user_id: UUID
    author_email: Optional[str] = None
    parent_comment_id: Optional[UUID] = None
    body: str
    created_at: datetime
    updated_at: datetime


class ProjectCommentCreateRequest(SQLModel):
    body: str
    parent_comment_id: Optional[UUID] = None


class ProjectApprovalView(SQLModel):
    id: UUID
    project_id: UUID
    status: str
    summary: Optional[str] = None
    requested_by_user_id: UUID
    resolved_by_user_id: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ProjectApprovalCreateRequest(SQLModel):
    summary: Optional[str] = None


class ProjectActivityView(SQLModel):
    id: UUID
    project_id: UUID
    actor_user_id: Optional[UUID] = None
    event_type: str
    payload: dict
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in ROLE_VALUES:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported project role",
            details={"role": role},
        )
    return value


def _project_or_404(session: Session, project_id: UUID, principal) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise not_found("Project not found", {"project_id": str(project_id)})
    if principal.org_id and project.org_id != principal.org_id:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message="Project belongs to a different organization",
            details={"project_id": str(project_id)},
        )
    return project


def _project_membership(session: Session, project_id: UUID, user_id: UUID | None) -> ProjectMembership | None:
    if not user_id:
        return None
    return session.exec(
        select(ProjectMembership).where((ProjectMembership.project_id == project_id) & (ProjectMembership.user_id == user_id))
    ).first()


def _effective_project_role(session: Session, project: Project, principal) -> str | None:
    if not principal.user_id:
        return "owner"
    membership = _project_membership(session, project.id, principal.user_id)
    if membership:
        return membership.role
    if project.owner_user_id == principal.user_id:
        return "owner"
    if principal.org_id and project.org_id == principal.org_id:
        org_membership = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.user_id == principal.user_id))
        ).first()
        if org_membership and org_membership.role in {"owner", "admin"}:
            return "admin"
    return None


def _require_project_role(session: Session, project: Project, principal, min_role: str) -> str:
    role = _effective_project_role(session, project, principal)
    if role is None or ROLE_RANK.get(role, -1) < ROLE_RANK[min_role]:
        raise unauthorized("Project permission denied")
    return role


def _emit_project_activity(
    session: Session,
    *,
    project: Project,
    actor_user_id: UUID | None,
    event_type: str,
    payload: dict,
) -> None:
    session.add(
        ProjectActivityEvent(
            project_id=project.id,
            org_id=project.org_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            payload=payload,
            created_at=_now(),
        )
    )


def _member_view(session: Session, membership: ProjectMembership) -> ProjectMemberView:
    user = session.get(User, membership.user_id)
    if not user:
        raise not_found("User not found", {"user_id": str(membership.user_id)})
    return ProjectMemberView(
        user_id=membership.user_id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        added_at=membership.created_at,
    )


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_project_members(project_id: UUID, session: SessionDep, principal: PrincipalDep) -> list[ProjectMemberView]:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "viewer")
    memberships = session.exec(select(ProjectMembership).where(ProjectMembership.project_id == project_id)).all()
    views = [_member_view(session, item) for item in memberships]
    if not views and project.owner_user_id:
        owner = session.get(User, project.owner_user_id)
        if owner:
            views.append(
                ProjectMemberView(
                    user_id=owner.id,
                    email=owner.email,
                    display_name=owner.display_name,
                    role="owner",
                    added_at=project.created_at,
                )
            )
    return views


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberView,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def add_project_member(
    project_id: UUID,
    payload: ProjectMemberUpsertRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> ProjectMemberView:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "admin")
    role = _normalize_role(payload.role)

    user: User | None = None
    if payload.user_id:
        user = session.get(User, payload.user_id)
    elif payload.email:
        user = session.exec(select(User).where(User.email == payload.email.strip().lower())).first()
    if not user:
        raise not_found("User not found", {"user_id": str(payload.user_id) if payload.user_id else None, "email": payload.email})
    if project.org_id:
        org_membership = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == project.org_id) & (OrgMembership.user_id == user.id))
        ).first()
        if not org_membership:
            raise conflict("User is not an organization member", details={"user_id": str(user.id), "project_id": str(project_id)})

    membership = _project_membership(session, project_id, user.id)
    now = _now()
    if membership is None:
        membership = ProjectMembership(
            project_id=project.id,
            org_id=project.org_id,
            user_id=user.id,
            role=role,
            created_at=now,
            updated_at=now,
        )
    else:
        membership.role = role
        membership.updated_at = now
    session.add(membership)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.member_upserted",
        payload={"user_id": str(user.id), "role": role},
    )
    session.commit()
    session.refresh(membership)
    return _member_view(session, membership)


@router.patch(
    "/projects/{project_id}/members/{user_id}",
    response_model=ProjectMemberView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_project_member_role(
    project_id: UUID,
    user_id: UUID,
    payload: ProjectMemberRoleUpdateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> ProjectMemberView:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "admin")
    membership = _project_membership(session, project_id, user_id)
    if not membership:
        raise not_found("Project member not found", {"project_id": str(project_id), "user_id": str(user_id)})
    membership.role = _normalize_role(payload.role)
    membership.updated_at = _now()
    session.add(membership)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.member_role_updated",
        payload={"user_id": str(user_id), "role": membership.role},
    )
    session.commit()
    session.refresh(membership)
    return _member_view(session, membership)


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def remove_project_member(project_id: UUID, user_id: UUID, session: SessionDep, principal: PrincipalDep) -> Response:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "admin")
    membership = _project_membership(session, project_id, user_id)
    if not membership:
        raise not_found("Project member not found", {"project_id": str(project_id), "user_id": str(user_id)})
    session.delete(membership)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.member_removed",
        payload={"user_id": str(user_id)},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/comments",
    response_model=list[ProjectCommentView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_project_comments(project_id: UUID, session: SessionDep, principal: PrincipalDep) -> list[ProjectCommentView]:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "viewer")
    comments = session.exec(
        select(ProjectComment).where(ProjectComment.project_id == project_id).order_by(ProjectComment.created_at.asc())
    ).all()
    views: list[ProjectCommentView] = []
    for comment in comments:
        author = session.get(User, comment.author_user_id)
        views.append(
            ProjectCommentView(
                id=comment.id,
                project_id=comment.project_id,
                author_user_id=comment.author_user_id,
                author_email=author.email if author else None,
                parent_comment_id=comment.parent_comment_id,
                body=comment.body,
                created_at=comment.created_at,
                updated_at=comment.updated_at,
            )
        )
    return views


@router.post(
    "/projects/{project_id}/comments",
    response_model=ProjectCommentView,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def create_project_comment(
    project_id: UUID,
    payload: ProjectCommentCreateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> ProjectCommentView:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "viewer")
    if not principal.user_id:
        raise unauthorized("Authentication required")
    body = (payload.body or "").strip()
    if not body:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Comment body is required",
            details={"field": "body"},
        )
    if payload.parent_comment_id:
        parent = session.get(ProjectComment, payload.parent_comment_id)
        if not parent or parent.project_id != project_id:
            raise not_found("Parent comment not found", {"comment_id": str(payload.parent_comment_id)})
    comment = ProjectComment(
        project_id=project_id,
        org_id=project.org_id,
        author_user_id=principal.user_id,
        parent_comment_id=payload.parent_comment_id,
        body=body,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(comment)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.comment_created",
        payload={"comment_id": str(comment.id), "parent_comment_id": str(payload.parent_comment_id) if payload.parent_comment_id else None},
    )
    session.commit()
    session.refresh(comment)
    author = session.get(User, comment.author_user_id)
    return ProjectCommentView(
        id=comment.id,
        project_id=comment.project_id,
        author_user_id=comment.author_user_id,
        author_email=author.email if author else None,
        parent_comment_id=comment.parent_comment_id,
        body=comment.body,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.delete(
    "/projects/{project_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_project_comment(project_id: UUID, comment_id: UUID, session: SessionDep, principal: PrincipalDep) -> Response:
    project = _project_or_404(session, project_id, principal)
    role = _require_project_role(session, project, principal, "viewer")
    comment = session.get(ProjectComment, comment_id)
    if not comment or comment.project_id != project_id:
        raise not_found("Project comment not found", {"comment_id": str(comment_id)})
    if principal.user_id != comment.author_user_id and ROLE_RANK.get(role, 0) < ROLE_RANK["admin"]:
        raise unauthorized("Only the comment author or project admins can delete this comment")
    session.delete(comment)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.comment_deleted",
        payload={"comment_id": str(comment_id)},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/approvals/request",
    response_model=ProjectApprovalView,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def request_project_approval(
    project_id: UUID,
    payload: ProjectApprovalCreateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> ProjectApprovalView:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "editor")
    if not principal.user_id:
        raise unauthorized("Authentication required")
    approval = ProjectApprovalRequest(
        project_id=project_id,
        org_id=project.org_id,
        requested_by_user_id=principal.user_id,
        status="pending",
        summary=(payload.summary or "").strip() or None,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(approval)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type="project.approval_requested",
        payload={"approval_id": str(approval.id)},
    )
    session.commit()
    session.refresh(approval)
    return ProjectApprovalView(**approval.model_dump())


def _resolve_project_approval(
    *,
    project_id: UUID,
    approval_id: UUID,
    resolved_status: str,
    session: Session,
    principal,
) -> ProjectApprovalView:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "admin")
    if not principal.user_id:
        raise unauthorized("Authentication required")
    approval = session.get(ProjectApprovalRequest, approval_id)
    if not approval or approval.project_id != project_id:
        raise not_found("Project approval request not found", {"approval_id": str(approval_id)})
    if approval.status != "pending":
        raise conflict("Approval request is already resolved", details={"status": approval.status})
    approval.status = resolved_status
    approval.resolved_by_user_id = principal.user_id
    approval.resolved_at = _now()
    approval.updated_at = _now()
    session.add(approval)
    _emit_project_activity(
        session,
        project=project,
        actor_user_id=principal.user_id,
        event_type=f"project.approval_{resolved_status}",
        payload={"approval_id": str(approval.id), "requested_by_user_id": str(approval.requested_by_user_id)},
    )
    session.commit()
    session.refresh(approval)
    return ProjectApprovalView(**approval.model_dump())


@router.post(
    "/projects/{project_id}/approvals/{approval_id}/approve",
    response_model=ProjectApprovalView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def approve_project_approval(project_id: UUID, approval_id: UUID, session: SessionDep, principal: PrincipalDep) -> ProjectApprovalView:
    return _resolve_project_approval(
        project_id=project_id,
        approval_id=approval_id,
        resolved_status="approved",
        session=session,
        principal=principal,
    )


@router.post(
    "/projects/{project_id}/approvals/{approval_id}/reject",
    response_model=ProjectApprovalView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def reject_project_approval(project_id: UUID, approval_id: UUID, session: SessionDep, principal: PrincipalDep) -> ProjectApprovalView:
    return _resolve_project_approval(
        project_id=project_id,
        approval_id=approval_id,
        resolved_status="rejected",
        session=session,
        principal=principal,
    )


@router.get(
    "/projects/{project_id}/activity",
    response_model=list[ProjectActivityView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_project_activity(project_id: UUID, session: SessionDep, principal: PrincipalDep, limit: int = 100) -> list[ProjectActivityView]:
    project = _project_or_404(session, project_id, principal)
    _require_project_role(session, project, principal, "viewer")
    clamped_limit = max(1, min(limit, 300))
    events = session.exec(
        select(ProjectActivityEvent)
        .where(ProjectActivityEvent.project_id == project_id)
        .order_by(ProjectActivityEvent.created_at.desc())
        .limit(clamped_limit)
    ).all()
    return [ProjectActivityView(**event.model_dump()) for event in events]
