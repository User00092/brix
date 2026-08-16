from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from brix import __version__


def event_loop_factory(*, use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """Create an event loop that can launch Codex on Windows.

    Uvicorn normally selects a ``SelectorEventLoop`` on Windows when reload or
    multiple workers are enabled. That loop does not implement asyncio's
    subprocess APIs, which Brix needs for ``codex app-server``.
    """
    del use_subprocess
    if sys.platform == "win32":
        loop_class: type[asyncio.AbstractEventLoop] = getattr(  # noqa: B009
            asyncio, "ProactorEventLoop"
        )
        return loop_class()
    return asyncio.SelectorEventLoop()


def _request(method: str, path: str, payload: dict[str, object] | None = None) -> object:
    base_url = os.environ.get("BRIX_API_URL", "http://127.0.0.1:8787").rstrip("/")
    if urllib.parse.urlsplit(base_url).scheme not in {"http", "https"}:
        raise SystemExit("BRIX_API_URL must use http or https")
    headers = {"Accept": "application/json"}
    token = os.environ.get("BRIX_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(  # noqa: S310
        f"{base_url}{path}", data=data, headers=headers, method=method
    )
    try:
        # The base URL scheme is constrained to HTTP(S) above.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"Brix API returned {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Unable to reach Brix API at {base_url}: {error.reason}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brix", description="Codex-powered browser automation")
    parser.add_argument("--version", action="version", version=f"Brix {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="start the Brix API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--reload", action="store_true")
    task = subparsers.add_parser("task", help="create a browser task")
    task.add_argument("instruction", help="plain-language browser task")
    task.add_argument("--profile", default="default")
    status = subparsers.add_parser("status", help="show a task as JSON")
    status.add_argument("task_id")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "task":
        result = _request(
            "POST", "/api/v1/tasks", {"task": args.instruction, "profile": args.profile}
        )
        sys.stdout.write(f"{json.dumps(result, indent=2)}\n")
        return
    if args.command == "status":
        result = _request("GET", f"/api/v1/tasks/{args.task_id}")
        sys.stdout.write(f"{json.dumps(result, indent=2)}\n")
        return
    if args.command is None:
        parser.print_help()
        return
    import uvicorn

    uvicorn.run(
        "brix.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="brix.cli:event_loop_factory",
    )


if __name__ == "__main__":
    main()
