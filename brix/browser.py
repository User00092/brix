from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from brix.domain import BrowserSession, ControlState, FailureReason, utc_now


class BrowserError(RuntimeError):
    pass


class BrowserWorker:
    """Deterministic Playwright worker with stable semantic element references."""

    def __init__(
        self, session: BrowserSession, user_data_dir: Path, run_dir: Path, *, trace: bool = False
    ) -> None:
        self.session = session
        self.user_data_dir = user_data_dir
        self.run_dir = run_dir
        self.trace = trace
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._elements: dict[str, Any] = {}
        self._action_lock = asyncio.Lock()
        self._agent_allowed = asyncio.Event()
        self._agent_allowed.set()

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise BrowserError(
                "Playwright is not installed; run `playwright install chromium`"
            ) from error
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "downloads").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "uploads").mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=os.environ.get("BRIX_BROWSER_HEADLESS", "false").lower()
            in {"1", "true", "yes", "on"},
            accept_downloads=True,
            downloads_path=str(self.run_dir / "downloads"),
            viewport={"width": 1440, "height": 900},
        )
        if self.trace:
            await self._context.tracing.start(screenshots=True, snapshots=True, sources=False)
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )

    async def close(self) -> None:
        if self._context:
            if self.trace:
                trace_dir = self.run_dir / "trace"
                trace_dir.mkdir(exist_ok=True)
                await self._context.tracing.stop(path=str(trace_dir / "trace.zip"))
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    async def set_control(self, state: ControlState) -> None:
        async with self._action_lock:
            self.session.state = state
            self.session.last_activity_at = utc_now()
            if state == ControlState.AGENT_CONTROLLED:
                self._agent_allowed.set()
            else:
                self._agent_allowed.clear()

    async def _guard(self) -> Any:
        await self._agent_allowed.wait()
        if self._page is None:
            raise BrowserError("Browser is not running")
        return self._page

    async def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._action_lock:
            page = await self._guard()
            if action == "navigate":
                url = str(arguments["url"])
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise BrowserError("Navigation URL must be an absolute HTTP(S) URL")
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                return {"url": page.url, "status": response.status if response else None}
            if action in {"back", "forward", "reload"}:
                await getattr(page, action)()
                return {"url": page.url}
            if action == "snapshot":
                return await self.snapshot()
            if action in {"click", "fill", "type", "press", "hover", "select"}:
                locator = self._locator(str(arguments["element_id"]))
                if action in {"fill", "type"}:
                    await getattr(locator, action)(str(arguments.get("value", "")))
                elif action == "press":
                    await locator.press(str(arguments["key"]))
                elif action == "select":
                    await locator.select_option(str(arguments["value"]))
                else:
                    await getattr(locator, action)()
                return {"ok": True, "url": page.url}
            if action == "scroll":
                await page.mouse.wheel(int(arguments.get("x", 0)), int(arguments.get("y", 600)))
                return {"ok": True}
            if action == "wait_for":
                timeout = min(max(int(arguments.get("timeout_ms", 10_000)), 1), 60_000)
                if arguments.get("element_id"):
                    await self._locator(str(arguments["element_id"])).wait_for(
                        state="visible", timeout=timeout
                    )
                elif arguments.get("text"):
                    await page.get_by_text(str(arguments["text"]), exact=False).first.wait_for(
                        state="visible", timeout=timeout
                    )
                else:
                    await page.wait_for_load_state("domcontentloaded", timeout=timeout)
                return {"ok": True, "url": page.url}
            if action == "tabs":
                return {
                    "tabs": [
                        {"index": i, "url": tab.url, "title": await tab.title()}
                        for i, tab in enumerate(self._context.pages)
                    ]
                }
            if action == "switch_tab":
                self._page = self._context.pages[int(arguments["index"])]
                await self._page.bring_to_front()
                return {"url": self._page.url}
            if action == "close_tab":
                pages = self._context.pages
                index = int(arguments["index"])
                if len(pages) == 1:
                    raise BrowserError("Cannot close the only browser tab")
                if index < 0 or index >= len(pages):
                    raise BrowserError("Tab index is out of range")
                closing = pages[index]
                await closing.close()
                if closing is self._page:
                    self._page = self._context.pages[min(index, len(self._context.pages) - 1)]
                    await self._page.bring_to_front()
                return {"url": self._page.url}
            if action == "get_text":
                maximum = min(max(int(arguments.get("max_chars", 20_000)), 1), 100_000)
                target = (
                    self._locator(str(arguments["element_id"]))
                    if arguments.get("element_id")
                    else page.locator("body")
                )
                return {"text": (await target.inner_text())[:maximum], "truncated_at": maximum}
            if action == "upload":
                relative = Path(str(arguments["path"]))
                upload_root = (self.run_dir / "uploads").resolve()
                target = (upload_root / relative).resolve()
                if (
                    relative.is_absolute()
                    or upload_root not in target.parents
                    or not target.is_file()
                ):
                    raise BrowserError("Upload path must name a file in the task uploads directory")
                await self._locator(str(arguments["element_id"])).set_input_files(str(target))
                return {"ok": True, "name": target.name}
            if action == "storage":
                keys = await page.evaluate(
                    """() => ({
                        local: Object.keys(localStorage),
                        session: Object.keys(sessionStorage)
                    })"""
                )
                return {
                    "local_storage_keys": keys["local"],
                    "session_storage_keys": keys["session"],
                }
            if action == "screenshot":
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(arguments.get("name", "capture.png")))
                if not name.endswith(".png"):
                    name += ".png"
                path = self.run_dir / "screenshots" / name
                await page.screenshot(
                    path=str(path), full_page=bool(arguments.get("full_page", False))
                )
                return {"path": str(path.relative_to(self.run_dir.parent.parent))}
            if action == "assert_text":
                text = str(arguments["text"])
                found = await page.get_by_text(text, exact=False).count() > 0
                return {"passed": found, "expected": text}
            if action == "assert_url":
                expected = str(arguments["value"])
                return {"passed": expected in page.url, "actual": page.url, "expected": expected}
            if action == "assert_element":
                element_id = str(arguments["element_id"])
                return {
                    "passed": await self._locator(element_id).is_visible(),
                    "element_id": element_id,
                }
            if action == "detect_challenge":
                return await self.detect_challenge()
            raise BrowserError(f"Unsupported browser action: {action}")

    async def snapshot(self) -> dict[str, Any]:
        page = await self._guard()
        raw = await page.locator(
            "a,button,input,textarea,select,[role],[contenteditable=true]"
        ).evaluate_all(
            """els => els.slice(0, 250).map((el, i) => ({
                index: i,
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || ({
                    A: 'link', BUTTON: 'button', INPUT: 'textbox',
                    TEXTAREA: 'textbox', SELECT: 'combobox'
                })[el.tagName] || el.tagName.toLowerCase(),
                name: el.getAttribute('aria-label') || el.labels?.[0]?.innerText ||
                    el.innerText || el.getAttribute('placeholder') ||
                    el.getAttribute('name') || '',
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            }))"""
        )
        self._elements.clear()
        elements = []
        locator = page.locator("a,button,input,textarea,select,[role],[contenteditable=true]")
        for item in raw:
            element_id = f"e{item['index'] + 1}"
            self._elements[element_id] = locator.nth(item["index"])
            elements.append(
                {
                    "id": element_id,
                    "role": item["role"],
                    "name": str(item["name"]).strip()[:300],
                    "visible": item["visible"],
                }
            )
        self.session.current_url = page.url
        return {"url": page.url, "title": await page.title(), "elements": elements}

    async def detect_challenge(self) -> dict[str, Any]:
        page = await self._guard()
        content = (await page.locator("body").inner_text()).lower()[:100_000]
        selectors = await page.locator(
            "iframe[src*='captcha'], [class*='captcha'], [id*='captcha']"
        ).count()
        if selectors or any(
            term in content
            for term in ("captcha", "verify you are human", "cloudflare challenge", "turnstile")
        ):
            return {"detected": True, "reason": FailureReason.CAPTCHA}
        if any(
            term in content
            for term in (
                "one-time code",
                "verification code",
                "authenticator",
                "passkey",
                "security code",
            )
        ):
            return {"detected": True, "reason": FailureReason.MFA}
        return {"detected": False, "reason": None}

    def _locator(self, element_id: str) -> Any:
        try:
            return self._elements[element_id]
        except KeyError as error:
            raise BrowserError("Element reference is stale; take a fresh snapshot") from error
