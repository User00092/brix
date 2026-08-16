from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    USER_CONTROLLED = "user_controlled"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ControlState(StrEnum):
    AGENT_CONTROLLED = "agent_controlled"
    USER_CONTROLLED = "user_controlled"
    WAITING_FOR_USER = "waiting_for_user"
    PAUSED = "paused"


class FailureReason(StrEnum):
    NAVIGATION_FAILED = "navigation_failed"
    ELEMENT_NOT_FOUND = "element_not_found"
    BROWSER_CRASHED = "browser_crashed"
    TIMEOUT = "timeout"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CAPTCHA = "captcha"
    MFA = "mfa"
    PERMISSION_DENIED = "permission_denied"
    USER_CANCELLED = "user_cancelled"
    SITE_ERROR = "site_error"
    VERIFICATION_FAILED = "verification_failed"


class PermissionDecision(StrEnum):
    AUTO = "auto"
    ASK = "ask"
    DENY = "deny"


class TaskPermissions(BaseModel):
    allow_navigation: bool = True
    allow_login: bool = True
    allow_form_submission: bool = False
    allow_messages: bool = False
    allow_account_changes: bool = False
    allow_purchase: bool = False
    level_0: PermissionDecision = PermissionDecision.AUTO
    level_1: PermissionDecision = PermissionDecision.AUTO
    level_2: PermissionDecision = PermissionDecision.ASK
    level_3: PermissionDecision = PermissionDecision.DENY


class CreateTask(BaseModel):
    task: str = Field(min_length=1, max_length=50_000)
    profile: str = Field(default="default", pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    caller: str = Field(default="api", max_length=80)
    permissions: TaskPermissions = Field(default_factory=TaskPermissions)
    trace: bool = False
    timeout_seconds: int = Field(default=900, ge=10, le=86_400)


class TaskResult(BaseModel):
    success: bool
    summary: str
    final_url: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class BrowserTask(BaseModel):
    id: str = Field(default_factory=lambda: identifier("tsk"))
    task: str
    profile: str
    caller: str = "api"
    permissions: TaskPermissions = Field(default_factory=TaskPermissions)
    trace: bool = False
    timeout_seconds: int = 900
    status: TaskStatus = TaskStatus.QUEUED
    browser_session_id: str | None = None
    challenge_reason: FailureReason | None = None
    current_url: str | None = None
    codex_thread_id: str | None = None
    codex_turn_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    verification_passed: bool = False


class BrowserSession(BaseModel):
    id: str = Field(default_factory=lambda: identifier("bs"))
    task_id: str
    profile: str
    state: ControlState = ControlState.AGENT_CONTROLLED
    current_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_activity_at: datetime = Field(default_factory=utc_now)


class TaskEvent(BaseModel):
    id: int | None = None
    task_id: str
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Profile(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    display_name: str
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime | None = None
    locked_by: str | None = None


class Approval(BaseModel):
    id: str = Field(default_factory=lambda: identifier("apr"))
    task_id: str
    action: str
    risk_level: int = Field(ge=0, le=3)
    status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalDecision(BaseModel):
    approved: bool
