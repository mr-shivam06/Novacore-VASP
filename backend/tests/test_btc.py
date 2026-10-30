import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.btc.heuristics import detect_change
from backend.btc.labels import load_labels
from backend.btc.models import normalize_tx
from backend.btc.providers import EsploraProvider, FixtureProvider
from backend.btc.scoring import score
from backend.btc.tracer import trace
from backend.btc.validate import is_valid_address

DATA = Path(__file__).parents[1] / 'data'
PROVIDER = FixtureProvider(DATA / 'fixtures' / 'bitcoin_demo.json')
LABELS = load_labels(DATA / 'labels.sample.csv')
SEEDS = [e['address'] for e in PROVIDER.examples]


def test_real_address_checksums():
    assert is_valid_address('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa')
    assert is_valid_address('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4')
    assert is_valid_address('BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4')
    assert not is_valid_address('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb')
    assert not is_valid_address('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5')
    assert not is_valid_address('0x0000000000000000000000000000000000000001')


def test_direct_deposit_and_unconfirmed_ignored():
    r = trace(SEEDS[0], PROVIDER, LABELS)
    assert r['nearest']['hops'] == 1 and r['nearest']['vasp'] == 'Demo Exchange X'
    assert r['nearest']['match'] == 'label'
    assert len(r['excluded_time_transfers']) == 1
    assert all(t['to'] != 'shady1' for t in r['transactions'])


def test_split_finds_three_endpoints_by_different_evidence():
    r = trace(SEEDS[1], PROVIDER, LABELS)
    by_match = {c['match']: c for c in r['candidates']}
    assert sorted(c['match'] for c in r['candidates']) == ['cluster', 'label', 'pattern']
    assert by_match['pattern']['hops'] == 1 and by_match['label']['hops'] == 2 and by_match['cluster']['hops'] == 3
    assert by_match['pattern']['confidence'] == 'Low'
    assert by_match['label']['vasp'] == 'Demo Exchange X'
    assert by_match['cluster']['vasp'] == 'Demo Exchange Y' and by_match['cluster']['via']
    assert r['nearest']['match'] == 'label'


def test_change_is_followed_without_adding_a_hop():
    r = trace(SEEDS[1], PROVIDER, LABELS)
    kinds = [t['kind'] for t in r['transactions']]
    assert 'change' in kinds
    pattern = next(c for c in r['candidates'] if c['match'] == 'pattern')
    assert [s['kind'] for s in pattern['transactions']] == ['change', 'payment']


def test_hop_limit_is_explicit():
    r = trace(SEEDS[1], PROVIDER, LABELS, max_hops=1)
    assert r['status'] == 'limited'
    assert r['nearest']['match'] == 'pattern'
    assert not [c for c in r['candidates'] if c['match'] != 'pattern']


def test_unknown_does_not_invent_an_exchange():
    r = trace(SEEDS[2], PROVIDER, LABELS)
    assert r['candidates'] == [] and r['nearest'] is None
    assert any('unspent' in text for text in r['limitations'])


def test_absent_address_and_date_filter():
    assert trace('bc1q' + 'f' * 38, PROVIDER, LABELS)['status'] == 'not_in_demo'
    late = datetime(2027, 1, 1, tzinfo=timezone.utc)
    r = trace(SEEDS[0], PROVIDER, LABELS, start=late)
    assert not r['candidates'] and not r['transactions']


def test_state_budget_marks_result_incomplete():
    r = trace(SEEDS[1], PROVIDER, LABELS, max_states=2)
    assert any('budget' in text for text in r['limitations'])


def _tx(types, values, input_types=None):
    return {'inputs': [{'type': t, 'address': 'in'} for t in (input_types or ['p2wpkh'])],
            'outputs': [{'n': i, 'address': f'out{i}', 'type': t, 'value': v} for i, (t, v) in enumerate(zip(types, values))]}


def test_change_detection_rules():
    assert detect_change(_tx(['p2wsh', 'p2wpkh'], [100_000_000, 99_954_321]), {'in'}) == (1, 'strong')
    assert detect_change(_tx(['p2wpkh', 'p2wpkh'], [100_000_000, 99_954_321]), {'in'}) == (1, 'weak')
    assert detect_change(_tx(['p2wpkh', 'p2wpkh'], [100_000_000, 200_000_000]), {'in'}) == (None, None)
    assert detect_change(_tx(['p2wpkh'], [100_000_000]), {'in'}) == (None, None)


def test_scoring_levels_and_reasons():
    verified = {'verified': True}
    unverified = {'verified': False}
    assert score('label', verified, 1, 0, 0, False)[0] == 'High'
    assert score('label', unverified, 1, 0, 0, False)[0] == 'Medium'
    assert score('cluster', unverified, 3, 0, 0, False)[0] == 'Medium'
    assert score('label', unverified, 3, 0, 2, True)[0] == 'Low'
    level, _, reasons = score('pattern', unverified, 0, 0, 0, False)
    assert level == 'Low' and reasons


