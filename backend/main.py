import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from threading import Lock
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from dotenv import load_dotenv
from .btc.labels import load_labels
from .btc.providers import EsploraProvider, FixtureProvider, ProviderError
from .btc.tracer import trace
from .btc.validate import is_valid_address, normalize_address
from .exports import markdown_report, csv_report, printable_report
from .ai.ai_Service import AIServiceError, generate_assistant_reply
from typing import Literal
BASE = Path(__file__).resolve().parent


def _load_backend_dotenv() -> None:
    load_dotenv(BASE / '.env')
    load_dotenv(BASE.parent / '.env')


_load_backend_dotenv()
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemma-4-26b-a4b-it').strip()
# Use live blockchain data by default. Fixture mode is an explicit opt-in.
MODE = os.environ.get('VASP_MODE', 'live').strip().lower()
if MODE not in ('fixture', 'live'):
    raise RuntimeError("VASP_MODE must be 'fixture' or 'live'")
ESPLORA_URL = os.environ.get(
    'VASP_ESPLORA_URL', 'https://blockstream.info/api'
).strip().rstrip('/')
if MODE == 'live':
    PROVIDER = EsploraProvider(ESPLORA_URL)
    # Live mode must use the live labels file only. Do not fall back to
    # labels.sample.csv: those labels are for synthetic demo data.
    LABELS_PATH = Path(
        os.environ.get('VASP_LABELS', str(BASE / 'data' / 'labels.csv'))
    ).expanduser()
    if not LABELS_PATH.is_absolute():
        LABELS_PATH = (Path.cwd() / LABELS_PATH).resolve()
    LABELS = load_labels(str(LABELS_PATH))
else:
    PROVIDER = FixtureProvider(BASE / 'data' / 'fixtures' / 'bitcoin_demo.json')
    LABELS_PATH = BASE / 'data' / 'labels.sample.csv'
    LABELS = load_labels(str(LABELS_PATH))
DB_PATH = Path(os.environ.get('VASP_DB_PATH', str(BASE / 'cases.sqlite3'))).expanduser()
if not DB_PATH.is_absolute():
    DB_PATH = (Path.cwd() / DB_PATH).resolve()
app = FastAPI(title='VASP Desk', version='0.3.0')
SCHEMA_LOCK = Lock()
@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    with SCHEMA_LOCK:
        connection.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, case_ref TEXT, created TEXT, result TEXT)')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(cases)')}
        for name, definition in [('notes', "TEXT NOT NULL DEFAULT ''"),
                                 ('review_status', "TEXT NOT NULL DEFAULT 'open'"),
                                 ('updated', "TEXT NOT NULL DEFAULT ''")]:
            if name not in columns:
                connection.execute(f'ALTER TABLE cases ADD COLUMN {name} {definition}')
        connection.execute('CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, action TEXT, created TEXT)')
        connection.commit()
    try:
        with connection:
            yield connection
    finally:
        connection.close()
class TraceRequest(BaseModel):
    case_ref: str = Field(default='DEMO-001', min_length=1, max_length=60, pattern=r'^[A-Za-z0-9 _-]+$')
    address: str = Field(min_length=14, max_length=90, pattern=r'^[A-Za-z0-9]+$')
    network: str = 'bitcoin'
    max_hops: int = Field(default=3, ge=1, le=5)
    start: datetime | None = None
    end: datetime | None = None
    @field_validator('start', 'end')
    @classmethod
    def require_timezone(cls, value):
        if value and value.tzinfo is None:
            raise ValueError('Dates must include timezone, e.g. 2026-10-01T00:00:00Z')
        return value
    @model_validator(mode='after')
    def validate_range(self):
        if self.network != 'bitcoin':
            raise ValueError('Only bitcoin is supported in this version')
        if self.start and self.end and self.start > self.end:
            raise ValueError('Start must not be after end')
        return self
class AssistantMessage(BaseModel):
    role: Literal['user', 'model']
    content: str = Field(min_length=1, max_length=2000)
    @field_validator('content')
    @classmethod
    def require_message_text(cls, value):
        if not value.strip():
            raise ValueError('Messages cannot be blank')
        return value
class AssistantRequest(BaseModel):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=10)
    @model_validator(mode='after')
    def validate_conversation(self):
        if self.messages[0].role != 'user' or self.messages[-1].role != 'user':
            raise ValueError('Conversation must start and end with an investigator message')
        if any(
            current.role == previous.role
            for previous, current in zip(self.messages, self.messages[1:])
        ):
            raise ValueError('Conversation messages must alternate roles')
        return self
