# Brix — Codex-Powered Automated Browser

## Overview

Brix is a Strix-inspired, open-source AI browser automation platform built around Codex.

Brix converts the existing Trix agent-orchestration project into a browser-focused automation system that can receive a task from a user, Hermes agent, n8n workflow, API client, or another AI agent; launch or reuse a browser session; allow Codex to operate that browser; verify the requested task was completed; and return a structured result to the caller.

Brix should also provide live remote access to the browser directly from the Brix web interface. A user should be able to watch the browser while the agent works, take control when necessary, complete login/MFA/CAPTCHA or other human-verification steps, and then return control to Codex without losing the browser session.

---

# Primary Goal

Convert Trix from a software-development agent orchestration system into a general-purpose automated browser platform.

The desired workflow is:

```text
User / Hermes / n8n / External Agent
                |
                v
          Brix Task API
                |
                v
          Brix Manager
                |
                v
             Codex
                |
                v
       Browser Tool Layer
                |
                v
       Chromium / Playwright
                |
                +-------------------+
                |                   |
                v                   v
         Automated Control     Remote Browser UI
                                    |
                                    v
                                  User
```

Brix should:

- Accept plain-language browser tasks.
- Use Codex as the reasoning and planning engine.
- Use Playwright or an equivalent browser automation layer for deterministic browser actions.
- Maintain persistent browser sessions and authenticated profiles.
- Allow a user to remotely view and control the browser from the Brix website.
- Pause automation when human interaction is required.
- Resume the same Codex/browser task after human intervention.
- Verify important actions before declaring success.
- Save screenshots, browser events, logs, and task results.
- Return machine-readable results to the calling agent.
- Support multiple isolated browser workers.
- Eventually support parallel browser subtasks.

---

# Rename and Product Conversion

The existing project should be converted from:

```text
Trix
```

to:

```text
Brix
```

The rename should apply throughout the project.

Examples:

```text
Trix Manager        -> Brix Manager
Trix Worker         -> Brix Browser Worker
Trix API            -> Brix API
Trix Dashboard      -> Brix Dashboard
Trix Agent          -> Brix Browser Agent
trix/               -> brix/
TRIX_*              -> BRIX_*
trix.db              -> brix.db
```

Existing Trix components that are useful for task orchestration, agent lifecycle management, event streaming, Codex integration, logging, and the web interface should be reused rather than rewritten unnecessarily.

Development-agent-specific functionality should be removed or generalized.

---

# Core Architecture

```text
┌──────────────────────────────────────────────┐
│                  Brix Site                   │
│                                              │
│ Dashboard                                    │
│ Task creation                                │
│ Task history                                 │
│ Agent event stream                           │
│ Live browser viewer                          │
│ Remote browser control                       │
│ Human approval UI                            │
└─────────────────────┬────────────────────────┘
                      │
                      v
┌──────────────────────────────────────────────┐
│                 Brix API                     │
│                                              │
│ FastAPI                                      │
│ Authentication                               │
│ Task API                                     │
│ Browser session API                          │
│ WebSocket / SSE event stream                 │
│ Artifact API                                 │
│ Remote-control session API                   │
└─────────────────────┬────────────────────────┘
                      │
                      v
┌──────────────────────────────────────────────┐
│               Brix Manager                   │
│                                              │
│ Task scheduler                               │
│ Worker allocation                            │
│ Permission enforcement                       │
│ Task state machine                           │
│ Codex lifecycle                              │
│ Human intervention handling                  │
└─────────────────────┬────────────────────────┘
                      │
                      v
┌──────────────────────────────────────────────┐
│             Codex Browser Agent              │
│                                              │
│ Understand task                              │
│ Plan next action                             │
│ Call browser tools                           │
│ Inspect results                              │
│ Verify completion                            │
│ Produce structured result                    │
└─────────────────────┬────────────────────────┘
                      │
                      v
┌──────────────────────────────────────────────┐
│            Browser Tool Service              │
│                                              │
│ Playwright                                   │
│ Browser MCP                                  │
│ Semantic DOM snapshots                       │
│ Navigation                                   │
│ Clicking / typing                            │
│ Uploads / downloads                          │
│ Screenshots                                  │
│ Tabs                                         │
│ Challenge detection                          │
│ Verification                                 │
└─────────────────────┬────────────────────────┘
                      │
                      v
┌──────────────────────────────────────────────┐
│           Chromium Browser Worker            │
│                                              │
│ Persistent browser profile                   │
│ Dedicated browser context                    │
│ Remote desktop / browser stream              │
└──────────────────────────────────────────────┘
```