def test_esplora_provider_paginates_and_parses():
    def make(i):
        return {'txid': f'{i:064x}', 'fee': 1, 'status': {'confirmed': True, 'block_time': 1760000000 + i},
                'vin': [{'txid': 'a' * 64, 'vout': 0, 'prevout': {'scriptpubkey_address': 'x', 'value': 5, 'scriptpubkey_type': 'v0_p2wpkh'}}],
                'vout': [{'scriptpubkey_address': 'y', 'value': 4, 'scriptpubkey_type': 'v0_p2wpkh'}, {'value': 0, 'scriptpubkey_type': 'op_return'}]}
    pages = {'https://api.test/address/y/txs': [make(i) for i in range(25)],
             f'https://api.test/address/y/txs/chain/{24:064x}': [make(i) for i in range(25, 30)]}
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]
    provider = EsploraProvider('https://api.test', fetch=fetch, pause=0)
    txs, cut = provider.address_txs('y', 100)
    assert len(txs) == 30 and not cut and len(calls) == 2
    assert txs[0]['outputs'][1]['address'] is None and txs[0]['confirmed']
    txs, cut = provider.address_txs('y', 10)
    assert len(txs) == 10 and cut



def test_esplora_paginates_when_full_page_includes_unconfirmed_tx():
    def make(i, confirmed=True):
        return {
            'txid': f'{i:064x}',
            'fee': 1,
            'status': (
                {'confirmed': True, 'block_time': 1760000000 + i}
                if confirmed else {'confirmed': False}
            ),
            'vin': [{
                'txid': 'a' * 64,
                'vout': 0,
                'prevout': {
                    'scriptpubkey_address': 'x',
                    'value': 5,
                    'scriptpubkey_type': 'v0_p2wpkh',
                },
            }],
            'vout': [{
                'scriptpubkey_address': 'y',
                'value': 4,
                'scriptpubkey_type': 'v0_p2wpkh',
            }],
        }

    first_page = [make(i) for i in range(24)] + [make(24, confirmed=False)]
    second_page = [make(25), make(26)]
    first_url = 'https://api.test/address/y/txs'
    next_url = f'https://api.test/address/y/txs/chain/{23:064x}'
    pages = {first_url: first_page, next_url: second_page}
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    provider = EsploraProvider('https://api.test', fetch=fetch, pause=0)
    txs, truncated = provider.address_txs('y', 100)

    assert len(txs) == 27
    assert calls == [first_url, next_url]
    assert not truncated

def test_unconfirmed_has_no_time():
    tx = normalize_tx({'txid': 'a' * 64, 'vin': [], 'vout': [], 'status': {'confirmed': False}})
    assert tx['time'] is None and not tx['confirmed']


def _addr(key):
    import hashlib
    return 'bc1q' + hashlib.sha256(key.encode()).hexdigest()[:38]


def test_profile_totals_and_counterparties():
    r = trace(SEEDS[1], PROVIDER, LABELS)
    p = r['profile']
    assert p['tx_count'] == 2 and p['total_received'] == '2.00000000' and p['total_sent'] == '2.00000000'
    assert p['balance'] == '0.00000000' and p['history_complete']
    assert p['incoming_counterparties'][0]['address'] == _addr('victim2')


def test_sources_are_traced_backwards_in_both_directions():
    middle = _addr('mule_a')
    r = trace(middle, PROVIDER, LABELS, max_hops=3)
    sources = {s['address']: s for s in r['sources']}
    assert sources[_addr('scam2')]['hops'] == 1 and sources[_addr('victim2')]['hops'] == 2
    directions = {t['direction'] for t in r['transactions']}
    assert directions == {'in', 'out'}
    assert any(c['match'] == 'cluster' for c in r['candidates'])
    short = trace(middle, PROVIDER, LABELS, max_hops=1)
    assert _addr('victim2') not in {s['address'] for s in short['sources']}
    assert any('Source tracing stopped' in t for t in short['limitations'])


def test_labeled_source_is_not_traced_past():
    r = trace(_addr('hot2'), PROVIDER, LABELS, max_hops=3)
    assert r['profile']['tx_count'] == 1
    assert {s['address'] for s in r['sources']} >= {_addr('dep2'), _addr('dep2_known')}


def test_report_contains_profile_and_sources():
    from backend.exports import markdown_report
    r = trace(SEEDS[0], PROVIDER, LABELS)
    r.update({'case_ref': 'X', 'id': '1', 'created': 'now', 'review_status': 'open', 'filters': {}, 'notes': ''})
    text = markdown_report(r)
    assert '## Address profile' in text and '## Where the money came from' in text


def test_demo004_accounting_and_unverified_attribution():
    seed = "bc1q2cddfc9e7a49bf96802464b83c90b79c84c3ff"

    result = trace(seed, PROVIDER, LABELS)

    # The seed's transaction accounting should remain correct.
    profile = result["profile"]
    assert profile["total_received"] == "0.80000000"
    assert profile["total_sent"] == "0.80000000"
    assert profile["balance"] == "0.00000000"

    # Find the exchange candidate without assuming it is verified.
    exchange = next(
        candidate
        for candidate in result["candidates"]
        if candidate.get("vasp") == "Demo Exchange X"
    )

    # The label is a candidate, not a verified attribution.
    assert exchange["label"]["verified"] is False

    # This is the transaction output value, not a proven seed-origin share.
    assert exchange["amount"] == "0.79990000"
    assert exchange["amount_basis"] == "transaction_output_value"
    assert exchange["share_upper_bound"] is None

    assert "seed-origin share" in exchange["amount_note"]
    assert "unknown" in exchange["amount_note"]
