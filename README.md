# VASP Desk v0.3: Bitcoin investigation tool

> v0.3 replaced the Ethereum demo with a Bitcoin engine. See STRUCTURE.md for the current layout and status. Sections below that mention Ethereum, ETH or engine.py describe v0.2 and are out of date.


An editable local learning project for the user-provided SIH 2026 PS 26182.
React + TypeScript frontend, Python FastAPI backend, SQLite case history.
The default mode uses synthetic transactions and demo labels. An opt-in live mode queries public
Bitcoin mainnet transaction history through Blockstream Esplora (or another compatible endpoint).

## Quick start

Start with **START_HERE.txt**. The compiled React frontend is included.
Windows: Python 3.11+ installed, then run `start-demo.cmd` for the offline demo or `start-live.cmd`
for live Bitcoin mainnet lookups. The launcher tries `py -3` and `python`.
macOS/Linux: Python 3.11+ with venv support, then run `sh start-demo.sh`.
For live mode on macOS/Linux, run `VASP_MODE=live sh start-demo.sh`. First setup downloads Python
dependencies. The offline demo requires no external API.
Open `http://127.0.0.1:8000` after the server starts. Keep the terminal open.
The app binds to your local computer. It has no authentication and is not ready for public hosting.
Live mode sends searched Bitcoin addresses to the configured public Esplora endpoint; use it only
if you are comfortable disclosing those queries to that provider. It is read-only and never broadcasts transactions.

## AI Investigation Assistant

The floating assistant uses Google's Gemini API with the `gemma-4-26b-a4b-it` model by default.
Set a Google AI Studio API key in `backend/.env`, a project-root `.env`, or the backend process
environment before starting the server. The backend-specific file takes precedence over the
project-root file; existing process environment variables take precedence over both. Add:

```dotenv
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_MODEL=gemma-4-26b-a4b-it
```

Alternatively, set the backend process environment variables:

Windows PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-google-ai-studio-key"
$env:GEMINI_MODEL = "gemma-4-26b-a4b-it"
.\start-demo.cmd
```

macOS/Linux:

```sh
GEMINI_API_KEY="your-google-ai-studio-key" GEMINI_MODEL="gemma-4-26b-a4b-it" sh start-demo.sh
```

`GEMINI_MODEL` can be changed to another model ID enabled for your Google API key. The key stays
on the backend and is never returned by `/api/health` or sent to the browser. The assistant is
disabled when `GEMINI_API_KEY` is unset. Existing process environment variables take precedence
over values in `.env`; restart the server after changing either source. Its replies are advisory,
not evidence or legal conclusions.
When you submit a message, the selected case's bounded transaction summary is sent to Google; do not
use it with sensitive or restricted case data unless that transfer is authorized. Chat history is
held in the browser only and is not saved with the case.


## Website features

- Overview with actual saved-case counts, recent investigations, and activity.
- Investigation forms with hop limits and optional UTC dates; interactive graph,
  address inspection, path highlighting, transaction search, and label sources.
- Persistent case references, investigator notes, and Open / Reviewed / Archived status.
- Searchable case workspace and service directory; browser-local hop preferences.
- Markdown, JSON, CSV, printable reports, and editable sample request drafts.
- English interface, responsive layout, and mode-aware live/offline data coverage notices.

## Upgrade safely

Stop your previous server first. Extract this release into a separate folder.
To retain history, back up and copy the old `backend/cases.sqlite3` into the new
`backend` folder before startup. Existing case records are preserved while the
new notes, review status, and activity schema is added automatically.
Do not copy the previous `.venv` or compiled frontend over this release.

## Demo expectations

| Example | Expected result |
|---|---|
| Direct deposit | Demo Exchange X, one hop |
| Multiple wallets | Demo Exchange Y at two hops, X at three hops |
| Multiple wallets, hop limit 1 | Limited result, no labeled endpoint yet |
| Unknown exchange | One observed transfer, no service label |
| Address outside sample dataset | Not in demo, no claim about live activity |

The multi-wallet fixture includes a transfer before the incoming transfer and a failed transaction.
Both are excluded. Service endpoints stop a branch. Case runs save to `backend/cases.sqlite3`.
The Cases and Reports pages load the latest 200 runs. Overview totals cover all saved runs.
Reports export Markdown, JSON, and transaction CSV. The printable report supports the
browser Print / Save as PDF dialog. These are prototype reports, not certified legal evidence.

## Live Bitcoin mode

The Windows `start-live.cmd` launcher sets `VASP_MODE=live`. Other platforms can set the same
environment variable before starting the backend. The live provider defaults to
`https://blockstream.info/api`; set `VASP_ESPLORA_URL` to a trusted Esplora-compatible API base URL
to use another provider. No API key is required for the public Blockstream endpoint.