---

# Codex Integration

Codex should remain the primary reasoning engine.

Brix should support a backend abstraction such as:

```python
class AgentBackend:
    async def start_task(self, task):
        ...

    async def resume_task(self, task_id):
        ...

    async def cancel_task(self, task_id):
        ...

    async def send_context(self, task_id, context):
        ...
```

Initial backend:

```text
CodexExecBackend
```

This can launch Codex CLI using `codex exec` and consume its JSONL event stream.

Future backend:

```text
CodexAppServerBackend
```

This can use the Codex SDK or Codex App Server for persistent threads, better lifecycle control, and tighter communication with Brix.

The rest of Brix should not depend directly on the Codex CLI implementation.

---

# Browser Control Strategy

Codex should reason about browser actions, but browser execution should be handled by a deterministic browser service.

Preferred stack:

```text
Codex
   |
   v
Browser MCP / Internal Browser API
   |
   v
Playwright
   |
   v
Chromium
```

Do not rely primarily on Codex generating arbitrary Playwright scripts.

Expose a controlled browser tool interface.

Example tools:

```text
browser.open
browser.navigate
browser.back
browser.forward
browser.reload

browser.snapshot
browser.get_text
browser.get_elements
browser.get_accessibility_tree

browser.click
browser.type
browser.fill
browser.press
browser.select
browser.hover
browser.scroll

browser.wait_for
browser.wait_for_navigation

browser.tabs
browser.switch_tab
browser.close_tab

browser.upload
browser.download

browser.cookies
browser.storage

browser.screenshot

browser.assert_text
browser.assert_url
browser.assert_element

browser.detect_challenge
browser.request_human
```

---

# Semantic Browser Snapshots

Codex should not receive giant raw HTML dumps unless specifically required.

Brix should convert the current page into a compact semantic representation.

Example:

```json
{
  "url": "https://example.com/login",
  "title": "Sign In",
  "elements": [
    {
      "id": "e17",
      "role": "textbox",
      "name": "Email",
      "visible": true
    },
    {
      "id": "e18",
      "role": "textbox",
      "name": "Password",
      "visible": true
    },
    {
      "id": "e19",
      "role": "button",
      "name": "Sign In",
      "visible": true
    }
  ]
}
```

Codex can then execute actions against stable Brix element IDs:

```text
browser.fill("e17", value)
browser.fill("e18", value)
browser.click("e19")
```

The Brix browser service maps those IDs back to Playwright locators.

Prefer:

1. ARIA role and accessible name.
2. Explicit labels.
3. Stable DOM attributes.
4. Text-based locators.
5. CSS/XPath only as a fallback.

---

# Remote Browser Access

Remote access to the active browser is a core Brix feature.

Every browser task should optionally expose its browser session directly through the Brix website.

Example Brix route:

```text
/browsers/{session_id}
```

or:

```text
/tasks/{task_id}/browser
```

The page should display the live browser and allow direct mouse and keyboard control.

Example layout:

```text
┌─────────────────────────────────────────────────────────────┐
│ Brix                                         Task: #BRX-104 │
├───────────────────────┬─────────────────────────────────────┤
│ Task                  │                                     │
│                       │                                     │
│ Check my latest UPS   │          LIVE BROWSER               │
│ delivery status.      │                                     │
│                       │                                     │
│ Status: RUNNING       │                                     │
│                       │                                     │
│ Agent: Codex          │                                     │
│                       │                                     │
│ [Pause Agent]         │                                     │
│ [Take Control]        │                                     │
│                       │                                     │
├───────────────────────┴─────────────────────────────────────┤
│ Agent activity                                              │
│ > Navigated to UPS                                         │
│ > Opened tracking page                                     │
│ > Waiting for page                                         │
└─────────────────────────────────────────────────────────────┘
```

