# Automation Agents

This package is the production runtime package for LangOrch agents.

The current LangOrch runtime is already strong at orchestration, approvals, retries, replay, leases, and audit. The remaining requirement is to keep the execution edge organized around reusable automation domains instead of one-off agent packages.

## Recommended Runtime Model

- Use **agents** as runtime boundaries.
- Use **tools/capabilities** inside each agent as the executable contract.
- Use **workflow capabilities** for bounded long-running automation or reasoning.
- Do **not** use "skills" as a runtime primitive in LangOrch. Skills are a design-time concept for templates, playbooks, or agent packaging, not a dispatch target.

## New Agent Layout

### `integration_agent.py`
- Channel: `api`
- Best for REST, GraphQL, webhooks, SOAP, OAuth token fetch
- This should be the default external-system connector for most automation

### `database_agent.py`
- Channel: `database`
- Unified SQL contract across:
  - SQLite
  - ODBC via `pyodbc`
  - JDBC via `jaydebeapi`

### `file_agent.py`
- Channel: `file`
- Handles filesystem automation with optional base-dir confinement
- Destructive delete is disabled by default

### `email_agent.py`
- Channel: `email`
- Supports:
  - SMTP/IMAP mailbox automation
  - Microsoft Graph email automation

### `desktop_agent.py`
- Channel: `desktop`
- Uses a provider model so one agent contract can target:
  - Windows UI Automation
  - Java Access Bridge
  - Mainframe terminal emulators
  - Citrix/vision-style automation
- Implemented now:
  - `pywinauto` for Windows UI Automation
  - WinAppDriver for WebDriver-style desktop control
  - Java Access Bridge via `pyjab`
  - `mock` for simulation and contract tests

### `web_agent.py`
- Channel: `web`
- Production web automation surface for Playwright + CDP execution
- Production web automation surface kept under the supported runtime package

### `swarm_agent.py`
- Channel: `swarm`
- Bounded multi-agent reasoning workflows, including failure analysis
- Bounded workflow reasoning surface kept under the supported runtime package

## Why This Is Better Than More Demo Agents

The platform should not grow by adding random one-off agents per application. It should grow by adding:

1. Stable channels
2. Stable capability contracts
3. Provider adapters behind those contracts

That gives you portability across:

- web apps
- Windows native apps
- Java/Swing apps
- green-screen/mainframe sessions
- filesystem flows
- APIs and event-driven integrations
- databases

## Next Connectors To Add

Highest value next:

1. 3270/5250 emulator provider for mainframe automation
2. OCR / computer-vision provider for image-only desktops
3. SAP GUI / Citrix-specific providers if those are target accounts
4. Exchange/EWS provider if Microsoft Graph is not available
5. Additional database-specific adapters where bulk-load and CDC matter

## Naming Direction

Use `backend/automation_agents/` as the only implementation source.
