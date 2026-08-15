from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from brix.backend import CodexAppServerBackend
from brix.domain import CreateTask, TaskEvent, TaskStatus
from brix.manager import TaskManager
from brix.profiles import ProfileManager
from brix.remote import RemoteAccessTokens
from brix.task_store import TaskStore

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
DATA_ROOT = Path(os.environ.get("BRIX_DATA_DIR", ".brix")).resolve()
store = TaskStore(Path(os.environ.get("BRIX_DATABASE", str(DATA_ROOT / "brix.db"))).resolve())
profiles = ProfileManager(DATA_ROOT / "profiles")
manager = TaskManager(store, profiles, DATA_ROOT, max_workers=int(os.environ.get("BRIX_MAX_BROWSER_WORKERS", "2")))
remote_tokens = RemoteAccessTokens(os.environ.get("BRIX_SECRET_KEY", "development-only-secret-change-me-123456"))
backend = CodexAppServerBackend(os.environ.get("BRIX_CODEX_EXECUTABLE", "codex"), DATA_ROOT, manager.execute_tool, manager.handle_codex_event)
manager.set_backend(backend)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await manager.start()
    yield
    await manager.close()


app = FastAPI(title="Brix API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def authentication(request: Request, call_next: Any) -> Any:
    expected = os.environ.get("BRIX_API_TOKEN")
    public = request.url.path in {"/api/health"} or request.url.path.startswith("/remote/")
    if expected and not public and request.headers.get("Authorization") != f"Bearer {expected}":
        return HTMLResponse("Unauthorized", status_code=401)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def required_task(task_id: str) -> Any:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


@app.get("/api/health")
async def health() -> dict[str, str]: return {"status": "ok", "service": "brix"}


@app.post("/api/v1/tasks", status_code=201)
async def create_task(payload: CreateTask) -> dict[str, Any]:
    task = await manager.create(payload)
    return {"task_id": task.id, "status": task.status}


@app.get("/api/v1/tasks")
async def list_tasks() -> list[dict[str, Any]]: return [item.model_dump(mode="json") for item in store.list_tasks()]


@app.get("/api/v1/tasks/{task_id}")
async def task_status(task_id: str) -> dict[str, Any]: return required_task(task_id).model_dump(mode="json")


@app.get("/api/v1/tasks/{task_id}/result")
async def task_result(task_id: str) -> dict[str, Any]:
    task = required_task(task_id)
    if not task.result:
        raise HTTPException(409, "Task has no result yet")
    return {"task_id": task.id, "status": task.status, **task.result.model_dump(mode="json")}


@app.post("/api/v1/tasks/{task_id}/cancel")
async def cancel(task_id: str) -> dict[str, Any]: return (await manager.cancel(task_id)).model_dump(mode="json")


@app.post("/api/v1/tasks/{task_id}/pause")
async def pause(task_id: str) -> dict[str, Any]: return (await manager.pause(task_id)).model_dump(mode="json")


@app.post("/api/v1/tasks/{task_id}/resume")
async def resume(task_id: str) -> dict[str, Any]: return (await manager.return_control(task_id)).model_dump(mode="json")


@app.post("/api/v1/tasks/{task_id}/retry", status_code=201)
async def retry(task_id: str) -> dict[str, Any]:
    old = required_task(task_id)
    if old.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}:
        raise HTTPException(409, "Only terminal failed tasks can be retried")
    return (await manager.create(CreateTask(task=old.task, profile=old.profile, caller=old.caller, permissions=old.permissions, trace=old.trace, timeout_seconds=old.timeout_seconds))).model_dump(mode="json")


@app.websocket("/api/v1/tasks/{task_id}/events")
async def events(websocket: WebSocket, task_id: str) -> None:
    expected = os.environ.get("BRIX_API_TOKEN")
    if expected and websocket.headers.get("Authorization") != f"Bearer {expected}" and websocket.query_params.get("token") != expected:
        await websocket.close(code=4401); return
    if not store.get_task(task_id): await websocket.close(code=4404); return
    await websocket.accept()
    async def send(event: TaskEvent) -> None: await websocket.send_json(event.model_dump(mode="json"))
    manager.subscribe(task_id, send)
    try:
        await websocket.send_json({"type": "snapshot", "task": required_task(task_id).model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in store.events(task_id)]})
        while True:
            if await websocket.receive_text() == "ping": await websocket.send_text("pong")
    except WebSocketDisconnect: pass
    finally: manager.unsubscribe(task_id, send)


@app.get("/api/v1/browser-sessions")
async def browser_sessions() -> list[dict[str, Any]]: return [item.model_dump(mode="json") for item in store.list_sessions()]


@app.post("/api/v1/browser-sessions/{session_id}/take-control")
async def take_control(session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if not session: raise HTTPException(404, "Browser session not found")
    return (await manager.take_control(session.task_id)).model_dump(mode="json")


@app.post("/api/v1/browser-sessions/{session_id}/return-to-agent")
async def return_to_agent(session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if not session: raise HTTPException(404, "Browser session not found")
    return (await manager.return_control(session.task_id)).model_dump(mode="json")


@app.get("/api/v1/browser-sessions/{session_id}/remote-access")
async def remote_access(session_id: str) -> dict[str, Any]:
    if not store.get_session(session_id): raise HTTPException(404, "Browser session not found")
    token, expires = remote_tokens.create(session_id)
    return {"session_id": session_id, "url": f"/remote/{session_id}?token={token}", "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}


@app.get("/remote/{session_id}", response_class=HTMLResponse)
async def remote_view(session_id: str, token: str) -> str:
    if not remote_tokens.verify(token, session_id): raise HTTPException(401, "Invalid or expired remote access token")
    novnc = os.environ.get("BRIX_NOVNC_INTERNAL_URL", "")
    if not novnc:
        return "<main style='font:16px system-ui;padding:2rem'><h1>Brix live browser</h1><p>The browser session is active, but noVNC is not configured. Set BRIX_NOVNC_INTERNAL_URL to the authenticated internal gateway.</p></main>"
    return f"<iframe title='Brix live browser' src='{novnc}' style='position:fixed;inset:0;width:100%;height:100%;border:0'></iframe>"


class ProfileInput(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    display_name: str | None = Field(default=None, max_length=120)


@app.get("/api/v1/profiles")
async def list_profiles() -> list[dict[str, Any]]: return [item.model_dump(mode="json") for item in profiles.list()]


@app.post("/api/v1/profiles", status_code=201)
async def create_profile(payload: ProfileInput) -> dict[str, Any]:
    try: return profiles.create(payload.id, payload.display_name).model_dump(mode="json")
    except FileExistsError as error: raise HTTPException(409, "Profile already exists") from error


@app.delete("/api/v1/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: str) -> None:
    try: profiles.delete(profile_id)
    except KeyError as error: raise HTTPException(404, "Profile not found") from error
    except RuntimeError as error: raise HTTPException(409, str(error)) from error


@app.get("/api/v1/tasks/{task_id}/artifacts/{path:path}")
async def artifact(task_id: str, path: str) -> FileResponse:
    required_task(task_id)
    root = (DATA_ROOT / "runs" / task_id).resolve(); target = (root / path).resolve()
    if root not in target.parents or not target.is_file(): raise HTTPException(404, "Artifact not found")
    return FileResponse(target)


app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str) -> FileResponse: return FileResponse(STATIC_ROOT / "index.html")