---

# Remote Browser Implementation

A practical first implementation can use:

```text
Chromium
   |
Xvfb / virtual desktop
   |
x11vnc
   |
noVNC
   |
WebSocket proxy
   |
Brix frontend iframe/component
```

Alternative implementations may use a browser-streaming technology that provides lower latency.

The remote browser service should be internal-only.

The Brix API should generate short-lived authenticated session URLs or tokens.

Example:

```text
GET /api/v1/browser-sessions/{id}/remote-access
```

Response:

```json
{
  "session_id": "bs_123",
  "url": "/remote/bs_123?token=...",
  "expires_at": "2026-08-15T17:30:00Z"
}
```

Do not expose raw VNC ports publicly.

---

# Human Takeover

Users must be able to take direct control of a browser session.

States:

```text
AGENT_CONTROLLED
USER_CONTROLLED
WAITING_FOR_USER
PAUSED
```

When the user clicks:

```text
Take Control
```

Brix should:

1. Pause new Codex browser actions.
2. Allow any currently executing browser action to safely finish.
3. Change the browser session state to `USER_CONTROLLED`.
4. Give the user full mouse and keyboard interaction.
5. Keep the browser context and Codex task alive.
6. Continue recording browser events where appropriate.

When the user clicks:

```text
Return to Agent
```

Brix should:

1. Disable direct user control.
2. Capture a fresh semantic browser snapshot.
3. Capture the current URL.
4. Optionally capture a screenshot.
5. Tell Codex that the human intervention is complete.
6. Provide the new browser state to Codex.
7. Resume the existing task.

Codex must not restart the task from the beginning.

---

# CAPTCHA, MFA, and Human Verification

Brix should detect verification challenges and transition to human intervention instead of attempting to defeat them.

Detect common challenges such as:

```text
CAPTCHA
reCAPTCHA
hCaptcha
Cloudflare Turnstile
Cloudflare challenge pages
Arkose / FunCaptcha
SMS OTP
email OTP
authenticator OTP
passkeys
security confirmation
"Verify you are human"
```

Example task transition:

```text
RUNNING
   |
   v
WAITING_FOR_USER
   reason=CAPTCHA
```

Brix should notify the caller:

```json
{
  "task_id": "tsk_123",
  "status": "waiting_for_user",
  "reason": "captcha",
  "browser_session_id": "bs_456",
  "message": "Human verification is required before the task can continue."
}
```

The Brix site should prominently show:

```text
Human interaction required

[Open Browser]
```

Once the user completes the challenge:

```text
[Resume Agent]
```

The same browser profile, cookies, tabs, and task context should remain active.

---

# Persistent Browser Profiles

Brix should support reusable browser identities.

Example:

```text
data/
└── profiles/
    ├── default/
    ├── ryan/
    ├── hermes/
    └── work/
```

Each profile can contain:

```text
Chromium user data
cookies
localStorage
site sessions
browser preferences
downloads
metadata
```

Example metadata:

```json
{
  "id": "ryan",
  "display_name": "Ryan",
  "created_at": "2026-08-15T12:00:00Z",
  "last_used_at": "2026-08-15T15:44:00Z"
}
```

Browser profiles contain sensitive authentication material and must:

- Never be committed to Git.
- Be excluded through `.gitignore`.
- Have restrictive filesystem permissions.
- Be encrypted at rest when practical.
- Never be exposed through task logs.
- Never be returned to Codex as raw cookies unless specifically required.

---

# Task API

Primary task creation endpoint:

```text
POST /api/v1/tasks
```

Example:

```json
{
  "task": "Open UPS and determine whether my latest package is arriving today.",
  "profile": "ryan",
  "permissions": {
    "allow_navigation": true,
    "allow_login": true,
    "allow_form_submission": false,
    "allow_messages": false,
    "allow_account_changes": false,
    "allow_purchase": false
  }
}
```

Response:

```json
{
  "task_id": "tsk_01K2XYZ",
  "status": "queued"
}
```

---

# Task Status API

```text
GET /api/v1/tasks/{task_id}
```

Example:

