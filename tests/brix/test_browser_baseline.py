from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from brix.domain import (
    BrowserSession,
    BrowserTask,
    ControlState,
    CreateTask,
    FailureReason,
    PermissionDecision,
    TaskEvent,
    TaskPermissions,
    TaskResult,
    TaskStatus,
)
from brix.manager import TaskManager
from brix.permissions import PermissionDenied, PermissionPolicy, PermissionRequired
from brix.profiles import ProfileManager
from brix.remote import RemoteAccessTokens
from brix.task_store import TaskStore


def make_store(root: Path) -> TaskStore:
    return TaskStore(root / "browser-baseline.db")


def test_task_models_supply_browser_defaults_and_validate_api_input() -> None:
    payload = CreateTask(task="Open the account page")
    task = BrowserTask(**payload.model_dump())

    assert task.id.startswith("tsk_")
    assert task.status == TaskStatus.QUEUED
    assert task.permissions.level_2 == PermissionDecision.ASK
    assert task.created_at.tzinfo is not None

    for invalid in (
        {"task": ""},
        {"task": "ok", "profile": "bad profile"},
        {"task": "ok", "timeout_seconds": 9},
        {"task": "ok", "timeout_seconds": 86_401},
    ):
        with pytest.raises(ValidationError):
            CreateTask.model_validate(invalid)


def test_task_api_returns_validation_errors_before_queueing() -> None:
    from fastapi.testclient import TestClient

    from brix.api import app

    client = TestClient(app)
    response = client.post("/api/v1/tasks", json={"task": "", "profile": "bad profile"})

    assert response.status_code == 422
    fields = {tuple(error["loc"]) for error in response.json()["detail"]}
    assert ("body", "task") in fields
    assert ("body", "profile") in fields


