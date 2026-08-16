from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from brix.backend import AgentBackend
from brix.browser import BrowserWorker
from brix.domain import (
    BrowserSession,
    BrowserTask,
    ControlState,
    CreateTask,
    FailureReason,
    TaskEvent,
    TaskResult,
    TaskStatus,
    utc_now,
)
from brix.permissions import PermissionDenied, PermissionPolicy, PermissionRequired
from brix.profiles import ProfileManager
from brix.task_store import TaskStore

Subscriber = Callable[[TaskEvent], Awaitable[None]]
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}
VERIFICATION_ACTIONS = {"assert_text", "assert_url", "assert_element"}
OBSERVATION_ACTIONS = {
    "snapshot",
    "get_text",
    "tabs",
    "storage",
    "screenshot",
    "detect_challenge",
    "wait_for",
}


class TaskManager:
    def __init__(
        self,
        store: TaskStore,
        profiles: ProfileManager,
        data_root: Path,
        *,
        max_workers: int = 2,
        browser_factory: Any = BrowserWorker,
    ) -> None:
        self.store, self.profiles, self.data_root = store, profiles, data_root
        self.max_workers, self.browser_factory = max_workers, browser_factory
        self.backend: AgentBackend | None = None
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: dict[str, BrowserWorker] = {}
        self.runners: list[asyncio.Task[None]] = []
        self._background_tasks: set[asyncio.Task[None]] = set()
        self.subscribers: dict[str, set[Subscriber]] = defaultdict(set)
        self.policy = PermissionPolicy(store)

    def set_backend(self, backend: AgentBackend) -> None:
        self.backend = backend

    async def start(self) -> None:
        for task in self.store.list_tasks():
            if task.status not in TERMINAL:
                task.status = TaskStatus.QUEUED
                self.store.save_task(task)
                await self.queue.put(task.id)
        self.runners = [asyncio.create_task(self._runner()) for _ in range(self.max_workers)]

    async def close(self) -> None:
        for runner in self.runners:
            runner.cancel()
        await asyncio.gather(*self.runners, return_exceptions=True)
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        for worker in list(self.workers.values()):
            await worker.close()
        if self.backend:
            await self.backend.close()

    async def create(self, payload: CreateTask) -> BrowserTask:
        task = self.store.save_task(BrowserTask(**payload.model_dump()))
        run_dir = self.data_root / "runs" / task.id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "task.json").write_text(
            json.dumps(task.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        await self.emit(
            TaskEvent(task_id=task.id, type="task.queued", message="Browser task queued")
        )
        await self.queue.put(task.id)
        return task

    async def _runner(self) -> None:
        while True:
            task_id = await self.queue.get()
            try:
                await self._launch(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.fail(task_id, FailureReason.BROWSER_CRASHED, str(error))
            finally:
                self.queue.task_done()

    async def _launch(self, task_id: str) -> None:
        task = self._task(task_id)
        task.status, task.started_at = TaskStatus.STARTING, utc_now()
        self.store.save_task(task)
        await self.emit(
            TaskEvent(task_id=task.id, type="task.started", message="Starting browser worker")
        )
        self.profiles.acquire(task.profile, task.id)
        session = self.store.save_session(BrowserSession(task_id=task.id, profile=task.profile))
        task.browser_session_id = session.id
        run_dir = self.data_root / "runs" / task.id
        worker = self.browser_factory(
            session, self.profiles.user_data_dir(task.profile), run_dir, trace=task.trace
        )
        self.workers[task.id] = worker
        try:
            await worker.start()
            await worker.execute("screenshot", {"name": "start.png"})
            task.status = TaskStatus.RUNNING
            self.store.save_task(task)
            self.store.save_session(session)
            await self.emit(
                TaskEvent(
                    task_id=task.id,
                    type="browser.started",
                    message="Chromium browser started",
                    data={"browser_session_id": session.id},
                )
            )
            if not self.backend:
                raise RuntimeError("No agent backend configured")
            await self.backend.start_task(task)
            self.store.save_task(task)
            timeout_task = asyncio.create_task(self._timeout(task.id, task.timeout_seconds))
            self._background_tasks.add(timeout_task)
            timeout_task.add_done_callback(self._background_tasks.discard)
        except Exception:
            await worker.close()
            self.workers.pop(task.id, None)
            self.profiles.release(task.profile, task.id)
            raise

    async def execute_tool(
        self, task_id: str, action: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        task, worker = self._task(task_id), self._worker(task_id)
        if task.status != TaskStatus.RUNNING:
            raise RuntimeError(f"Browser actions are blocked while task is {task.status}")
        if action == "request_human":
            reason = FailureReason(arguments.get("reason", "authentication_required"))
            await self.request_human(
                task_id, reason, str(arguments.get("message", "Human interaction required"))
            )
            return {"status": "waiting_for_user", "reason": reason}
        if action == "complete":
            success = bool(arguments["success"])
            if success and not task.verification_passed:
                raise RuntimeError(
                    "Successful completion requires a passing browser assertion "
                    "after the last action"
                )
            await self.complete(
                task_id,
                TaskResult(
                    success=success,
                    summary=str(arguments["summary"]),
                    extracted_data=arguments.get("extracted_data") or {},
                    final_url=worker.session.current_url,
                ),
            )
            return {"status": "completed"}
        try:
            risk = self.policy.enforce(task, action)
        except PermissionRequired as error:
            await self.emit(
                TaskEvent(
                    task_id=task.id,
                    type="approval.required",
                    message=str(error),
                    data=error.approval.model_dump(mode="json"),
                )
            )
            raise
        except PermissionDenied as error:
            await self.emit(
                TaskEvent(
                    task_id=task.id,
                    type="browser.permission_denied",
                    message=str(error),
                    data={"action": action},
                )
            )
            raise
        result = await worker.execute(action, arguments)
        if action in VERIFICATION_ACTIONS:
            task.verification_passed = result.get("passed") is True
        elif action not in OBSERVATION_ACTIONS:
            task.verification_passed = False
        task.current_url = worker.session.current_url
        self.store.save_task(task)
        self.store.save_session(worker.session)
        await self.emit(
            TaskEvent(
                task_id=task.id,
                type=f"browser.{action}",
                message=f"Browser {action}",
                data={"risk_level": risk, "result": result},
            )
        )
        if action not in {"snapshot", "detect_challenge", "assert_text", "assert_url"}:
            challenge = await worker.detect_challenge()
            if challenge["detected"]:
                await self.request_human(
                    task_id,
                    FailureReason(challenge["reason"]),
                    "Human verification is required before the task can continue.",
                )
        return result

    async def take_control(self, task_id: str) -> BrowserTask:
        task, worker = self._task(task_id), self._worker(task_id)
        await worker.set_control(ControlState.USER_CONTROLLED)
        task.status = TaskStatus.USER_CONTROLLED
        self.store.save_session(worker.session)
        self.store.save_task(task)
        await self.emit(
            TaskEvent(task_id=task.id, type="browser.user_controlled", message="User took control")
        )
        return task

    async def return_control(self, task_id: str) -> BrowserTask:
        task, worker = self._task(task_id), self._worker(task_id)
        task.status = TaskStatus.RESUMING
        self.store.save_task(task)
        await worker.set_control(ControlState.AGENT_CONTROLLED)
        snapshot = await worker.snapshot()
        await worker.execute("screenshot", {"name": "human-handoff.png"})
        task.status, task.challenge_reason = TaskStatus.RUNNING, None
        self.store.save_session(worker.session)
        self.store.save_task(task)
        await self.emit(
            TaskEvent(task_id=task.id, type="task.resumed", message="Control returned to agent")
        )
        if self.backend:
            await self.backend.resume_task(task, snapshot)
        return task

    async def pause(self, task_id: str) -> BrowserTask:
        task, worker = self._task(task_id), self._worker(task_id)
        await worker.set_control(ControlState.PAUSED)
        task.status = TaskStatus.PAUSED
        self.store.save_task(task)
        self.store.save_session(worker.session)
        return task

    async def request_human(self, task_id: str, reason: FailureReason, message: str) -> None:
        task, worker = self._task(task_id), self._worker(task_id)
        await worker.execute("screenshot", {"name": "human-required.png"})
        await worker.set_control(ControlState.WAITING_FOR_USER)
        task.status, task.challenge_reason = TaskStatus.WAITING_FOR_USER, reason
        self.store.save_task(task)
        self.store.save_session(worker.session)
        await self.emit(
            TaskEvent(
                task_id=task.id,
                type="task.waiting_for_user",
                message=message,
                data={"reason": reason, "browser_session_id": worker.session.id},
            )
        )

    async def complete(self, task_id: str, result: TaskResult) -> BrowserTask:
        task = self._task(task_id)
        worker = self._worker(task_id)
        if result.success and not task.verification_passed:
            raise RuntimeError(
                "Successful completion requires a passing browser assertion after the last action"
            )
        shot = await worker.execute("screenshot", {"name": "final.png"})
        result.artifacts.append({"type": "screenshot", **shot})
        task.status, task.result, task.completed_at = TaskStatus.COMPLETED, result, utc_now()
        self.store.save_task(task)
        run_dir = self.data_root / "runs" / task.id
        (run_dir / "result.json").write_text(
            json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        await self.emit(TaskEvent(task_id=task.id, type="task.completed", message=result.summary))
        await self._release(task)
        return task

    async def cancel(self, task_id: str) -> BrowserTask:
        task = self._task(task_id)
        if task.status in TERMINAL:
            return task
        if self.backend:
            await self.backend.cancel_task(task)
        task.status, task.completed_at = TaskStatus.CANCELLED, utc_now()
        task.result = TaskResult(
            success=False, summary="Task cancelled", error=FailureReason.USER_CANCELLED
        )
        self.store.save_task(task)
        await self.emit(TaskEvent(task_id=task.id, type="task.cancelled", message="Task cancelled"))
        await self._release(task)
        return task

    async def fail(self, task_id: str, reason: FailureReason, message: str) -> None:
        task = self.store.get_task(task_id)
        if not task or task.status in TERMINAL:
            return
        task.status, task.completed_at = TaskStatus.FAILED, utc_now()
        task.result = TaskResult(
            success=False, summary="Browser task failed", error=f"{reason}: {message}"
        )
        self.store.save_task(task)
        await self.emit(
            TaskEvent(task_id=task.id, type="task.failed", message=message, data={"reason": reason})
        )
        await self._release(task)

    async def _timeout(self, task_id: str, seconds: int) -> None:
        await asyncio.sleep(seconds)
        task = self.store.get_task(task_id)
        if task and task.status not in TERMINAL:
            task.status = TaskStatus.TIMED_OUT
            self.store.save_task(task)
            await self.emit(
                TaskEvent(task_id=task.id, type="task.timed_out", message="Task timed out")
            )
            await self._release(task)

    async def _release(self, task: BrowserTask) -> None:
        worker = self.workers.pop(task.id, None)
        if worker:
            await worker.close()
        self.profiles.release(task.profile, task.id)

    async def emit(self, event: TaskEvent) -> None:
        self.store.add_event(event)
        run_dir = self.data_root / "runs" / event.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "browser-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.model_dump(mode="json"), separators=(",", ":")) + "\n")
        await asyncio.gather(
            *(callback(event) for callback in self.subscribers[event.task_id]),
            return_exceptions=True,
        )

    def subscribe(self, task_id: str, callback: Subscriber) -> None:
        self.subscribers[task_id].add(callback)

    def unsubscribe(self, task_id: str, callback: Subscriber) -> None:
        self.subscribers[task_id].discard(callback)

    def _task(self, task_id: str) -> BrowserTask:
        task = self.store.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        return task

    def _worker(self, task_id: str) -> BrowserWorker:
        if task_id not in self.workers:
            raise KeyError(f"No active browser for {task_id}")
        return self.workers[task_id]

    async def handle_codex_event(self, payload: dict[str, Any]) -> None:
        params = payload.get("params", {})
        thread_id = params.get("threadId")
        task = next(
            (item for item in self.store.list_tasks() if item.codex_thread_id == thread_id), None
        )
        if task:
            await self.emit(
                TaskEvent(
                    task_id=task.id,
                    type="agent.event",
                    message=str(payload.get("method", "Codex event")),
                    data={"event": payload},
                )
            )
