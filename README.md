# Brix

Brix is a Strix-inspired, open-source AI browser automation platform. It uses Codex agents and a
deterministic Playwright browser layer to navigate websites, operate web applications, verify
results, support live human takeover, and return structured results to users or calling agents.

## Current capabilities

- Browser tasks backed by Codex App Server threads.
- Deterministic Chromium control through Playwright, including semantic snapshots and stable element
  references.
- Persistent browser profiles and SQLite task state.
- REST controls and a WebSocket event stream.
- Permission checks, approval states, screenshots, and structured task results.
- Pause/resume and agent-to-user browser control handoff primitives.

See [trix-to-brix-plan.md](trix-to-brix-plan.md) for the product direction and later milestones.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A working, authenticated `codex` CLI with App Server support
- Chromium installed for Playwright

## Run locally

```bash
uv sync
uv run playwright install chromium
uv run brix --reload
```

Open <http://127.0.0.1:8787> to create and monitor browser tasks. The API schema is available at
<http://127.0.0.1:8787/docs>.

Configuration:

```bash
export BRIX_DATABASE=/absolute/path/to/brix.db
export BRIX_CODEX_EXECUTABLE=codex
export BRIX_DATA_DIR=/absolute/path/to/brix-data
```

Important endpoints include:

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{id}
POST /api/v1/tasks/{id}/cancel
POST /api/v1/browser-sessions/{id}/take-control
POST /api/v1/browser-sessions/{id}/return-to-agent
WS   /api/v1/tasks/{id}/events
```

Codex reasons about a task while Brix owns browser execution, session state, permission enforcement,
and verification. When CAPTCHA, MFA, or another human-verification step appears, automation pauses
so a user can take control of the same browser session and then return it to the agent.

## Development

```bash
make dev-install
make test
make check-all
```

The historical `trix/` and `strix/` sources are retained as migration reference. They are not part
of the Brix wheel and do not expose console commands; new product implementation belongs in `brix/`.

## Architecture

```text
Caller -> Brix REST/WebSocket API -> Task Manager -> Codex
                                         |
                                         +-> Playwright -> Chromium
                                         +-> SQLite / artifacts
                                         +-> live human control
```

Brix is licensed under Apache-2.0. Its orchestration lineage runs through Trix, which began as a fork
of [usestrix/strix](https://github.com/usestrix/strix); preserved historical code retains its
original copyright and license notices.