The live API accepts checksum-valid Bitcoin mainnet addresses through the existing `POST /api/trace`
endpoint. It retrieves address history and follows confirmed transaction outputs with bounded
pagination, request retries, and hop/state limits. `/api/health` reports the active mode.
Real service labels are optional and loaded from `backend/data/labels.csv`; the file is intentionally
empty by default. Only add labels from sources whose terms permit reuse, and independently verify
them. Public chain data does not identify a wallet owner, and heuristics are not proof.
Live mode is read-only: it does not broadcast transactions, contact exchanges, or freeze funds.

## VS Code development

Open the project root folder in VS Code.
Install Node.js 22.12+ (or a newer supported LTS) for frontend development.

Terminal 1, project root:

```sh
py -3 -m venv .venv  # Windows; use python3 on macOS/Linux
```

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux:

```sh
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL Vite prints (normally `http://127.0.0.1:5173`).
Vite proxies `/api` to the Python server. No CORS configuration or API key is needed.
Run `npm run build` after UI edits, then restart Python to use the compiled UI on port 8000.

## Render deployment

Deploy the backend as a Render Web Service from the repository root, with build command
`pip install -r backend/requirements.txt` and start command
`uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. Set `VASP_CORS_ORIGINS` on
the backend to the exact public frontend origin, for example
`https://your-frontend.onrender.com` (no trailing slash).

Deploy `frontend` as a Render Static Site with build command `npm ci && npm run build`
and publish directory `dist`. Set `VITE_API_BASE_URL` to the backend's public origin,
for example `https://your-backend.onrender.com` (no `/api` suffix), then redeploy the
static site so Vite includes the setting in its build. If the frontend and backend
origins change, update these two environment variables accordingly.

## Tests

From project root, with dev requirements installed:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

Or `.venv/bin/python -m pytest backend/tests -q` on macOS/Linux.
Tests cover chronological paths, branch ranking, hop truncation, unknown labels,
date filters, invalid requests, persistence and report retrieval.

## Architecture

- `frontend/src/main.tsx`: overview, investigation graph, cases, reports, directory, settings, and guide.
- `backend/exports.py`: evidence exports and escaped printable reports.
- `backend/main.py`: HTTP API, input validation, SQLite storage and report endpoint.
- `backend/ai/`: on-demand Google Gemini API client and investigation prompt.
- `frontend/src/InvestigationAssistant.tsx`: case-aware AI chat interface.
- `backend/engine.py`: bounded traversal with per-path timestamps and cycle avoidance.
- `backend/data/demo.json`: explicit synthetic records and label provenance.
- `frontend/dist`: compiled frontend for Python-only startup.

Tracing uses a small purpose-built queue for this fixture. NetworkX can be added
when broader graph analysis is required. SQLite and built-in Python types keep setup small.
Amounts are strings so display does not introduce binary floating-point rounding.

## Actual scope and limits

Fixture mode only proves connectivity within its synthetic dataset. Live mode retrieves public
Bitcoin mainnet address history from Esplora, but does not establish exact provenance of blended
balances or wallet ownership. Paths are bounded by hops and 250 explored states, and address
history is capped. Mixers, CoinJoin, cross-chain bridges and swaps are not resolved. Labels in the
live CSV are not independently validated by the application; existing demo labels must never be
used as real exchange evidence. There is no login, SAHYOG connector, KYC access or freezing capability. The AI assistant does not
establish wallet ownership or automatically make investigative decisions.

Before relying on live results, validate the provider behavior and attribution accuracy on
independent cases. Record data coverage and verify each label's source and licence.

## Troubleshooting

- Python not found: reinstall with PATH enabled, restart the terminal.
- Port 8000 busy: close an older server or use `--port 8001` and open that URL.
  For Vite development, update the proxy if changing the backend port.
- UI edits not visible: use the Vite development URL or rebuild frontend and refresh.
- Blank compiled UI: ensure `frontend/dist` exists and restart Python after building.
- Internet installation error: check connectivity; setup does not need paid API access.

## Primary documentation

- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- Vite setup: https://vite.dev/guide/
- React Flow: https://reactflow.dev/

Dependency versions used during validation are recorded in backend/requirements-lock.txt
and frontend/package-lock.json. No real case data or secrets ship in this archive.