@app.get('/api/health')
def health():
    return {
        'status': 'ok',
        'mode': MODE,
        'labels': len(LABELS),
        'labels_file': str(LABELS_PATH),
        'provider': 'esplora' if MODE == 'live' else 'fixture',
        'ai': {
            'enabled': bool(GEMINI_API_KEY),
            'provider': 'Google Gemini API',
            'model': GEMINI_MODEL,
        },
        'warning': (
            'No live VASP labels loaded; attribution to known VASPs is unavailable.'
            if MODE == 'live' and not LABELS
            else None
        ),
    }
@app.get('/api/examples')
def examples():
    return PROVIDER.examples
@app.get('/api/directory')
def directory():
    return [{'address': a, 'name': PROVIDER.names.get(a, label['entity']), 'network': 'Bitcoin', **label}
            for a, label in LABELS.items()]
@app.post('/api/trace')
def run_trace(request: TraceRequest):
    address = normalize_address(request.address)
    if not (PROVIDER.knows(address) or is_valid_address(address)):
        raise HTTPException(422, 'This is not a valid Bitcoin address (checksum failed)')
    if MODE == 'live' and not is_valid_address(address):
        raise HTTPException(422, 'This is not a valid Bitcoin address (checksum failed)')
    try:
        result = trace(address, PROVIDER, LABELS, request.max_hops, request.start, request.end)
        # Apply configured labels to every matching address object in the trace.
        # Unverified labels are candidates, never confirmed ownership.
        def apply_labels(value):
            if isinstance(value, dict):
                raw_address = value.get("address")
                if isinstance(raw_address, str):
                    label = LABELS.get(normalize_address(raw_address))
                    if label:
                        verified = bool(label.get("verified", False))
                        entity = label.get("entity") or "Unknown entity"
                        value["name"] = entity if verified else f"{entity} (unverified candidate)"
                        value["label"] = {**label, "verified": verified}
                        value["attribution_status"] = (
                            "verified" if verified else "unverified_candidate"
                        )
                for child in value.values():
                    apply_labels(child)
            elif isinstance(value, list):
                for child in value:
                    apply_labels(child)
        apply_labels(result)
        # Ensure the starting wallet profile is labeled consistently too.
        # A label marked verified=false is only a candidate, not confirmed ownership.
        seed_label = LABELS.get(address)
        profile = result.get("profile")
        if seed_label:
            is_verified = bool(seed_label.get("verified", False))
            entity = seed_label.get("entity") or "Unknown entity"
            result["attribution_status"] = (
                "verified" if is_verified else "unverified_candidate"
            )
            if isinstance(profile, dict):
                profile["name"] = (
                    entity if is_verified
                    else f"{entity} (unverified candidate)"
                )
                profile["label"] = {**seed_label, "verified": is_verified}
                profile["attribution_status"] = (
                    "verified" if is_verified else "unverified_candidate"
                )
    except ProviderError as error:
        raise HTTPException(502, str(error))
    result.update({'id': str(uuid4()), 'case_ref': request.case_ref,
                   'created': datetime.now(timezone.utc).isoformat(),
                   'filters': {'start': request.start.isoformat() if request.start else None,
                               'end': request.end.isoformat() if request.end else None}})
    with db() as connection:
        connection.execute('INSERT INTO cases (id, case_ref, created, result) VALUES (?, ?, ?, ?)',
                           (result['id'], result['case_ref'], result['created'], json.dumps(result)))
        connection.execute('INSERT INTO activity (case_id, action, created) VALUES (?, ?, ?)',
                           (result['id'], 'Investigation created', result['created']))
    return get_result(result['id'])