```json
{
  "task_id": "tsk_01K2XYZ",
  "status": "running",
  "browser_session_id": "bs_01K2ABC",
  "started_at": "2026-08-15T15:45:01Z"
}
```

---

# Task Event Stream

Support either:

```text
GET /api/v1/tasks/{task_id}/events
```

using Server-Sent Events,

or:

```text
WS /api/v1/tasks/{task_id}/events
```

Events can include:

```text
task.queued
task.started
agent.started
agent.message
browser.started
browser.navigate
browser.snapshot
browser.click
browser.type
browser.download
browser.challenge
browser.user_controlled
browser.agent_controlled
task.waiting_for_user
task.resumed
task.completed
task.failed
```

---

# Structured Task Result

Brix must return deterministic machine-readable results.

Example:

```json
{
  "task_id": "tsk_01K2XYZ",
  "status": "completed",
  "success": true,
  "summary": "Your latest UPS package is out for delivery and is expected today between 1:15 PM and 5:15 PM.",
  "final_url": "https://www.ups.com/track",
  "extracted_data": {
    "status": "Out for Delivery",
    "delivery_date": "2026-08-15",
    "delivery_window": "1:15 PM - 5:15 PM"
  },
  "actions": [
    {
      "type": "navigate",
      "description": "Opened UPS tracking."
    },
    {
      "type": "read",
      "description": "Read the active shipment status."
    }
  ],
  "artifacts": [
    {
      "type": "screenshot",
      "path": "runs/tsk_01K2XYZ/screenshots/final.png"
    }
  ],
  "error": null
}
```

---

# Hermes Integration

Hermes should interact with Brix through one high-level tool.

Example:

```text
browser_task
```

Input:

```json
{
  "task": "Check when my most recent Amazon order will arrive.",
  "profile": "ryan"
}
```

Hermes should not need to know anything about Playwright, Chromium, selectors, screenshots, or browser sessions.

Flow:

```text
Hermes
   |
   | browser_task(...)
   v
Brix API
   |
   v
Brix Manager
   |
   v
Codex Browser Agent
   |
   v
Browser
   |
   v
Structured Result
   |
   v
Hermes
```

If Brix requires human interaction:

```json
{
  "status": "waiting_for_user",
  "reason": "mfa",
  "browser_session_id": "bs_123"
}
```

Hermes can report:

```text
Brix needs you to complete authentication before it can continue.
```

After the user interacts with the Brix browser UI, the existing task resumes.

---

# Task State Machine

Use an explicit state machine.

```text
QUEUED
   |
   v
STARTING
   |
   v
RUNNING
   |
   +-----------------------+
   |                       |
   v                       v
COMPLETED               FAILED

RUNNING
   |
   v
WAITING_FOR_USER
   |
   v
USER_CONTROLLED
   |
   v
RESUMING
   |
   v
RUNNING
```

Additional terminal states:

```text
CANCELLED
TIMED_OUT
```

---

# Verification Loop

Codex should follow:

```text
OBSERVE
   |
   v
REASON
   |
   v
ACT
   |
   v
OBSERVE
   |
   v
VERIFY
```

Every meaningful browser action should be verified.

Bad:

```text
Click Settings
Click Account
Click Save
Report success
```

Good:

```text
Snapshot
Click Settings
Snapshot
Verify Settings page opened

Click Account
Snapshot
Verify Account panel opened

Click Save
Wait for response
Snapshot
Verify success message or changed state

Report success
```

---

# Permissions and Approval Levels

Browser actions should be classified by risk.

## Level 0 — Observation

Examples:

```text
Navigate
Read page
Search
Scroll
Inspect order status
Read public information
Take screenshot
```

Default:

```text
AUTO
```

## Level 1 — Reversible Interaction

Examples:

```text
Fill form
Change search filters
Open authenticated page
Upload file
Modify temporary UI state
```

Default:

```text
AUTO
```

depending on task permissions.

## Level 2 — External Side Effect

Examples:

```text
Send email
Send message
Submit application
Schedule appointment
Change account setting
Post content
```

Default:

```text
ASK
```

## Level 3 — Financial or Destructive

Examples:

```text
Purchase item
Transfer money
Cancel subscription
Delete data
Delete account
Sign agreement
```