def test_task_result_and_challenge_state_round_trip_through_sqlite(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = BrowserTask(task="Sign in", profile="personal")
    store.save_task(task)
    task.status = TaskStatus.WAITING_FOR_USER
    task.challenge_reason = FailureReason.MFA
    task.result = TaskResult(success=False, summary="Waiting", error="MFA required")
    store.save_task(task)

    restored = store.get_task(task.id)
    assert restored == task
    assert restored is not None and restored.challenge_reason == FailureReason.MFA


def test_sqlite_task_session_event_and_approval_lifecycle(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    older = store.save_task(BrowserTask(task="First", profile="default"))
    newer = store.save_task(BrowserTask(task="Second", profile="default"))
    session = store.save_session(BrowserSession(task_id=newer.id, profile="default"))
    first = store.add_event(TaskEvent(task_id=newer.id, type="task.queued", message="Queued"))
    second = store.add_event(TaskEvent(task_id=newer.id, type="task.started", message="Started"))

    assert {item.id for item in store.list_tasks()} == {older.id, newer.id}
    assert store.get_session(session.id) == session
    assert [event.id for event in store.events(newer.id)] == [first.id, second.id]
    assert store.events(newer.id, after=first.id or 0) == [second]
    assert store.get_task("missing") is None


def test_permissions_auto_ask_deny_and_capability_flags(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    policy = PermissionPolicy(store)
    task = BrowserTask(task="Interact", profile="default")

    assert policy.enforce(task, "navigate") == 0
    with pytest.raises(PermissionDenied, match="Form submission"):
        policy.enforce(task, "submit")

    task.permissions.allow_form_submission = True
    with pytest.raises(PermissionRequired) as requested:
        policy.enforce(task, "submit")
    approval = requested.value.approval
    assert store.get_approval(approval.id) == approval

    with pytest.raises(PermissionDenied, match="Risk level 3"):
        policy.enforce(task, "unknown_action")


def test_signed_remote_tokens_reject_wrong_session_tampering_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 1_700_000_000
    monkeypatch.setattr("brix.remote.time.time", lambda: clock)
    tokens = RemoteAccessTokens("x" * 32, ttl_seconds=30)
    token, expires = tokens.create("session-1")

    assert expires == clock + 30
    assert tokens.verify(token, "session-1")
    assert not tokens.verify(token, "session-2")
    assert not tokens.verify(token[:-1] + ("0" if token[-1] != "0" else "1"), "session-1")
    monkeypatch.setattr("brix.remote.time.time", lambda: clock + 31)
    assert not tokens.verify(token, "session-1")
    assert not tokens.verify("malformed", "session-1")


def test_remote_token_secret_has_minimum_strength() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        RemoteAccessTokens("too-short")


class FakeWorker:
    def __init__(self, session: BrowserSession) -> None:
        self.session = session
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, arguments))
        return {"path": arguments.get("name", action)}

    async def set_control(self, state: ControlState) -> None:
        self.session.state = state

    async def snapshot(self) -> dict[str, Any]:
        return {"url": self.session.current_url, "elements": []}

    async def detect_challenge(self) -> dict[str, Any]:
        return {"detected": False}

    async def close(self) -> None:
        pass


class FakeBackend:
    def __init__(self) -> None:
        self.resumed: list[tuple[str, dict[str, Any]]] = []

    async def resume_task(self, task: BrowserTask, snapshot: dict[str, Any]) -> None:
        self.resumed.append((task.id, snapshot))


def manager_with_active_task(root: Path) -> tuple[TaskManager, BrowserTask, FakeWorker, FakeBackend]:
    store = make_store(root)
    profiles = ProfileManager(root / "profiles")
    manager = TaskManager(store, profiles, root)
    task = store.save_task(BrowserTask(task="Handle challenge", profile="default", status=TaskStatus.RUNNING))
    session = store.save_session(BrowserSession(task_id=task.id, profile=task.profile, current_url="https://example.test/"))
    worker = FakeWorker(session)
    backend = FakeBackend()
    manager.workers[task.id] = worker  # type: ignore[assignment]
    manager.backend = backend  # type: ignore[assignment]
    return manager, task, worker, backend


@pytest.mark.asyncio
async def test_manager_human_challenge_and_control_handoff(tmp_path: Path) -> None:
    manager, task, worker, backend = manager_with_active_task(tmp_path)

    await manager.request_human(task.id, FailureReason.CAPTCHA, "Solve challenge")
    waiting = manager.store.get_task(task.id)
    assert waiting is not None and waiting.status == TaskStatus.WAITING_FOR_USER
    assert waiting.challenge_reason == FailureReason.CAPTCHA
    assert worker.session.state == ControlState.WAITING_FOR_USER

    controlled = await manager.take_control(task.id)
    assert controlled.status == TaskStatus.USER_CONTROLLED
    assert worker.session.state == ControlState.USER_CONTROLLED

    resumed = await manager.return_control(task.id)
    assert resumed.status == TaskStatus.RUNNING
    assert resumed.challenge_reason is None
    assert worker.session.state == ControlState.AGENT_CONTROLLED
    assert backend.resumed == [(task.id, {"url": "https://example.test/", "elements": []})]
    assert [event.type for event in manager.store.events(task.id)] == [
        "task.waiting_for_user",
        "browser.user_controlled",
        "task.resumed",
    ]


@pytest.mark.asyncio
async def test_manager_queue_create_and_complete_without_live_browser(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    manager = TaskManager(store, ProfileManager(tmp_path / "profiles"), tmp_path)
    task = await manager.create(CreateTask(task="Capture the page", profile="default"))
    assert await manager.queue.get() == task.id
    manager.queue.task_done()
    session = store.save_session(BrowserSession(task_id=task.id, profile=task.profile, current_url="https://example.test/done"))
    worker = FakeWorker(session)
    manager.workers[task.id] = worker  # type: ignore[assignment]
    task.status = TaskStatus.RUNNING
    store.save_task(task)

    completed = await manager.complete(task.id, TaskResult(success=True, summary="Captured"))
    assert completed.status == TaskStatus.COMPLETED
    assert completed.result is not None and completed.result.final_url is None
    assert completed.result.artifacts == [{"type": "screenshot", "path": "final.png"}]
    assert (tmp_path / "runs" / task.id / "result.json").is_file()
    assert task.id not in manager.workers


@pytest.mark.asyncio
async def test_execute_tool_blocks_non_running_tasks(tmp_path: Path) -> None:
    manager, task, _worker, _backend = manager_with_active_task(tmp_path)
    task.status = TaskStatus.PAUSED
    manager.store.save_task(task)
    with pytest.raises(RuntimeError, match="blocked while task is paused"):
        await manager.execute_tool(task.id, "snapshot", {})
