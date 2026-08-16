from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from brix.codex import CodexAppServer
from brix.domain import BrowserTask
from brix.prompts import BROWSER_AGENT_INSTRUCTIONS

ToolHandler = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class AgentBackend(ABC):
    @abstractmethod
    async def start_task(self, task: BrowserTask) -> None: ...

    @abstractmethod
    async def resume_task(self, task: BrowserTask, context: dict[str, Any]) -> None: ...

    @abstractmethod
    async def cancel_task(self, task: BrowserTask) -> None: ...

    @abstractmethod
    async def send_context(self, task: BrowserTask, context: dict[str, Any]) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


def _function(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


BROWSER_TOOLS = [
    {
        "type": "namespace",
        "name": "browser",
        "description": (
            "Operate the isolated Brix browser. Observe after every meaningful action "
            "and verify before completing."
        ),
        "tools": [
            _function(
                "navigate", "Navigate to an HTTP(S) URL.", {"url": {"type": "string"}}, ["url"]
            ),
            _function("back", "Navigate back.", {}, []),
            _function("forward", "Navigate forward.", {}, []),
            _function("reload", "Reload.", {}, []),
            _function(
                "snapshot", "Get a compact semantic snapshot with stable element IDs.", {}, []
            ),
            _function(
                "click",
                "Click a semantic element.",
                {"element_id": {"type": "string"}},
                ["element_id"],
            ),
            _function(
                "fill",
                "Replace a field value.",
                {"element_id": {"type": "string"}, "value": {"type": "string"}},
                ["element_id", "value"],
            ),
            _function(
                "type",
                "Type into a field.",
                {"element_id": {"type": "string"}, "value": {"type": "string"}},
                ["element_id", "value"],
            ),
            _function(
                "press",
                "Press a key on an element.",
                {"element_id": {"type": "string"}, "key": {"type": "string"}},
                ["element_id", "key"],
            ),
            _function(
                "hover", "Hover an element.", {"element_id": {"type": "string"}}, ["element_id"]
            ),
            _function(
                "select",
                "Select an option.",
                {"element_id": {"type": "string"}, "value": {"type": "string"}},
                ["element_id", "value"],
            ),
            _function(
                "scroll",
                "Scroll the page.",
                {"x": {"type": "integer"}, "y": {"type": "integer"}},
                [],
            ),
            _function(
                "wait_for",
                "Wait for an element or text to become visible.",
                {
                    "element_id": {"type": "string"},
                    "text": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                },
                [],
            ),
            _function("tabs", "List tabs.", {}, []),
            _function("switch_tab", "Switch tabs.", {"index": {"type": "integer"}}, ["index"]),
            _function("close_tab", "Close a tab.", {"index": {"type": "integer"}}, ["index"]),
            _function(
                "get_text",
                "Read visible page or element text.",
                {"element_id": {"type": "string"}, "max_chars": {"type": "integer"}},
                [],
            ),
            _function(
                "upload",
                "Upload a file from the task upload directory.",
                {"element_id": {"type": "string"}, "path": {"type": "string"}},
                ["element_id", "path"],
            ),
            _function(
                "storage",
                "Read non-sensitive local/session storage keys (values are redacted).",
                {},
                [],
            ),
            _function(
                "screenshot",
                "Save a screenshot artifact.",
                {"name": {"type": "string"}, "full_page": {"type": "boolean"}},
                [],
            ),
            _function(
                "assert_text", "Verify text is present.", {"text": {"type": "string"}}, ["text"]
            ),
            _function(
                "assert_url",
                "Verify the current URL contains a value.",
                {"value": {"type": "string"}},
                ["value"],
            ),
            _function(
                "assert_element",
                "Verify a semantic element is visible.",
                {"element_id": {"type": "string"}},
                ["element_id"],
            ),
            _function("detect_challenge", "Detect CAPTCHA or MFA challenges.", {}, []),
            _function(
                "request_human",
                "Pause for human interaction.",
                {"reason": {"type": "string"}, "message": {"type": "string"}},
                ["reason", "message"],
            ),
            _function(
                "complete",
                "Complete with a verified structured result.",
                {
                    "success": {"type": "boolean"},
                    "summary": {"type": "string"},
                    "extracted_data": {"type": "object"},
                },
                ["success", "summary"],
            ),
        ],
    }
]


class CodexAppServerBackend(AgentBackend):
    def __init__(
        self,
        executable: str,
        workspace: Path,
        tool_handler: ToolHandler,
        event_handler: EventHandler,
    ) -> None:
        self.client = CodexAppServer(executable)
        self.workspace = workspace
        self.tool_handler = tool_handler
        self.event_handler = event_handler
        self._threads: dict[str, str] = {}
        self.client.on_request("item/tool/call", self._on_tool)
        self.client.on_notification(event_handler)

    async def start_task(self, task: BrowserTask) -> None:
        await self.client.start()
        task.codex_thread_id = await self.client.create_thread(
            self.workspace, BROWSER_AGENT_INSTRUCTIONS, BROWSER_TOOLS, read_only=True
        )
        self._threads[task.codex_thread_id] = task.id
        task.codex_turn_id = await self.client.start_turn(task.codex_thread_id, task.task)

    async def resume_task(self, task: BrowserTask, context: dict[str, Any]) -> None:
        await self.send_context(task, {"human_intervention_complete": True, **context})

    async def send_context(self, task: BrowserTask, context: dict[str, Any]) -> None:
        if not task.codex_thread_id:
            raise RuntimeError("Task has no Codex thread")
        task.codex_turn_id = await self.client.start_turn(
            task.codex_thread_id, f"Updated browser context: {context}"
        )

    async def cancel_task(self, task: BrowserTask) -> None:
        if task.codex_thread_id and task.codex_turn_id:
            await self.client.interrupt(task.codex_thread_id, task.codex_turn_id)

    async def close(self) -> None:
        await self.client.close()

    async def _on_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = payload.get("params", {})
        thread_id = params.get("threadId")
        task_id = self._threads.get(thread_id)
        if not task_id or params.get("namespace") != "browser":
            return {
                "contentItems": [{"type": "inputText", "text": "Unknown Brix browser task"}],
                "success": False,
            }
        try:
            result = await self.tool_handler(
                task_id, str(params.get("tool", "")), params.get("arguments") or {}
            )
            return {"contentItems": [{"type": "inputText", "text": str(result)}], "success": True}
        except Exception as error:
            return {"contentItems": [{"type": "inputText", "text": str(error)}], "success": False}
