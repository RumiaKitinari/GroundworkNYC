from unittest.mock import patch

import pytest
from flask import jsonify

from site_advisor import build_evidence, local_summary, site_brief, wording_choices


@pytest.fixture
def dashboard():
    return {
        'locations': [{'id': f'3608100000{i}', 'name': f'Area {i}', 'opportunity': 80 - i,
                       'walkability': 65 + i, 'market_profile': {'population': 1200, 'jobs': 0},
                       'concept_evidence': {'same_cuisine_count': None}} for i in range(4)],
        'saved_locations': [{'id': '36081000009', 'name': 'Saved area', 'opportunity': 75}],
        'properties': [{'location_id': '36081000000', 'lead_type': 'synthetic'}],
        'meta': {'data_release': 'test-release'}, 'finance': {'required_covers_per_day': 44},
    }


def test_uses_server_order_and_real_zeroes(dashboard):
    evidence = build_evidence(dashboard)
    assert [r['id'] for r in evidence['sites']] == ['36081000000', '36081000001', '36081000002']
    facts = {f['id']: f for f in evidence['sites'][0]['facts']}
    assert facts['jobs']['value'] == '0'
    assert facts['rent']['value'] is None
    assert facts['competition']['value'] is None
    assert facts['synthetic']['value'] == '1'
    assert 'not available listings' in facts['synthetic']['basis']
    assert '44 covers/day' in evidence['economics']


def test_saved_sites_stay_selected(dashboard):
    evidence = build_evidence(dashboard, ['36081000009', '36081000009', 'invalid', '36081000002'])
    assert [r['id'] for r in evidence['sites']] == ['36081000009', '36081000002']


def test_model_cannot_add_or_change_facts(dashboard):
    evidence = build_evidence(dashboard)
    options = wording_choices(evidence)
    result = site_brief(evidence, lambda _: ({k: v[-1] for k, v in options.items()}, {}))
    assert result['mode'] == 'local_model'
    assert result['summary'] == ' '.join(v[-1] for v in options.values())
    invented = {k: v[-1] for k, v in options.items()}
    invented['site1'] += ' Guaranteed to earn $1 million.'
    result = site_brief(evidence, lambda _: (invented, {}))
    assert result['mode'] == 'template'
    assert 'Guaranteed' not in result['summary']


def test_model_unavailable_falls_back(dashboard):
    def unavailable(_):
        raise OSError('unavailable')
    result = site_brief(build_evidence(dashboard), unavailable)
    assert result['mode'] == 'template'
    assert '80/100' in result['summary']


def test_does_not_infer_if_other_model_loaded():
    with patch('site_advisor.loaded_models', return_value=[{'name': 'another-model'}]), patch('site_advisor._request') as request:
        with pytest.raises(RuntimeError, match='another_model_loaded'):
            local_summary({'site1': ['Evidence sentence.']})
        request.assert_not_called()


def test_http_endpoint_reuses_dashboard_and_ignores_client_facts(dashboard):
    from app import app
    with app.test_client() as client, patch('app.dashboard', side_effect=lambda: jsonify(dashboard)), \
            patch('site_advisor._request', side_effect=OSError('unavailable')):
        assert client.post('/api/site-brief').status_code == 415
        response = client.post('/api/site-brief?saved_id=36081000009', json={'opportunity': 100})
    assert response.status_code == 200
    result = response.get_json()
    assert result['mode'] == 'template'
    assert result['sites'][0]['id'] == '36081000009'
    assert '75/100' in result['summary']
    assert '100/100' not in result['summary']


def test_scenario_applies_only_explicit_changes():
    from werkzeug.datastructures import MultiDict
    from site_advisor import scenario_arguments

    original = MultiDict([('price_mode', 'tier'), ('price_tier', '$$'), ('daypart', 'evening'),
                          ('borough', 'Queens'), ('saved_id', '36081000001'), ('saved_id', '36081000002')])
    changed = scenario_arguments(original, {'average_check': 25, 'daypart': 'lunch'})
    assert original['price_mode'] == 'tier' and original['daypart'] == 'evening'
    assert changed['price_mode'] == 'exact' and changed['average_check'] == '25'
    assert changed['daypart'] == 'lunch' and changed['borough'] == 'Queens'
    assert changed.getlist('saved_id') == original.getlist('saved_id')
    for invalid in ({}, {'sort_by': 'opportunity'}, {'daypart': []}, {'average_check': True},
                    {'average_check': float('nan')}, {'average_check': 251}, {'average_check': 10**400}):
        with pytest.raises(ValueError):
            scenario_arguments(original, invalid)