Default:

```text
DENY
```

unless explicitly authorized.

Example policy:

```json
{
  "level_0": "auto",
  "level_1": "auto",
  "level_2": "ask",
  "level_3": "deny"
}
```

---

# Browser Worker Isolation

Each active browser worker should receive:

```text
Dedicated browser process or isolated browser context
Dedicated task workspace
Dedicated downloads directory
Dedicated event stream
Dedicated screenshots directory
Dedicated remote-control session
```

Workers must not accidentally share cookies or authenticated sessions unless they intentionally use the same named Brix profile.

---

# Worker Concurrency

Initial deployment:

```text
MAX_BROWSER_WORKERS=2
```

If two workers are active:

```text
Task 1 -> Worker A
Task 2 -> Worker B
Task 3 -> QUEUED
```

Concurrency can be configurable.

Future versions may dynamically scale worker containers.

---

# Subtasks

Brix should eventually support browser subtasks.

Example:

```text
Task:
Compare this replacement part at Amazon, RockAuto, and AutoZone.

Parent Browser Agent
     |
     +--> Browser Worker A -> Amazon
     |
     +--> Browser Worker B -> RockAuto
     |
     +--> Browser Worker C -> AutoZone
```

Each worker returns a structured result.

The parent Codex agent compares those results and produces the final answer.

Initial Brix releases do not need subtask support.

---

# Logging and Artifacts

Each task should receive its own run directory.

```text
data/
└── runs/
    └── tsk_01K2XYZ/
        ├── task.json
        ├── result.json
        ├── agent-events.jsonl
        ├── browser-events.jsonl
        ├── screenshots/
        │   ├── 000001.png
        │   ├── 000002.png
        │   └── final.png
        ├── downloads/
        └── trace/
```

Logs should record browser operations without leaking passwords, session cookies, auth headers, private tokens, or other credentials.

---

# Browser Screenshots

Capture screenshots:

```text
At task start
Before major external actions
After major external actions
When verification fails
When human intervention is required
At task completion
```

Do not take screenshots after every tiny action unless debug mode is enabled.

---

# Browser Trace

Support optional Playwright tracing.

Example:

```json
{
  "trace": true
}
```

Recommended defaults:

```text
Successful task -> trace optional / short retention
Failed task     -> retain trace
Debug task      -> retain full trace
```

Traces may contain sensitive information and should be access-controlled.

---

# Brix Web Dashboard

The existing Trix site should be converted into the Brix dashboard.

Main navigation:

```text
Dashboard
Tasks
Browsers
Profiles
Artifacts
Settings
```

---

# Dashboard

Show:

```text
Active tasks
Queued tasks
Waiting-for-user tasks
Active browser sessions
Recent completed tasks
Failed tasks
Worker utilization
```

---

# Tasks Page

Each task should display:

```text
Task description
Caller
Profile
Current status
Current URL
Start time
Duration
Agent events
Browser actions
Screenshots
Final result
```

Actions:

```text
Open Browser
Pause
Resume
Cancel
Retry
View Logs
View Result
```

---

# Browsers Page

Display active and reusable browser sessions.

Example:

```text
Session         Profile      State             Task
---------------------------------------------------------
bs_123          ryan         Agent Controlled  tsk_456
bs_789          work         User Controlled   tsk_790
```

Actions:

```text
Open Browser
Take Control
Return to Agent
Terminate
```

---

# Profiles Page

Allow users to:

```text
Create browser profile
Rename profile
Launch manual login session
Open browser profile manually
Delete profile
Set default profile
```

Example workflow:

```text
Create Profile: Amazon
        |
        v
Open Browser
        |
        v
User manually logs into Amazon
        |
        v
Close Browser
        |
        v
Session retained
        |
        v
Future Brix tasks can reuse login
```

This avoids repeatedly passing credentials through Codex.

---

# Frontend Live Browser Integration

The live browser should appear directly inside the Brix site instead of forcing the user into a separate VNC application.

Suggested page:

```text
/tasks/{task_id}
```

Layout:

