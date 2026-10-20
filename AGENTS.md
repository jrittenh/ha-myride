# Agent Guidelines & Repository Architecture

Welcome! This document outlines guidelines, architectural decisions, and standard operating procedures for AI agents (and human contributors) collaborating on `ha-myride`.

This repository adheres to Justin's global operational profile and system conventions defined in [`~/code/jrittenh-guide/AGENTS.md`](file:///home/jrittenh/code/jrittenh-guide/AGENTS.md).

---

## 1. Repository Purpose & Architecture

`ha-myride` is a custom integration for **Home Assistant** that reverse-engineers the Tyler Technologies **My Ride K-12** platform to provide real-time school bus tracking, student route schedules, and stop arrival ETAs.

### Core Architecture & Components
* `custom_components/myride/`
  * `__init__.py`: Component lifecycle (`async_setup_entry`, `async_unload_entry`), `MyRideDataUpdateCoordinator`, and real-time SignalR WebSocket worker task (`_async_run_signalr`).
  * `api.py`: `MyRideAPI` handling AWS Cognito authentication (`USER_PASSWORD_AUTH`) and REST API endpoints (`/api/student`, `/api/bus`).
  * `config_flow.py`: Home Assistant UI configuration flow, authenticating against Cognito and discovering linked school district tenants.
  * `const.py`: Domain constants, default polling intervals, and field access helpers (`get_field`).
  * `sensor.py`: Student route sensors (`MyRideNextStopSensor`, `MyRideBusStatusSensor`).
  * `device_tracker.py`: GPS tracker entities (`MyRideBusTracker`) reporting bus location, speed, and heading.
  * `manifest.json`: Home Assistant custom integration manifest.

### Data Flow & Communication Channels
1. **Authentication**: AWS Cognito User Pool (`us-east-1`, Client ID `3c5382gsq7g13djnejo98p2d98`). Obtains `AccessToken`, `IdToken`, and `RefreshToken`. School districts (tenants) are extracted from the `cognito:groups` JWT claim.
2. **REST API**:
   * Base URL: `https://myridek12.tylerapi.com`
   * `/api/student`: Student profiles, assigned routes (`runInfo`), and planned stop sequences (`stopsInfo`).
   * `/api/bus`: Snapshot of district bus locations (fallback; often unavailable or empty on live systems).
3. **SignalR WebSocket Hub**:
   * Endpoint: `wss://myridek12.tylerapi.com/livevehiclehub?x-tenant-id={tenant}&id={connectionToken}`
   * Negotiate endpoint: `POST https://myridek12.tylerapi.com/livevehiclehub/negotiate?x-tenant-id={tenant}`
   * Wire protocol: SignalR JSON Hub protocol (`\x1e` record separator, ping `type: 6`, invocation `type: 1`).
   * Real-time events:
     * `NewLocation`: Real-time GPS coordinate, speed, heading, and telemetry updates for active buses.
     * `NewETA`: Dynamic estimated time of arrival updates for specific runs and stops.

---

## 2. Operating Directives & Hard Constraints

Rules are structured under Justin's standard three-tier hierarchy:
* `[STATED]`: Explicit, non-negotiable rules and direct instructions.
* `[IMPLIED]`: Strong workflow preferences, style patterns, and technical practices.
* `[INFERRED]`: Background context and environmental factors.

### Directives
* `[STATED]` **Zero Secret Decryption & No Credential Exposure**: Never output, hardcode, or inspect credentials, Cognito tokens, or sensitive API payloads. Any scratch scripts or test templates must use placeholders or environment variables.
* `[STATED]` **Agent PR Boundaries & Merge Guardrails**: When completing feature or maintenance tasks, agents open Pull Requests and monitor CI via Forgejo CLI (`fj` / `~/.cargo/bin/fj-ex`). **Under no circumstances should the agent approve or merge its own Pull Requests**; merge authority is strictly reserved for the human maintainer.
* `[STATED]` **Dedicated Feature Branches (No Direct Commits to Main)**: All changes must be developed on dedicated branches (`feature/<name>` or `fix/<name>`). Never commit or push directly to `main`.
* `[STATED]` **Standardize on AGENTS.md**: Maintain `AGENTS.md` as the single tool-agnostic system prompt. Do not create vendor-locked configuration files (e.g., `.cursorrules`).
* `[STATED]` **Raw Code Blocks for Markdown Deliverables**: When generating Markdown files or deliverables intended for direct use or downstream export, wrap the entire Markdown document in a raw, fenced code block.
* `[STATED]` **Atomic & Conventional Commits**: Commits must be atomic (scoped to a single logical change) with imperative Conventional Commit messages (`type(scope): description`). Standard types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `rules`.
* `[STATED]` **Commit Spell-Checking**: Git commits are validated by a global `aspell` commit-msg hook (`~/.config/git/hooks/commit-msg`) using a personal dictionary (`~/.aspell.en.pws`). When technical jargon triggers spell-check failures, propose adding the word to the personal dictionary:
  ```bash
  echo -e "*<word>\n#" | aspell -a >/dev/null
  ```
  Test commit messages prior to committing:
  ```bash
  echo "<commit message>" | aspell list --mode=email
  ```
* `[STATED]` **PII & Privacy Protection**: Never log or print student names, addresses, or private location coordinates to logs. Scrub or mask sensitive fields in tests and debug logs.
* `[IMPLIED]` **Engineering Depth Over Hand-Holding**: Lead directly with technical solutions, concrete code, and architectural trade-offs without conversational filler.
* `[IMPLIED]` **Pre-Push Validation Gate**: Run local tests via `uv run pytest` before proposing commits or opening PRs. All tests must exit with code 0.

---

## 3. Development Workflow & Testing

### Package Management
This project uses [`uv`](https://github.com/astral-sh/uv) for fast, deterministic Python environment and dependency management.

```bash
# Run test suite
uv run pytest

# Run specific test file
uv run pytest tests/test_init.py
```

### Mocking Home Assistant in Tests
To keep local development and CI ultra-fast and lightweight without installing the entire Home Assistant monolithic package, `tests/conftest.py` provides lightweight stubs for Home Assistant core classes (`ConfigFlow`, `DataUpdateCoordinator`, `CoordinatorEntity`, `SensorEntity`, `TrackerEntity`, `dt_util`). Ensure new entity types or coordinator interactions are properly reflected in `conftest.py`.

---

## 4. Remotes & CI/CD
* **Forgejo Primary Remote**: `origin` (`git@git.52203.net:jrittenh/ha-myride`)
* **GitHub Mirror Remote**: `github` (`git@github.com:jrittenh/ha-myride`)
* **CI Engine**: Forgejo Actions running on `catthehacker-ubuntu-latest` defined in `.forgejo/workflows/ci.yml`. Runs `uv run pytest` on pushes and PRs targeting `main`.