def test_comparison_preserves_engine_order_and_scoring_basis(dashboard):
    from copy import deepcopy
    from site_advisor import compare_rankings

    dashboard['meta']['sort_by'] = 'inverse_walkability'
    for i, row in enumerate(dashboard['locations']):
        row['inverse_walkability'] = 90 - i
    after = deepcopy(dashboard)
    after['locations'] = [after['locations'][1], after['locations'][3], after['locations'][0]]
    result = compare_rankings(dashboard, after)
    assert [r['name'] for r in result['entered']] == ['Area 3']
    assert [r['name'] for r in result['left']] == ['Area 2']
    assert [(r['previous_rank'], r['current_rank']) for r in result['retained']] == [(2, 1), (1, 3)]
    assert result['after'][0]['score'] == 89
    after['meta']['data_release'] = 'new-release'
    with pytest.raises(ValueError, match='release'):
        compare_rankings(dashboard, after)


def test_scenario_http_reranks_both_inputs_without_model(dashboard):
    from copy import deepcopy
    from app import app
    from scoring import resolve_concept

    def rank(args, *, advisor_snapshot=False):
        assert advisor_snapshot
        result = deepcopy(dashboard)
        concept = resolve_concept(args)['concept']
        result['meta']['concept'] = concept
        if concept['daypart'] == 'lunch':
            result['locations'].reverse()
        return jsonify(result)

    with app.test_client() as client, patch('app._dashboard', side_effect=rank) as engine, \
            patch('site_advisor._request') as inference:
        response = client.post('/api/site-brief/scenario?cuisine=italian&daypart=evening&borough=Queens',
                               json={'average_check': 25, 'daypart': 'lunch'})
        assert response.status_code == 200
        assert engine.call_count == 2
        assert all(c.args[0]['borough'] == 'Queens' for c in engine.call_args_list)
        result = response.get_json()
        assert result['inputs'] == [{'average_check': 35, 'daypart': 'evening'}, {'average_check': 25, 'daypart': 'lunch'}]
        assert result['entered'][0]['name'] == 'Area 3'
        inference.assert_not_called()
        assert client.post('/api/site-brief/scenario', json={'borough': 'Brooklyn'}).status_code == 400


def test_empty_scenario_does_not_claim_all_sites_left(dashboard):
    from app import app
    with app.test_client() as client, patch('app._dashboard', side_effect=lambda args, **kwargs: jsonify(
            {'locations': []} if args.get('daypart') == 'lunch' else dashboard)):
        response = client.post('/api/site-brief/scenario', json={'daypart': 'lunch'})
        assert response.status_code == 422
        assert 'insufficient' in response.get_json()['error']


def test_decision_lab_routes_share_scope_and_guard_stale_dossiers(monkeypatch):
    import app as module

    site_id = '36081000100'
    calls = []

    def rank(inputs, package, **kwargs):
        calls.append((inputs.borough, inputs.concept.average_check, inputs.concept.daypart))
        return ([{'id': site_id, 'name': 'Example tract', 'opportunity': 80}],
                {'ranking_mode': 'screening'}, {'status': 'not_assessed'})

    def dossier(inputs, package, rows, survival, access, *, deep=False):
        return {'sites': [{**row, 'next_check': {'label': 'Confirm asking rent'}} for row in rows]}

    monkeypatch.setattr(module, 'integrated_package', lambda: {'data_release': 'Example release', 'release_id': 'v1'})
    monkeypatch.setattr(module, 'rank_locations', rank)
    monkeypatch.setattr(module, 'decision_lab_dossier', dossier)
    grid = '/api/site-brief/decision-lab'
    detail = grid + '/dossier'
    with module.app.test_client() as client, patch('site_advisor._request') as inference:
        assert client.post(grid + '?borough=Queen', json={}).status_code == 400
        assert not calls
        response = client.post(grid + '?borough=Queens', json={'average_checks': [25, 45], 'dayparts': ['lunch', 'evening']})
        assert response.status_code == 200
        assert len(calls) == 9 and all(borough == 'Queens' for borough, *_ in calls)
        result = response.get_json()
        assert result['candidates'][0]['clear_count'] == 9
        assert result['dossiers']['sites'][0]['id'] == site_id
        request = {'id': site_id, 'snapshot_id': result['snapshot_id']}
        assert client.post(detail + '?borough=Queens', json=request).status_code == 200
        assert client.post(detail + '?borough=Brooklyn', json=request).status_code == 409
        assert client.post(detail + '?borough=Queens', json={**request, 'id': '36061000100'}).status_code == 404
        inference.assert_not_called()