```text
┌───────────────────────────────────────────────────────────────┐
│ BRIX                           RUNNING        [Cancel Task]    │
├────────────────────────┬──────────────────────────────────────┤
│ Task                   │                                      │
│                        │                                      │
│ Check Amazon shipment  │             Browser                  │
│                        │                                      │
│ Profile: Ryan          │                                      │
│ Agent: Codex           │                                      │
│                        │                                      │
│ [Pause Agent]          │                                      │
│ [Take Control]         │                                      │
│                        │                                      │
├────────────────────────┴──────────────────────────────────────┤
│ Activity                                                      │
│ 11:42:01 Navigated to amazon.com                             │
│ 11:42:03 Opened Orders                                       │
│ 11:42:05 Inspecting most recent order                         │
└───────────────────────────────────────────────────────────────┘
```

The browser panel should support:

```text
Mouse
Keyboard
Clipboard
Scrolling
Browser resizing
Fullscreen
```

File upload support can be added later.

---

# Security

Brix will control authenticated web sessions and must be treated as a privileged service.

Requirements:

- Require authentication for the Brix site.
- Protect API endpoints with authorization.
- Use short-lived remote-browser access tokens.
- Never directly expose VNC ports.
- Restrict browser worker network access where appropriate.
- Store secrets outside the repository.
- Never send browser-profile cookies to the frontend.
- Redact passwords from logs.
- Redact Authorization headers.
- Redact cookies from agent logs.
- Validate all uploaded files.
- Apply task permission policies server-side.
- Do not trust Codex alone to enforce permissions.
- Require server-side approval for high-risk browser actions.
- Limit browser worker resources.
- Terminate abandoned sessions.
- Maintain an audit log for consequential actions.

---

# Challenge Handling

Brix should distinguish normal browser compatibility from bypassing site controls.

Brix may:

```text
Use a normal Chromium browser
Run JavaScript
Store cookies
Maintain authenticated sessions
Use realistic browser dimensions
Reuse browser profiles
Wait for dynamic content
Handle SPA navigation
Support downloads/uploads
```

When a site presents a CAPTCHA or explicit human-verification challenge, Brix should pause and request human interaction through the remote browser UI rather than attempt to defeat the challenge.

---

# Suggested Backend Stack

Initial implementation:

```text
Python 3.12+
FastAPI
Pydantic
asyncio
Playwright
Chromium
Codex CLI
SQLite
WebSockets or SSE
Xvfb
x11vnc
noVNC
```

Later:

```text
PostgreSQL
Redis
Codex App Server / SDK
Containerized browser workers
Distributed worker nodes
Object storage for artifacts
```

---

# Suggested Frontend

Reuse the existing Trix frontend where practical.

Recommended technologies:

```text
React / Next.js
or existing Trix frontend framework

WebSocket client
noVNC browser component
Task timeline
Live agent events
Browser-control toolbar
```

---

# Proposed Repository Structure

```text
brix/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── brix/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── tasks.py
│   │   ├── browsers.py
│   │   ├── profiles.py
│   │   ├── events.py
│   │   └── artifacts.py
│   │
│   ├── agent/
│   │   ├── base.py
│   │   ├── codex_exec.py
│   │   ├── codex_app_server.py
│   │   ├── prompts.py
│   │   └── parser.py
│   │
│   ├── browser/
│   │   ├── manager.py
│   │   ├── worker.py
│   │   ├── session.py
│   │   ├── context.py
│   │   ├── snapshots.py
│   │   ├── actions.py
│   │   ├── verification.py
│   │   ├── challenges.py
│   │   ├── remote_control.py
│   │   └── artifacts.py
│   │
│   ├── mcp/
│   │   ├── server.py
│   │   └── tools/
│   │       ├── navigation.py
│   │       ├── observation.py
│   │       ├── interaction.py
│   │       ├── files.py
│   │       ├── verification.py
│   │       └── human.py
│   │
│   ├── tasks/
│   │   ├── manager.py
│   │   ├── queue.py
│   │   ├── states.py
│   │   └── permissions.py
│   │
│   ├── profiles/
│   │   ├── manager.py
│   │   └── encryption.py
│   │
│   ├── remote/
│   │   ├── manager.py
│   │   ├── tokens.py
│   │   └── novnc.py
│   │
│   └── models/
│       ├── task.py
│       ├── result.py
│       ├── browser.py
│       └── events.py
│
├── frontend/
│   ├── tasks/
│   ├── browsers/
│   ├── profiles/
│   └── components/
│       ├── BrowserViewer.*
│       ├── TaskTimeline.*
│       └── AgentActivity.*
│
├── schemas/
│   └── browser-task-result.schema.json
│
├── data/
│   ├── profiles/
│   └── runs/
│
└── tests/
```

