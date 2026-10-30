<div align="center">

# VASP Desk v0.3

### Bitcoin Blockchain Investigation & Attribution Workspace

**Trace Bitcoin activity. Explore transaction paths. Record evidence. Review potential service-provider links.**

[![Bitcoin](https://img.shields.io/badge/Blockchain-Bitcoin%20Mainnet-orange)](#live-bitcoin-mode)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688)](#architecture)
[![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-3178C6)](#architecture)
[![Storage](https://img.shields.io/badge/Storage-SQLite-003B57)](#architecture)
[![Status](https://img.shields.io/badge/Status-Prototype%20%2F%20Learning%20Project-yellow)](#scope-limitations-and-responsible-use)

An editable local learning project for the user-provided **SIH 2026 PS 26182**.

</div>

> **Version note:** v0.3 replaces the earlier Ethereum demo with a Bitcoin tracing engine. References to Ethereum, ETH, or the former `backend/engine.py` architecture describe v0.2 and should not be treated as current v0.3 behavior. See `STRUCTURE.md` and `START_HERE.txt` in the repository for the current project layout and startup guidance.

---

## Contents

- [Overview](#overview)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Operating modes](#operating-modes)
- [Live Bitcoin mode](#live-bitcoin-mode)
- [Demo scenarios](#demo-scenarios)
- [AI Investigation Assistant](#ai-investigation-assistant)
- [Architecture](#architecture)
- [Application API](#application-api)
- [Development setup](#development-setup)
- [Tests](#tests)
- [Data, reports, and case history](#data-reports-and-case-history)
- [Privacy and security](#privacy-and-security)
- [Scope, limitations, and responsible use](#scope-limitations-and-responsible-use)
- [Troubleshooting](#troubleshooting)
- [Roadmap ideas](#roadmap-ideas)
- [Documentation and project status](#documentation-and-project-status)

## Overview

**VASP Desk** is a local-first Bitcoin investigation prototype for exploring public blockchain activity and organizing investigation results. It combines a React + TypeScript interface, a Python FastAPI backend, SQLite case history, a synthetic demo dataset, and an optional live data provider compatible with Blockstream Esplora.

A **Virtual Asset Service Provider (VASP)** is a business that provides covered virtual-asset services, such as certain cryptocurrency exchange or transfer services. A blockchain address label can suggest a possible service relationship; it does not by itself prove who owns or controls an address.

VASP Desk is intended for learning, prototyping, and analyst workflow exploration. It is not a certified forensic platform and should not be used as the sole basis for legal, financial, compliance, or enforcement decisions.

## What it does

- **Trace Bitcoin activity:** request address history and explore transaction relationships within configured limits.
- **Explore paths:** inspect an interactive transaction graph, highlight paths, search transactions, and inspect addresses.
- **Review possible attribution:** display available labels, label sources, and candidate endpoints where supported by the data.
- **Keep investigation records:** save cases with references, investigator notes, and Open / Reviewed / Archived status.
- **Revisit work:** search the case workspace and service directory; inspect recent investigations and saved-case summaries.
- **Export findings:** produce Markdown, JSON, CSV, printable reports, and editable sample request drafts.
- **Switch data modes:** use deterministic synthetic fixtures for offline demonstrations or opt into live Bitcoin mainnet lookups.
- **Review coverage:** show mode-aware notices and tracing-limit diagnostics so incomplete results are not mistaken for conclusive findings.

The exact results depend on the selected mode, data coverage, labels, provider response, and tracing limits.

## Quick start

### Requirements

- **Windows:** Python 3.11 or newer.
- **macOS/Linux:** Python 3.11 or newer with virtual-environment support.
- Internet access is needed for initial dependency installation and live blockchain queries.
- Node.js 22.12+ (or a newer supported LTS) is needed only for frontend development; the compiled React frontend is included in the release.

### Windows

1. Open the project folder.
2. Double-click `start-demo.cmd` for the offline demo, or run `start-live.cmd` for live Bitcoin lookups.
3. On first startup, the launcher installs required Python dependencies if needed.
4. Keep the terminal open.
5. Open **http://127.0.0.1:8000**.

PowerShell alternative:

```powershell
.\start-demo.cmd
```

For live Bitcoin mainnet:

```powershell
.\start-live.cmd
```

The launcher tries `py -3` and then `python`.

### macOS / Linux

From the project root:

```sh
sh start-demo.sh
```

For live mode:

```sh
VASP_MODE=live sh start-demo.sh
```

Then open **http://127.0.0.1:8000**.

> **Local-only by default:** the app binds to `127.0.0.1`. It has no authentication and is not ready for public hosting. Do not expose it to a network without adding and validating appropriate security controls.

For first-time setup details, read `START_HERE.txt`.

## Operating modes

| Mode | Purpose | Data source | Important caveat |
|---|---|---|---|
| **Demo / offline** | Demonstrate workflows with predictable examples | Synthetic fixtures and demo labels | Results only describe the fixture dataset; they are not real-world attribution |
| **Live** | Explore real Bitcoin mainnet address history | Configured Esplora-compatible endpoint | Public chain history and address labels do not prove wallet ownership; history may be incomplete |

Demo mode is the recommended starting point for learning the interface and checking expected behavior. Live mode is opt-in.

## Live Bitcoin mode

The Windows `start-live.cmd` launcher sets `VASP_MODE=live`. On macOS/Linux, set that environment variable before starting the backend.

The default provider base URL is:

```text
https://blockstream.info/api
```

To use another trusted Esplora-compatible endpoint, set `VASP_ESPLORA_URL` to its API base URL. The public Blockstream endpoint does not require an API key.

### Live trace behavior

- The existing `POST /api/trace` endpoint accepts checksum-valid Bitcoin mainnet addresses.
- The provider retrieves address transaction history and follows confirmed transaction outputs.
- History retrieval uses bounded pagination, retries, and tracing limits.
- The active mode is reported by `/api/health`.
- Real service labels are optional and loaded from `backend/data/labels.csv`; the file is intentionally empty by default.
- Live mode is read-only: it does not broadcast transactions, contact exchanges, freeze funds, or move assets.

### History completeness

A trace is bounded by hop, state, address-query, and per-address transaction-history limits. A result marked `limited`, or one that reports truncated address history, must be treated as incomplete.

The trace response can include a `history_diagnostics` object with fields such as:

- `transaction_limit_per_address`
- `truncated_addresses`
- `seed_history_truncated`

Check the current implementation and API schema before relying on these fields in downstream automation.

### Health check and API docs

After startup, inspect:

- **Health:** http://127.0.0.1:8000/api/health
- **Interactive API documentation:** http://127.0.0.1:8000/docs

The health endpoint reports runtime information such as mode and provider. A healthy API confirms service availability, not trace completeness or attribution accuracy.

### Attribution data and labels

Labels are loaded from `backend/data/labels.csv`. Add only labels from sources whose terms permit reuse, record their provenance, and independently validate them. The application does not independently certify the labels.

Do not copy synthetic demo labels into live attribution data or describe unverified labels as confirmed service ownership.

## Demo scenarios

The offline fixture dataset is designed to demonstrate tracing behavior without querying the live blockchain.

| Example | Expected result |
|---|---|
| **Direct deposit** | `Demo Exchange X`, one hop |
| **Multiple wallets** | `Demo Exchange Y` at two hops; `Demo Exchange X` at three hops |
| **Multiple wallets, hop limit 1** | Limited result; no labeled endpoint reached yet |
| **Unknown exchange** | One observed transfer, no service label |
| **Address outside sample dataset** | Not present in demo data; no conclusion about live activity |

The multi-wallet fixture includes a transfer before the incoming transfer and a failed transaction; both are excluded from the expected path. Service endpoints stop a branch.

The demo fixture address previously used for the direct-deposit test is:

```text
bc1q2cddfc9e7a49bf96802464b83c90b79c84c3ff
```

The expected `Demo Exchange X` result is synthetic and must never be presented as real-world attribution.

## AI Investigation Assistant

The floating assistant can use Google's Gemini API. The documented default model is `gemma-4-26b-a4b-it`.

The assistant is optional and disabled when `GEMINI_API_KEY` is not configured.

### Configure the API key

Set the key in one of these locations before starting the backend:

1. `backend/.env`
2. Project-root `.env`
3. Backend process environment

The backend-specific `.env` takes precedence over the project-root `.env`; existing process environment variables take precedence over both.

Add:

```dotenv
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_MODEL=gemma-4-26b-a4b-it
```

Use a real key from Google AI Studio. Do not commit `.env` files or API keys to source control.

#### Windows PowerShell

```powershell
$env:GEMINI_API_KEY = "your-google-ai-studio-key"
$env:GEMINI_MODEL = "gemma-4-26b-a4b-it"
.\start-demo.cmd
```

#### macOS / Linux

```sh
GEMINI_API_KEY="your-google-ai-studio-key" \
GEMINI_MODEL="gemma-4-26b-a4b-it" \
sh start-demo.sh
```

`GEMINI_MODEL` can be changed to another model ID enabled for the configured API key. Restart the server after changing environment variables or `.env` files.

### AI data handling and limitations

- The key stays on the backend and is not returned by `/api/health` or sent to the browser.
- When a message is submitted, a bounded summary of the selected case's transactions is sent to Google for the assistant response.
- Do not use the assistant with sensitive or restricted case data unless that transfer is authorized.
- Chat history is held in the browser and is not saved with the case.
- Assistant responses are advisory. They are not evidence, verified attribution, or legal conclusions, and should be checked independently.

## Architecture

VASP Desk uses a local frontend/backend design.

| Component | Responsibility |
|---|---|
| **React + TypeScript frontend** | Dashboard, investigation forms, graph and path inspection, cases, reports, directory, settings, guide, and assistant UI |
| **FastAPI backend** | HTTP API, input validation, trace coordination, SQLite persistence, and report endpoints |
| **Bitcoin provider** | Retrieves live address and transaction data from an Esplora-compatible API |
| **Bitcoin tracer** | Traverses transaction relationships within configured limits and returns trace results and diagnostics |
| **SQLite** | Stores case history and associated investigation metadata |
| **Attribution labels** | Optional address-to-service candidates with source/provenance information where provided |
| **Gemini integration** | Optional, on-demand AI assistant through a backend API client |
| **Compiled frontend** | `frontend/dist`, served for the Python-only local startup workflow |

Useful source locations documented for the current project:

- `frontend/src/main.tsx` — primary application views and interface
- `frontend/src/InvestigationAssistant.tsx` — AI chat interface
- `backend/main.py` — API, validation, persistence, and report routes
- `backend/exports.py` — evidence exports and printable reports
- `backend/ai/` — Gemini client and assistant prompt
- `backend/btc/` — Bitcoin provider and tracing implementation
- `backend/data/fixtures/bitcoin_demo.json` — Bitcoin demo fixture
- `backend/data/labels.csv` — optional live attribution labels
- `frontend/dist/` — compiled frontend
- `backend/requirements-lock.txt` and `frontend/package-lock.json` — dependency locks

See `STRUCTURE.md` for the current repository layout. File names and routes should be checked against the checked-out version before relying on this overview.

## Application API

The backend exposes a REST API. The interactive documentation at **http://127.0.0.1:8000/docs** is the authoritative place to inspect request and response schemas for the running version.

Previously documented routes include:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health and active-mode information |
| `GET` | `/api/examples` | Returns examples provided by the active mode/provider |
| `GET` | `/api/directory` | Service directory data |
| `POST` | `/api/trace` | Submit a trace request |
| `GET` | `/api/cases` | List saved cases |
| `GET` | `/api/summary` | Summary information |
| `GET` | `/api/cases/{case_id}` | Retrieve a saved case |
| `PATCH` | `/api/cases/{case_id}` | Update case metadata |
| `GET` | `/api/cases/{case_id}/report` | Retrieve/generate case report |
| `GET` | `/api/cases/{case_id}/export?format=json` | Export case data as JSON |
| `GET` | `/api/cases/{case_id}/export?format=csv` | Export case data as CSV |
| `GET` | `/api/cases/{case_id}/print` | Printable report output |
| `GET` | `/api/cases/{case_id}/draft` | Sample request draft |

Routes and response shapes may evolve. Use `/docs` rather than treating this table as a versioned API contract.

## Development setup

### 1. Create a virtual environment

From the repository root:

```powershell
py -3 -m venv .venv
```

On macOS/Linux, use `python3 -m venv .venv`.

### 2. Install development dependencies

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
```

macOS/Linux:

```sh
.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

### 3. Run the backend in reload mode

Windows:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux:

```sh
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Run the frontend development server

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally **http://127.0.0.1:5173**. Vite proxies `/api` requests to the Python backend.

After frontend changes, build the compiled UI:

```sh
npm run build
```

Restart the Python server and refresh the browser to use the updated compiled frontend on port 8000.

## Tests

Run backend tests from the repository root after installing development requirements.

Windows:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

macOS/Linux:

```sh
.venv/bin/python -m pytest backend/tests -q
```

The documented test scope includes chronological paths, branch ranking, hop truncation, unknown labels, date filters, invalid requests, persistence, and report retrieval. Inspect the current tests to confirm exact coverage.

A previous development run reported **36 passed, 1 warning**. This is a historical result, not a claim that the current checkout has just been tested. Rerun the test suite before publishing a new release or making changes.

## Data, reports, and case history

- Case runs are stored in `backend/cases.sqlite3`.
- The Cases and Reports pages load the latest 200 runs.
- Overview totals cover all saved runs.
- Reports support Markdown, JSON, and transaction CSV exports.
- The printable report uses the browser's **Print / Save as PDF** dialog.
- Investigator notes and review status are part of the case workflow.
- Amounts are represented as strings where applicable to avoid introducing binary floating-point rounding during display.

These are prototype reports and records, not certified legal evidence. Preserve original data, timestamps, source information, and relevant warnings when using exported results for further review.

### Upgrading an existing local copy

1. Stop the previous server.
2. Extract the new release into a separate folder.
3. Back up the old `backend/cases.sqlite3`.
4. If you need to retain case history, copy the backed-up database into the new `backend` folder before startup.
5. Do not copy the old `.venv` or old compiled frontend over the new release.

The project documentation states that existing case records are preserved while newer notes, review status, and activity schema are added automatically. Always make a backup first and test the migration on a copy.

## Privacy and security

- The app is designed for local use and has **no authentication**.
- Do not expose it to the public internet or a shared network without implementing and validating access controls and deployment security.
- Live mode sends searched Bitcoin addresses to the configured public Esplora endpoint. Provider operators may be able to observe those queries.
- The optional AI assistant sends a bounded summary of the selected case's transactions to Google when a message is submitted.
- Keep API keys in environment variables or ignored `.env` files; never commit secrets.
- Use only attribution data that you are permitted to reuse, and retain source/provenance information.
- Review logs, data retention, backups, dependency security, and case-data access before any broader deployment.

## Scope, limitations, and responsible use

VASP Desk is a learning and investigation-support prototype. Important limits include:

- Demo mode only demonstrates connectivity and behavior within its synthetic dataset.
- Live mode retrieves public Bitcoin blockchain data but does not establish exact ownership or provenance of blended funds.
- Paths are bounded by hop limits, explored-state limits, address-query limits, and address-history caps. Verify the active configuration in source.
- Mixers, CoinJoin, cross-chain bridges, and swaps are not resolved by the described tracing workflow.
- Live attribution labels are optional and are not independently validated by the application.
- Demo labels must never be treated as real exchange evidence.
- Public blockchain data does not, by itself, identify a person or organization controlling a wallet.
- A candidate label is not proof of ownership or control.
- A missing candidate does not prove that no VASP relationship exists.
- Provider outages, rate limits, incomplete pagination, or other failures can affect coverage.
- The AI assistant does not establish ownership or make verified investigative decisions.
- There is no login, SAHYOG connector, KYC access, or asset-freezing capability described by this project.

Before relying on live findings, validate provider behavior and attribution accuracy on independent cases. Record data coverage and independently verify every label and its source licence.

> **Disclaimer:** VASP Desk is an investigative support and learning tool. Results depend on public blockchain data, provider behavior, attribution sources, and configured tracing limits. An observed association is not definitive proof of wallet ownership or control. A missing result does not establish the absence of a relationship. Demo data is synthetic. Independently validate findings before making financial, compliance, legal, or investigative decisions.

## Troubleshooting

| Problem | What to try |
|---|---|
| Python is not found | Install Python 3.11+, enable PATH if appropriate, reopen the terminal, and try `py -3` or `python` |
| Port 8000 is already in use | Stop the older server or run Uvicorn on another port; update the Vite proxy if using a different backend port |
| UI edits are not visible | Use the Vite development URL, rebuild the frontend, or refresh after restarting Python |
| Compiled UI is blank | Confirm `frontend/dist` exists, run `npm run build`, restart Python, and refresh |
| Live trace fails | Check `/api/health`, internet connectivity, provider availability, and terminal logs |
| Live result is marked limited | Review the trace's history diagnostics and configured limits; do not interpret it as complete |
| No VASP candidate appears | Check mode, label data, provider coverage, and trace limits; absence of a label is not proof of no relationship |
| AI assistant is disabled | Configure `GEMINI_API_KEY`, verify the environment source, and restart the backend |
| Dependency installation fails | Check network connectivity and use the repository's requirements and lock files |

## Roadmap ideas

Potential improvements—not claims of currently implemented functionality:

- Stronger trace-quality and pagination diagnostics.
- Better provider retry, timeout, and rate-limit reporting.
- Expanded, independently sourced attribution data with provenance and confidence metadata.
- Reproducible live-trace fixtures and regression benchmarks.
- More explicit evidence provenance in exports and reports.
- Improved graph readability for large investigations.
- Authentication, authorization, and secure deployment support.
- Automated CI checks and release validation.
- Documented database migration and backup/restore procedures.
- Independent evaluation of attribution precision and recall.

## Documentation and project status

Start with these files in the repository:

- `START_HERE.txt` — first-run guidance.
- `STRUCTURE.md` — current layout and project status.
- `backend/requirements-lock.txt` — locked backend dependencies, if present.
- `frontend/package-lock.json` — locked frontend dependencies.

Useful upstream documentation:

- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Vite guide](https://vite.dev/guide/)
- [React Flow](https://reactflow.dev/)

### Before publishing

Check the current source tree and verify:
- startup scripts and supported Python/Node versions;
- exact API routes and response schemas;
- current tracing limits and diagnostics;
- current test results;
- the status of AI integration and environment-variable precedence;
- licensing and attribution-label provenance;
- whether screenshots, CI badges, or a licence file actually exist.

Do not add a licence badge, build badge, coverage percentage, security guarantee, or production-ready claim unless the repository supports it.

---

<div align="center">

**VASP Desk v0.3 · Bitcoin investigation prototype · Built for local learning and experimentation**

</div>
