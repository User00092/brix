from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brix.api as api
from brix.domain import Approval, BrowserTask
from brix.manager import TaskManager
from brix.profiles import ProfileManager
from brix.task_store import TaskStore


def isolated_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, TaskStore, TaskManager]:
    store = TaskStore(tmp_path / "api.db")
    manager = TaskManager(store, ProfileManager(tmp_path / "profiles"), tmp_path)
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "manager", manager)
    return TestClient(api.app), store, manager


def test_http_api_authentication_protects_tasks_but_not_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _manager = isolated_api(tmp_path, monkeypatch)
    monkeypatch.setenv("BRIX_API_TOKEN", "integration-secret")

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.get("/api/v1/tasks", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get("/api/v1/tasks", headers={"Authorization": "Bearer integration-secret"})
    assert response.status_code == 200
    assert response.json() == []


def test_approval_api_decides_once_and_emits_audit_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _manager = isolated_api(tmp_path, monkeypatch)
    task = store.save_task(BrowserTask(task="Submit form", profile="default"))
    approval = store.save_approval(Approval(task_id=task.id, action="submit", risk_level=2))

    response = client.post(f"/api/v1/approvals/{approval.id}", json={"approved": True})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert (
        client.post(f"/api/v1/approvals/{approval.id}", json={"approved": False}).status_code == 409
    )
    approvals = client.get(f"/api/v1/tasks/{task.id}/approvals").json()
    assert approvals[0]["status"] == "approved"
    event = store.events(task.id)[0]
    assert event.type == "approval.approved"
    assert event.data == {"approval_id": approval.id, "action": "submit"}