@app.get('/api/cases')
def cases(search: str = Query(default='', max_length=100), review: str = 'all',
          limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    if review not in ('all', 'open', 'reviewed', 'archived'):
        raise HTTPException(422, 'Invalid review status')
    with db() as connection:
        # INSTR treats the search literally, including '%' and '_'.
        rows = connection.execute('SELECT id, case_ref, created, result, review_status FROM cases '
                                  'WHERE (INSTR(LOWER(case_ref), LOWER(?)) > 0 OR INSTR(LOWER(result), LOWER(?)) > 0) '
                                  'AND (? = ? OR review_status = ?) ORDER BY created DESC LIMIT ? OFFSET ?',
                                  (search, search, review, 'all', review, limit, offset)).fetchall()
    records = []
    for row in rows:
        result = json.loads(row[3])
        records.append({'id': row[0], 'case_ref': row[1], 'created': row[2], 'review_status': row[4],
                        'status': result['status'], 'seed': result['seed'],
                        'nearest_vasp': result['nearest']['vasp'] if result['nearest'] else None,
                        'transfer_count': len(result['transactions']),
                        'candidate_count': len(result['candidates'])})
    return records
@app.get('/api/summary')
def summary():
    with db() as connection:
        rows = connection.execute('SELECT result, review_status FROM cases').fetchall()
        events = connection.execute('SELECT a.case_id, a.action, a.created, c.case_ref FROM activity a '
                                    'JOIN cases c ON c.id = a.case_id ORDER BY a.id DESC LIMIT 8').fetchall()
    results = [json.loads(row[0]) for row in rows]
    return {'total': len(rows), 'open': sum(row[1] == 'open' for row in rows),
            'reviewed': sum(row[1] == 'reviewed' for row in rows),
            'archived': sum(row[1] == 'archived' for row in rows),
            'with_candidates': sum(bool(r['candidates']) for r in results),
            'unresolved': sum(not r['candidates'] for r in results),
            'limited': sum(r['status'] == 'limited' for r in results),
            'activity': [{'case_id': e[0], 'action': e[1], 'created': e[2], 'case_ref': e[3]} for e in events]}
def _normalize_candidate(candidate, seed):
    """Normalize saved candidate fields without overstating attribution."""
    if not isinstance(candidate, dict):
        return candidate

    candidate = dict(candidate)
    label = candidate.get("label") or {}
    verified = label.get("verified") is True
    candidate["attribution_status"] = (
        "verified" if verified else "unverified_candidate"
    )
    candidate["share_upper_bound"] = None

    if candidate.get("address") == seed and candidate.get("hops") == 0:
        if candidate.get("amount") is not None:
            candidate["address_total_received"] = candidate.get("amount")
        candidate["amount"] = None
        candidate["amount_basis"] = "unknown_attributable_amount"
        candidate["amount_note"] = (
            "No amount has been established as attributable to this entity. "
            "The wallet's total received amount is an address-level statistic, "
            "not proof that all funds belong to the labeled entity. "
            "The seed-origin share is unknown."
        )
    else:
        if not candidate.get("amount_basis"):
            candidate["amount_basis"] = "transaction_output_value"
        if not candidate.get("amount_note"):
            candidate["amount_note"] = (
                "The displayed transaction output value does not establish the "
                "amount originating from the seed. The attributable share is unknown."
            )

    if not verified:
        entity = label.get("entity") or candidate.get("vasp") or "Unknown entity"
        candidate["name"] = f"{entity} (unverified candidate)"

    return candidate


def get_result(case_id):
    with db() as connection:
        row = connection.execute(
            'SELECT result, notes, review_status, updated, case_ref '
            'FROM cases WHERE id = ?',
            (case_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, 'Case not found')
    result = json.loads(row[0])
    seed = result.get("seed")

    # Normalize persisted cases at read time, including older saved cases.
    seed_label = LABELS.get(normalize_address(seed)) if isinstance(seed, str) else None
    if seed_label:
        verified = seed_label.get("verified") is True
        result["attribution_status"] = (
            "verified" if verified else "unverified_candidate"
        )

    profile = result.get("profile")
    if isinstance(profile, dict):
        profile = dict(profile)
        profile_label = profile.get("label") or seed_label
        if profile_label:
            verified = profile_label.get("verified") is True
            entity = profile_label.get("entity") or "Unknown entity"
            profile["label"] = {**profile_label, "verified": verified}
            profile["name"] = entity if verified else f"{entity} (unverified candidate)"
            profile["attribution_status"] = (
                "verified" if verified else "unverified_candidate"
            )
        result["profile"] = profile

    result["candidates"] = [
        _normalize_candidate(candidate, seed)
        for candidate in (result.get("candidates") or [])
    ]
    nearest = result.get("nearest")
    if isinstance(nearest, dict):
        result["nearest"] = _normalize_candidate(nearest, seed)
    result.update({
        'notes': row[1],
        'review_status': row[2],
        'updated': row[3] or result['created'],
        'case_ref': row[4],
    })
    return result
def _assistant_case_context(result):
    profile = result.get('profile') or {}
    candidates = []
    for candidate in (result.get('candidates') or [])[:20]:
        label = candidate.get('label') or {}
        candidates.append({
            'service': candidate.get('vasp'),
            'address': candidate.get('address'),
            'hops': candidate.get('hops'),
            'match': candidate.get('match'),
            'confidence': candidate.get('confidence'),
            'confidence_score': candidate.get('confidence_score'),
            'attribution_status': candidate.get('attribution_status'),
            'label': {
                'entity': label.get('entity'),
                'source': label.get('source'),
                'verified': label.get('verified') is True,
            },
            'reasons': (candidate.get('reasons') or [])[:10],
            'transactions': [
                {
                    'id': transaction.get('id'),
                    'from': transaction.get('from'),
                    'to': transaction.get('to'),
                    'amount': transaction.get('amount'),
                    'timestamp': transaction.get('timestamp'),
                }
                for transaction in (candidate.get('transactions') or [])[:10]
            ],
        })
    return {
        'case_ref': result.get('case_ref'),
        'network': result.get('network'),
        'mode': result.get('mode'),
        'status': result.get('status'),
        'seed': result.get('seed'),
        'profile': {
            key: profile.get(key)
            for key in (
                'tx_count', 'first_seen', 'last_seen', 'total_received',
                'total_sent', 'balance', 'history_complete', 'deposit_like',
            )
            if key in profile
        },
        'limitations': (result.get('limitations') or [])[:30],
        'candidates': candidates,
        'transactions': [
            {
                'id': transaction.get('id'),
                'from': transaction.get('from'),
                'to': transaction.get('to'),
                'amount': transaction.get('amount'),
                'timestamp': transaction.get('timestamp'),
                'direction': transaction.get('direction'),
            }
            for transaction in (result.get('transactions') or [])[:100]
        ],
    }
@app.post('/api/cases/{case_id}/assistant')
def ask_assistant(case_id: str, request: AssistantRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(
            503,
            'AI assistant is not configured. Set GEMINI_API_KEY on the backend and restart it.',
        )
    result = get_result(case_id)
    messages = [message.model_dump() for message in request.messages]
    try:
        answer = generate_assistant_reply(
            messages,
            _assistant_case_context(result),
            GEMINI_API_KEY,
            GEMINI_MODEL,
        )
    except AIServiceError as error:
        raise HTTPException(502, str(error)) from error
    return {'answer': answer, 'model': GEMINI_MODEL}
@app.get('/api/cases/{case_id}')
def case(case_id: str):
    return get_result(case_id)
class CaseUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=5000)
    review_status: Literal['open', 'reviewed', 'archived'] | None = None
    case_ref: str | None = Field(default=None, min_length=1, max_length=60, pattern=r'^[A-Za-z0-9 _-]+$')
@app.patch('/api/cases/{case_id}')
def update_case(case_id: str, request: CaseUpdate):
    get_result(case_id)
    updates = request.model_dump(exclude_none=True)
    if updates:
        updates['updated'] = datetime.now(timezone.utc).isoformat()
        with db() as connection:
            setters = ', '.join(name + ' = ?' for name in updates)
            connection.execute(f'UPDATE cases SET {setters} WHERE id = ?', [*updates.values(), case_id])
            action = 'Case archived' if request.review_status == 'archived' else 'Review and notes updated'
            connection.execute('INSERT INTO activity (case_id, action, created) VALUES (?, ?, ?)',
                               (case_id, action, updates['updated']))
    return get_result(case_id)
@app.get('/api/cases/{case_id}/report', response_class=PlainTextResponse)
def report(case_id: str):
    r = get_result(case_id)
    return PlainTextResponse(markdown_report(r), headers={'Content-Disposition': f'attachment; filename="vasp-report-{r["id"]}.md"'})
@app.get('/api/cases/{case_id}/export')
def export(case_id: str, format: Literal['json', 'csv'] = 'json'):
    r = get_result(case_id)
    headers = {'Content-Disposition': f'attachment; filename="vasp-evidence-{r["id"]}.{format}"'}
    if format == 'json':
        return JSONResponse(r, headers=headers)
    return PlainTextResponse(csv_report(r), media_type='text/csv', headers=headers)
@app.get('/api/cases/{case_id}/print', response_class=HTMLResponse)
def print_report(case_id: str):
    return HTMLResponse(printable_report(get_result(case_id)))
@app.get('/api/cases/{case_id}/draft')
def draft(case_id: str, candidate: int = Query(default=0, ge=0)):
    r = get_result(case_id)
    if candidate >= len(r['candidates']):
        raise HTTPException(422, 'A labeled candidate is required for a sample request draft')
    c = r['candidates'][candidate]
    return {'text': '\n'.join(['SAMPLE REQUEST DRAFT — NOT SENT', '', f"Case: {r['case_ref']}",
            f"Demo recipient: {c['vasp']}", f"Network: {r['network']}", f"Deposit address: {c['address']}",
            'Supporting references: ' + ', '.join(t['id'] for t in c['transactions']), '',
            f"Match type: {c['match']} | Confidence: {c['confidence']}",
            'Purpose: illustrate a request for relevant account and deposit records.',
            ('All labels and references are synthetic.' if r.get('mode') == 'fixture' else 'Labels come from the configured label file. Check each source before relying on it.'),
            'An authorized investigator must establish the actual recipient, legal basis and evidence before any real request.',
            'SAHYOG integration is unavailable. This draft does not send or freeze anything.'])}
DIST = BASE.parent / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='frontend')