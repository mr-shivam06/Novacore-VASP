import importlib
import io
import json
import os

from fastapi.testclient import TestClient


def test_assistant_prompt_requires_investigation_sections_and_risk_table():
    from backend.ai.prompts import build_assistant_prompt

    prompt = build_assistant_prompt({'case_ref': 'CASE-1'})

    for section in (
        '## Wallet Overview',
        '## Transaction Flow',
        '## Suspicious Activity',
        '## Evidence and Limitations',
        '## Next Investigation Steps',
        '## Risk Assessment',
        'Start with a short title containing the case reference',
        "'**Observed behavior**' and '**Not established**'",
        'Do not invent a numeric risk score',
        'High transaction frequency',
        'Mixer interaction',
        'Suspicious address connection',
        'Known illicit address exposure',
    ):
        assert section in prompt


def client(tmp_path, monkeypatch, api_key='test-key'):
    monkeypatch.setenv('VASP_DB_PATH', str(tmp_path / 'cases.sqlite3'))
    monkeypatch.setenv('VASP_MODE', 'fixture')
    monkeypatch.setenv('GEMINI_API_KEY', api_key or '')
    from backend import main
    importlib.reload(main)
    return TestClient(main.app), main


def test_dotenv_loads_backend_key_without_overriding_process_environment(
    tmp_path, monkeypatch
):
    from backend import main

    backend_dir = tmp_path / 'backend'
    backend_dir.mkdir()
    (backend_dir / '.env').write_text(
        'GEMINI_API_KEY=backend-dotenv-key\n',
        encoding='utf-8',
    )
    (tmp_path / '.env').write_text(
        'GEMINI_API_KEY=dotenv-key\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(main, 'BASE', backend_dir)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)

    main._load_backend_dotenv()
    assert os.environ['GEMINI_API_KEY'] == 'backend-dotenv-key'

    monkeypatch.setenv('GEMINI_API_KEY', 'process-key')
    main._load_backend_dotenv()
    assert os.environ['GEMINI_API_KEY'] == 'process-key'


def test_assistant_uses_saved_case_context_and_hides_api_key(tmp_path, monkeypatch):
    test_client, main = client(tmp_path, monkeypatch)
    seed = test_client.get('/api/examples').json()[0]['address']
    case = test_client.post('/api/trace', json={'address': seed}).json()
    captured = {}

    def fake_reply(messages, context, api_key, model):
        captured.update(messages=messages, context=context, api_key=api_key, model=model)
        return 'Review the source label before drawing a conclusion.'

    monkeypatch.setattr(main, 'generate_assistant_reply', fake_reply)
    response = test_client.post(
        f"/api/cases/{case['id']}/assistant",
        json={'messages': [{'role': 'user', 'content': 'What should I verify?'}]},
    )

    assert response.status_code == 200
    assert response.json()['answer'].startswith('Review the source label')
    assert captured['context']['case_ref'] == case['case_ref']
    assert captured['context']['seed'] == seed
    assert captured['messages'][0]['content'] == 'What should I verify?'
    assert captured['api_key'] == 'test-key'
    assert 'test-key' not in test_client.get('/api/health').text


def test_assistant_requires_server_api_key_and_valid_conversation(tmp_path, monkeypatch):
    test_client, _ = client(tmp_path, monkeypatch, api_key='')
    seed = test_client.get('/api/examples').json()[0]['address']
    case = test_client.post('/api/trace', json={'address': seed}).json()
    endpoint = f"/api/cases/{case['id']}/assistant"

    assert test_client.post(
        endpoint, json={'messages': [{'role': 'user', 'content': 'Analyze this'}]}
    ).status_code == 503
    assert test_client.get('/api/health').json()['ai']['enabled'] is False

    main = importlib.import_module('backend.main')
    main.GEMINI_API_KEY = 'test-key'
    invalid = test_client.post(endpoint, json={'messages': [
        {'role': 'user', 'content': 'First'},
        {'role': 'user', 'content': 'Repeated role'},
    ]})
    assert invalid.status_code == 422


def test_assistant_accepts_long_previous_model_response(tmp_path, monkeypatch):
    test_client, main = client(tmp_path, monkeypatch, api_key='test-key')
    seed = test_client.get('/api/examples').json()[0]['address']
    case = test_client.post('/api/trace', json={'address': seed}).json()
    monkeypatch.setattr(
        main,
        'generate_assistant_reply',
        lambda messages, context, api_key, model: 'Follow-up response',
    )

    response = test_client.post(
        f"/api/cases/{case['id']}/assistant",
        json={'messages': [
            {'role': 'user', 'content': 'First question'},
            {'role': 'model', 'content': 'x' * 3000},
            {'role': 'user', 'content': 'Follow-up question'},
        ]},
    )

    assert response.status_code == 200


def test_gemini_request_uses_configured_model_and_parses_reply(monkeypatch):
    from backend.ai import ai_Service

    captured = {}

    def fake_urlopen(request, timeout):
        captured['request'] = request
        captured['timeout'] = timeout
        return io.BytesIO(json.dumps({
            'candidates': [{'content': {'parts': [{'text': 'A careful finding.'}]}}],
        }).encode())

    monkeypatch.setattr(ai_Service, 'urlopen', fake_urlopen)
    answer = ai_Service.generate_assistant_reply(
        [{'role': 'user', 'content': 'Summarize the observed evidence.'}],
        {'case_ref': 'CASE-1'},
        'private-key',
        'gemma-4-26b-a4b-it',
    )

    request = captured['request']
    assert answer == 'A careful finding.'
    assert request.full_url.endswith('/models/gemma-4-26b-a4b-it:generateContent')
    assert request.get_header('X-goog-api-key') == 'private-key'
    assert 'private-key' not in request.full_url
    assert captured['timeout'] == 30
