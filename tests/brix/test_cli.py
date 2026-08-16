from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import patch

import pytest

from brix import cli


def test_parser_exposes_browser_task_commands() -> None:
    args = cli.build_parser().parse_args(["task", "Read the page title", "--profile", "work"])
    assert args.command == "task"
    assert args.instruction == "Read the page title"
    assert args.profile == "work"


def test_request_uses_brix_api_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIX_API_URL", "http://brix.example")
    monkeypatch.setenv("BRIX_API_TOKEN", "secret")
    response = type(
        "Response",
        (),
        {
            "__enter__": lambda self: self,
            "__exit__": lambda *args: None,
            "read": lambda self: b'{"status":"queued"}',
        },
    )()
    with patch("urllib.request.urlopen", return_value=response) as open_url:
        result = cli._request("POST", "/api/v1/tasks", {"task": "Example"})
    assert result == {"status": "queued"}
    request = open_url.call_args.args[0]
    assert request.full_url == "http://brix.example/api/v1/tasks"
    assert request.get_header("Authorization") == "Bearer secret"
    assert json.loads(request.data) == {"task": "Example"}


def test_request_rejects_non_http_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIX_API_URL", "file:///tmp/not-an-api")
    with pytest.raises(SystemExit, match="must use http or https"):
        cli._request("GET", "/api/health")


def test_event_loop_factory_ignores_uvicorn_subprocess_flag() -> None:
    loop = cli.event_loop_factory(use_subprocess=True)
    try:
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.ProactorEventLoop)
        else:
            assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