def test_dashboard_access_snapshot_does_not_fill_ranks_with_missing_scores(monkeypatch):
    import app as module

    monkeypatch.setattr(module, 'integrated_package', lambda: {'data_release': 'Example release', 'release_id': 'v1'})
    monkeypatch.setattr(module, 'rank_locations', lambda *args, **kwargs: (
        [{'id': 'scored', 'inverse_walkability': 75}, {'id': 'unscored', 'inverse_walkability': None}],
        {'ranking_mode': 'screening'}, {'status': 'available'}))
    with module.app.test_request_context('/?sort_by=inverse_walkability'):
        result = module._dashboard(module.request.args, advisor_snapshot=True).get_json()
    assert [row['id'] for row in result['locations']] == ['scored']


def test_advisor_chat_keeps_conversation_scope_and_checks_signed_context(monkeypatch):
    import app as module

    geoid = '36081000100'
    calls = []

    def rank(inputs, package, **kwargs):
        calls.append((inputs.borough, inputs.concept.cuisine, inputs.concept.average_check))
        return ([{'id': geoid, 'name': 'Elmhurst Tract 1', 'opportunity': 80}],
                {'ranking_mode': 'screening'}, {'status': 'not_assessed'})

    def dossier(inputs, package, rows, survival, access, **kwargs):
        return {'sites': [{**row, 'evidence': [], 'next_check': {'label': 'Confirm asking rent'}} for row in rows]}

    package = {'data_release': 'Fixture', 'release_id': 'v1', 'tracts': [
        {'geoid': geoid, 'borough': 'Queens', 'nta_name': 'Elmhurst', 'tract_label': '1'},
    ]}
    monkeypatch.setattr(module, 'integrated_package', lambda: package)
    monkeypatch.setattr(module, 'rank_locations', rank)
    monkeypatch.setattr(module, 'decision_lab_dossier', dossier)
    url = '/api/site-brief/chat'
    with module.app.test_client() as client, patch('site_advisor._request') as inference:
        first = client.post(url, json={'message': 'Where should I look for an Italian restaurant in Queens?'}).get_json()
        assert first['cards'][0]['id'] == geoid
        assert first['scope'].startswith('Queens · Italian')
        variant = client.post(url, json={'message': 'What if I charge $45 per guest?', 'context': first['context']})
        assert variant.status_code == 200
        second = variant.get_json()
        assert '$45 per guest' in second['scope']
        assert calls == [('Queens', 'italian', 35), ('Queens', 'italian', 45), ('Queens', 'italian', 35)]
        third = client.post(url, json={'message': 'Why the first one?', 'context': second['context']}).get_json()
        assert third['cards'][0]['id'] == geoid
        assert 'Elmhurst' in third['answer']
        assert client.post(url + '?borough=Brooklyn', json={'message': 'Why?', 'context': second['context']}).status_code == 409
        assert client.post(url, json={'message': 'Why?', 'context': 'invalid.signature'}).status_code == 409
        assert client.post(url, json={'message': 'x' * 501}).status_code == 400
        inference.assert_not_called()