---

# Codex Browser Agent Prompt

The Brix Codex system prompt should establish the browser operating rules.

Example:

```text
You are Brix, an autonomous browser worker.

Your objective is to complete the supplied browser task using the browser
tools available to you.

RULES

1. Observe the current browser state before acting.
2. Prefer semantic element identifiers returned by browser.snapshot.
3. Never assume an action succeeded.
4. Verify important actions after they occur.
5. Do not expose passwords, cookies, tokens, or authentication data.
6. Respect the task's permissions.
7. Never perform a higher-risk action without the required approval.
8. If CAPTCHA, MFA, passkey verification, or another human challenge appears,
   call browser.request_human.
9. When human control is returned to you, inspect the browser again before
   continuing.
10. Avoid unnecessary navigation and actions.
11. Preserve the user's existing browser session whenever possible.
12. Return a structured BrowserTaskResult when the objective is complete.
13. If the objective cannot be completed, explain the exact blocker.

TASK:
{{ task }}
```

---

# Phase 1 — Convert Trix to Brix

Goals:

- Rename application from Trix to Brix.
- Remove development-specific language.
- Preserve working Codex orchestration infrastructure.
- Preserve frontend layout where useful.
- Replace development task concepts with browser tasks.
- Replace development workers with browser workers.
- Update environment variables.
- Update package names.
- Update API routes.
- Update database models.
- Update branding and UI text.

Acceptance criteria:

```text
Application starts as Brix.
No visible Trix branding remains.
Old Trix task infrastructure still functions after generalization.
```

---

# Phase 2 — Browser Worker

Implement:

- Playwright browser manager.
- Chromium launching.
- Browser contexts.
- Browser sessions.
- Semantic snapshots.
- Navigation.
- Click.
- Type/fill.
- Keyboard.
- Tabs.
- Screenshots.
- Downloads.
- Basic assertions.

Acceptance criteria:

```text
Brix can launch Chromium.
Brix can navigate to a website.
Codex can inspect page contents.
Codex can interact with page controls.
Brix can return a screenshot.
```

---

# Phase 3 — Codex Browser Tools

Implement an MCP or internal browser tool service.

Connect Codex to:

```text
browser.snapshot
browser.navigate
browser.click
browser.fill
browser.press
browser.scroll
browser.tabs
browser.screenshot
browser.assert_*
```

Acceptance criteria:

```text
A Codex task can independently navigate a simple website and extract requested information.
```

---

# Phase 4 — Task Orchestration

Implement:

- Task queue.
- Task manager.
- Worker allocation.
- Task state machine.
- Timeout handling.
- Cancellation.
- Event stream.
- Structured task result.

Acceptance criteria:

```text
POST /tasks creates a task.
The task is executed by a browser worker.
Events are streamed.
The result is returned as structured JSON.
```

---

# Phase 5 — Persistent Profiles

Implement:

- Create profile.
- Load profile.
- Browser user-data directories.
- Profile locking.
- Profile metadata.
- Manual profile login.
- Profile deletion.

Acceptance criteria:

```text
User logs into a website once.
Browser closes.
Future Brix task reopens the same authenticated session.
```

---

# Phase 6 — Remote Browser Access

Implement:

```text
Xvfb
x11vnc
noVNC
Brix-authenticated browser session gateway
BrowserViewer frontend component
```

Acceptance criteria:

```text
User opens an active Brix task.
The browser is visible directly inside the Brix site.
The user can interact with the remote browser.
The raw VNC endpoint is not publicly exposed.
```

This phase is considered a core requirement, not an optional enhancement.

---

# Phase 7 — Agent/User Control Handoff

Implement:

```text
Take Control
Return to Agent
Pause Agent
Resume Agent
```

Acceptance criteria:

```text
Codex is operating browser.
User clicks Take Control.
Codex stops issuing browser actions.
User interacts with the live browser.
User clicks Return to Agent.
Codex receives updated browser state.
Codex continues the same task.
```

---

# Phase 8 — Challenge Detection

Implement detection of:

```text
CAPTCHA
MFA
OTP
passkeys
Cloudflare verification
other human verification
```

Acceptance criteria:

```text
Agent detects challenge.
Task changes to WAITING_FOR_USER.
Brix dashboard alerts user.
User opens browser.
User completes challenge.
Task resumes.
```

---

# Phase 9 — Verification and Permissions

Implement:

- Verification after consequential actions.
- Action risk levels.
- Task-specific permissions.
- Approval requests.
- Server-side permission enforcement.

Acceptance criteria:

```text
Codex cannot bypass Brix permission restrictions.
Level 2 actions can trigger approval.
Level 3 actions can be denied globally.
```

---

# Phase 10 — Hermes Integration

Implement a simple Brix client/tool for Hermes.

Suggested tool:

```text
browser_task
```

Hermes should be able to:

```text
Start browser task
Read task result
Receive waiting-for-user status
Resume after user interaction
Cancel task
```

Acceptance criteria:

```text
Hermes sends a natural-language browser task.
Brix performs it.
Brix returns structured results.
Hermes reports those results to the user.
```

---

# Phase 11 — Reliability

Add:

- Action retries.
- Stale-element recovery.
- Page-load recovery.
- Browser-crash handling.
- Worker restart.
- Task timeouts.
- Trace capture.
- Screenshot capture.
- Better semantic snapshots.
- Structured failure reasons.

Failure reasons should include values such as:

```text
navigation_failed
element_not_found
browser_crashed
timeout
authentication_required
captcha
mfa
permission_denied
user_cancelled
site_error
verification_failed
```

---

# Phase 12 — Multi-Agent Browser Tasks

Once the core browser worker is stable, add optional subtasks.

Example:

```text
Parent task:
Compare these products from three vendors.

Brix Manager
   |
   +--- Worker 1
   +--- Worker 2
   +--- Worker 3
```

The parent Codex task should receive structured worker results and verify them before producing the final response.

---

# Initial MVP

The MVP should remain intentionally small.

Use:

```text
FastAPI
Codex CLI
Playwright
Chromium
SQLite
asyncio.Queue
WebSocket/SSE
Xvfb
x11vnc
noVNC
existing Trix frontend
```

Initial maximum workers:

```text
2
```

MVP requirements:

- Brix branding.
- Create browser task.
- Codex controls Playwright through browser tools.
- Persistent browser profile.
- Live browser visible through site.
- User takeover.
- Agent resume.
- Task event stream.
- Screenshots.
- Structured results.
- Challenge detection and human handoff.
- Hermes-compatible API.

Do not add Redis, Kubernetes, distributed workers, or complex scheduling until the basic browser worker is reliable.

---

# Definition of Done

Brix V1 is considered functional when the following flow works end-to-end:

```text
1. Hermes sends:
   "Check when my most recent Amazon order is arriving."

2. Brix creates a task.

3. Brix allocates a browser worker using the user's persistent profile.

4. Codex receives the task.

5. Codex observes the browser.

6. Codex navigates Amazon using Brix browser tools.

7. The live browser is visible from the Brix website during execution.

8. If a login verification or CAPTCHA appears:
      Brix pauses.
      The user opens the browser from the Brix site.
      The user completes verification.
      The user returns control to Codex.

9. Codex continues from the existing browser state.

10. Codex finds the latest order.

11. Codex verifies the displayed delivery information.

12. Brix stores supporting screenshots and events.

13. Brix returns:

    {
      "success": true,
      "summary": "...",
      "extracted_data": {...}
    }

14. Hermes receives the structured response.

15. Hermes reports the result to the user.
```

---

# Product Description

> **Brix is a Strix-inspired, open-source AI browser automation platform that uses Codex agents to navigate websites, operate web applications, complete browser-based tasks, verify results, support live human takeover, and report structured results back to the user or calling agent.**