def test_explains_entrant_from_beyond_dashboard_display_cutoff(dashboard):
    from copy import deepcopy
    from site_advisor import compare_rankings

    dashboard['scoring'] = {'ranking_mode': 'screening'}
    far = {'id': 'far', 'name': 'Far', 'opportunity': 60, 'score_components': [
        {'key': 'fit', 'label': 'Customer fit', 'score': 20, 'coverage': 100},
        {'key': 'rent', 'label': 'Rent', 'score': 50, 'coverage': 0},
    ]}
    dashboard['locations'].extend({'id': str(i), 'name': str(i), 'opportunity': 65} for i in range(25))
    dashboard['locations'].append(far)
    after = deepcopy(dashboard)
    entrant = after['locations'].pop()
    entrant['opportunity'] = 82
    entrant['score_components'][0].update(score=55, coverage=80)
    entrant['score_components'][1].update(score=95, coverage=100)
    after['locations'].insert(0, entrant)
    result = compare_rankings(dashboard, after)
    entry = next(row for row in result['explanations'] if row['id'] == 'far')
    assert (entry['before_rank'], entry['after_rank'], entry['score_delta']) == (30, 1, 22)
    assert entry['factors'] == [{'key': 'fit', 'label': 'Customer fit', 'delta': 35,
                                 'before': 20, 'after': 55, 'coverage_changed': True}]
    unchanged_score = next(row for row in result['explanations'] if row['id'] == '36081000000')
    assert 'score stayed the same' in unchanged_score['note']


def test_does_not_borrow_screening_factors_for_customer_access(dashboard):
    from copy import deepcopy
    from site_advisor import compare_rankings

    dashboard['scoring'] = {'ranking_mode': 'screening'}
    dashboard['meta']['sort_by'] = 'inverse_walkability'
    site = dashboard['locations'][0]
    site['inverse_walkability'] = 40
    site['score_components'] = [{'key': 'fit', 'label': 'Fit', 'score': 20, 'coverage': 100}]
    after = deepcopy(dashboard)
    after['locations'][0]['inverse_walkability'] = 60
    after['locations'][0]['score_components'][0]['score'] = 90
    change = compare_rankings(dashboard, after)['explanations'][0]
    assert change['score_delta'] == 20
    assert not change['factors']
    assert 'not available' in change['note']


def test_evidence_warns_about_missing_and_synthetic_data(dashboard):
    dashboard['locations'][0]['assessment_policy'] = {'recommendation_eligible': False,
                                                      'cuisine_mode': 'general_concept_suitability'}
    dashboard['feeds'] = [{'name': 'ACS demographics', 'vintage': '2024', 'url': 'https://www.census.gov/'},
                          {'name': 'Invalid', 'url': 'javascript:alert(1)'}]
    result = build_evidence(dashboard)
    site = result['sites'][0]
    facts = {f['id']: f for f in site['facts']}
    assert facts['score']['value'] is None
    assert facts['population']['source']['vintage'] == '2024'
    assert result['sources'][1]['url'] is None
    assert 'Reported median monthly rent' in site['gaps']
    assert any('Synthetic properties' in note for note in site['cautions'])
    assert any('evidence threshold' in note for note in site['cautions'])
    assert site['checks']


def test_http_brief_is_keyless_no_model_by_default_and_polish_refuses_stale_evidence(dashboard):
    from app import app
    from site_advisor import site_brief as actual_brief

    def render(evidence, *, wording):
        def inference(options):
            return {k: v[-1] for k, v in options.items()}, {}
        return actual_brief(evidence, inference, wording=wording)

    with app.test_client() as client, patch('app.dashboard', side_effect=lambda: jsonify(dashboard)), \
            patch('app.site_brief', side_effect=render) as render_brief:
        initial = client.post('/api/site-brief', json={}).get_json()
        assert initial['mode'] == 'template'
        assert render_brief.call_args.kwargs == {'wording': False}
        token = initial['evidence_version']
        updated = client.post('/api/site-brief', json={'wording': True, 'evidence_version': token}).get_json()
        assert updated['mode'] == 'local_model'
        assert updated['sites'] == initial['sites']
        assert updated['summary'] != initial['summary']
        assert updated['evidence_version'] == token
        dashboard['locations'][0]['market_profile']['population'] = 1500
        stale = client.post('/api/site-brief', json={'wording': True, 'evidence_version': token})
        assert stale.status_code == 409
        assert render_brief.call_count == 2


def test_missing_release_has_a_clear_error():
    from app import app

    with app.test_client() as client, patch('app.dashboard', side_effect=FileNotFoundError):
        response = client.post('/api/site-brief', json={})
    assert response.status_code == 503
    assert 'published sample' in response.get_json()['error']
