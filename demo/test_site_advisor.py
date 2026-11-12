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
        saved = client.post(url + '?saved_id=' + geoid, json={'message': 'Why the first one?', 'context': second['context']})
        assert saved.status_code == 200 and saved.get_json()['cards'][0]['id'] == geoid
        clarification = client.post(url, json={'message': 'Where should I look for an Italian or Thai dinner spot in Queens?'}).get_json()
        resolved = client.post(url, json={'message': 'Italian', 'context': clarification['context']}).get_json()
        assert resolved['scope'].startswith('Queens · Italian')
        assert '$35 per guest, evening' in resolved['scope']
        clarification = client.post(url, json={'message': 'Where should I look for an Italian restaurant in Queens with $90?'}).get_json()
        resolved = client.post(url, json={'message': '$45 per guest', 'context': clarification['context']}).get_json()
        assert resolved['scope'].startswith('Queens · Italian') and '$45 per guest' in resolved['scope']
        inference.assert_not_called()


def test_sample_is_packaged_with_the_dashboard_without_research_exports(tmp_path, monkeypatch):
    from pathlib import Path
    import app as module

    target = tmp_path / 'demo/examples/site_advisor_sample.csv'
    target.parent.mkdir(parents=True)
    target.write_bytes((Path(module.__file__).parent / 'examples/site_advisor_sample.csv').read_bytes())
    monkeypatch.setattr(module, 'PROJECT_ROOT', tmp_path)
    with module.app.test_client() as client, patch('site_advisor._request') as inference:
        assert client.post('/api/site-brief/sample', json={}).status_code == 200
        for amount in [18, 65]:
            response = client.post('/api/site-brief/sample/scenario', json={'average_check': amount})
            assert response.status_code == 200
            assert len(response.get_json()['after']) == 3
        inference.assert_not_called()


@pytest.fixture
def neighborhood_chat(monkeypatch):
    import app as module

    tracts = [
        ('36081000001', 'Astoria (Central)', 75, 60),
        ('36081000002', 'Astoria (North)', 55, 40),
        ('36081000003', 'Long Island City-Hunters Point', 70, None),
        ('36081000004', 'Long Island City-Hunters Point', 50, None),
        ('36081000005', 'Elmhurst', 99, 90),
    ]
    package = {'data_release': 'Fixture', 'release_id': 'v1', 'tracts': [
        {'geoid': identity, 'borough': 'Queens', 'nta_name': name, 'tract_label': index}
        for index, (identity, name, _, _) in enumerate(tracts, 1)
    ]}

    def rank(inputs, package, **kwargs):
        rows = [{'id': identity, 'name': f'{name} Tract {index}', 'opportunity': score, 'inverse_walkability': access}
                for index, (identity, name, score, access) in enumerate(tracts, 1)]
        rows.sort(key=lambda row: row[inputs.sort_by] if row[inputs.sort_by] is not None else -1, reverse=True)
        return rows, {'ranking_mode': 'screening'}, {'status': 'available'}

    def dossier(inputs, package, rows, survival, access, **kwargs):
        return {'sites': [{**row, 'evidence': []} for row in rows]}

    monkeypatch.setattr(module, 'integrated_package', lambda: package)
    monkeypatch.setattr(module, 'rank_locations', rank)
    monkeypatch.setattr(module, 'decision_lab_dossier', dossier)
    with module.app.test_client() as client, patch('site_advisor._request') as inference:
        def ask(message, context=None, *, sort='opportunity'):
            response = client.post(f'/api/site-brief/chat?borough=Queens&sort_by={sort}',
                                   json={'message': message, 'context': context})
            assert response.status_code == 200
            return response.get_json()

        yield ask
        inference.assert_not_called()


def test_neighborhood_comparison_remembers_its_shortlist(neighborhood_chat):
    compare = neighborhood_chat('Compare Astoria and Long Island City.')
    groups = compare['area_comparison']['groups']
    assert [(group['scored_count'], group['median_score']) for group in groups] == [(2, 65), (2, 60)]
    assert [card['id'] for card in compare['cards']] == ['36081000001', '36081000003']
    first = neighborhood_chat('Why the first one?', compare['context'])
    second = neighborhood_chat('Why the second one?', first['context'])
    assert second['cards'][0]['id'] == compare['cards'][1]['id']
    assert '36081000003' in second['cards'][0]['actions'][0]['prompt']


def test_neighborhood_what_if_retains_scope_and_comparison_preserves_missing_scores(neighborhood_chat):
    first = neighborhood_chat('Where should I look in Astoria?')
    revised = neighborhood_chat('What if I switch to lunch?', first['context'])
    assert revised['scope'].startswith('Astoria · Queens')
    assert [card['id'] for card in revised['cards']] == ['36081000001', '36081000002']
    broadened = neighborhood_chat('Where should I look in Queens?', revised['context'])
    assert broadened['cards'][0]['id'] == '36081000005'
    access = neighborhood_chat('Compare Astoria and Long Island City.', sort='inverse_walkability')
    assert access['area_comparison']['groups'][1]['scored_count'] == 0
    assert access['area_comparison']['groups'][1]['median_score'] is None
    assert len(access['cards']) == 1
    assert 'Long Island City had no scored tracts' in access['answer']


def test_neighborhood_scenario_keeps_both_groups_and_undo_restores_them(neighborhood_chat):
    comparison = neighborhood_chat('Compare Astoria and Long Island City.')
    preview = neighborhood_chat('What if I charge $50 per guest?', comparison['context'])
    assert preview['preview'] is True
    groups = preview['scenario']['groups']
    assert [group['label'] for group in groups] == ['Astoria', 'Long Island City']
    assert [(group['before']['median_score'], group['after']['median_score']) for group in groups] == [(65, 65), (60, 60)]
    assert [card['id'] for card in preview['cards']] == [card['id'] for card in comparison['cards']]
    assert 'Astoria: median score 65 → 65' in preview['answer']
    discarded = neighborhood_chat('Discard this preview.', preview['context'])
    assert not discarded['preview'] and '$35 per guest' in discarded['scope']
    assert discarded['scope'].startswith('Astoria + Long Island City')
    assert [card['id'] for card in discarded['cards']] == [card['id'] for card in comparison['cards']]


@pytest.fixture
def scenario_chat(monkeypatch):
    import app as module

    ids = [f'3608100000{index}' for index in range(1, 5)]
    package = {'data_release': 'Fixture', 'release_id': 'v1', 'tracts': [
        {'geoid': identity, 'borough': 'Queens', 'nta_name': 'Elmhurst', 'tract_label': index}
        for index, identity in enumerate(ids, 1)
    ]}
    calls = []

    def rank(inputs, package, **kwargs):
        check = inputs.concept.average_check
        calls.append((check, inputs.concept.daypart, inputs.borough, inputs.rent_cap))
        scores = [90, 80, 70, 60] if check == 35 else [90, 80, 70, 75] if check < 60 else [90, 80, 80, 80]
        rows = [{'id': identity, 'name': f'Elmhurst Tract {index}', 'opportunity': score,
                 'inverse_walkability': 90 - index if index <= 2 else None,
                 'score_components': [{'key': 'fit', 'label': 'Customer fit', 'score': check, 'coverage': 100},
                                      {'key': 'rent', 'label': 'Rent', 'score': check, 'coverage': 0}]}
                for index, (identity, score) in enumerate(zip(ids, scores), 1)]
        rows.sort(key=lambda row: row[inputs.sort_by] if row[inputs.sort_by] is not None else -1, reverse=True)
        return rows, {'ranking_mode': 'screening'}, {'status': 'available'}

    monkeypatch.setattr(module, 'integrated_package', lambda: package)
    monkeypatch.setattr(module, 'rank_locations', rank)
    monkeypatch.setattr(module, 'decision_lab_dossier', lambda inputs, package, rows, *args, **kwargs:
                        {'sites': [{**row, 'evidence': []} for row in rows]})
    with module.app.test_client() as client, patch('site_advisor._request') as inference:
        def ask(message, context=None, *, query=''):
            response = client.post('/api/site-brief/chat' + query, json={'message': message, 'context': context})
            assert response.status_code == 200, response.get_json()
            return response.get_json()
        yield ask, calls, package
        inference.assert_not_called()


def test_exact_tract_scenario_reports_own_score_rank_and_supported_factors(scenario_chat):
    ask, _, _ = scenario_chat
    preview = ask('What if I charge $50 per guest for tract 36081000004?')
    assert len(preview['cards']) == 1
    target, = preview['scenario']['targets']
    assert target['id'] == '36081000004' and target['score_delta'] == 15
    assert (target['before']['rank_min'], target['after']['rank_min']) == (4, 3)
    assert target['factors'] == [{'key': 'fit', 'label': 'Customer fit', 'before': 35, 'after': 50,
                                  'delta': 15, 'coverage_changed': False}]
    assert 'Elmhurst Tract 4: score 60 → 75; rank 4 → rank 3.' in preview['answer']
    assert 'joins the set' not in preview['answer']
    followup = ask('Why the first one?', preview['context'])
    assert followup['preview'] and '$50 per guest' in followup['scope']
    tied = ask('What if I charge $60 per guest there?', followup['context'])
    target, = tied['scenario']['targets']
    assert (target['after']['rank_min'], target['after']['rank_max']) == (2, 4)
    assert tied['scenario']['before_label'] == '$35 per guest, all day'
    assert 'tied ranks 2–4' in tied['answer']


def test_preview_apply_and_undo_are_separate_from_followup_questions(scenario_chat):
    ask, calls, _ = scenario_chat
    baseline = ask('Where should I look in Queens?')
    preview = ask('What if I charge $50 per guest?', baseline['context'])
    assert [action['label'] for action in preview['actions'][:2]] == ['Apply scenario', 'Discard preview']
    applied = ask('Apply this scenario.', preview['context'])
    assert not applied['preview'] and '$50 per guest' in applied['scope']
    assert applied['answer'].startswith('Scenario applied')
    assert applied['actions'][0]['label'] == 'Undo applied scenario'
    explained = ask('Why the first one?', applied['context'])
    assert calls[-1][:2] == (50, 'all_day')
    undone = ask('Undo the applied scenario.', explained['context'])
    assert not undone['preview'] and '$35 per guest' in undone['scope']
    assert [card['id'] for card in undone['cards']] == [card['id'] for card in baseline['cards']]
    assert calls[-1][:2] == (35, 'all_day')
    count = len(calls)
    repeated = ask('Undo', undone['context'])
    assert 'no applied scenario' in repeated['answer'] and len(calls) == count


def test_repeated_preview_discard_clarification_and_new_search_use_applied_baseline(scenario_chat):
    ask, calls, _ = scenario_chat
    first = ask('Where should I look for an Italian restaurant in Queens?')
    preview = ask('What if I charge $50 per guest?', first['context'])
    clarified = ask('Where should I look for Italian or Thai?', preview['context'])
    assert clarified['preview'] and clarified['actions'][0]['label'] == 'Apply scenario'
    lunch = ask('What if I switch to lunch?', clarified['context'])
    assert '$50 per guest, lunch' in lunch['scope']
    assert lunch['scenario']['before_label'] == '$35 per guest, all day'
    discarded = ask('Undo', lunch['context'])
    assert not discarded['preview'] and '$35 per guest, all day' in discarded['scope']
    assert discarded['scope'].startswith('Queens · Italian')
    preview = ask('What if I charge $60 per guest?', discarded['context'])
    new_search = ask('Where should I look in Brooklyn?', preview['context'])
    assert not new_search['preview'] and '$35 per guest' in new_search['scope']
    assert calls[-1][:3] == (35, 'all_day', 'Brooklyn')


def test_rent_hypothetical_does_not_persist_paired_guest_spend(scenario_chat):
    ask, calls, _ = scenario_chat
    first = ask('Where should I look in Queens?')
    rent = ask('What if rent is $9,000 and I charge $50 per guest?', first['context'])
    assert 'only to this rent calculation' in rent['answer']
    assert '$50 per guest' in rent['scope']
    followup = ask('Why the first one?', rent['context'])
    assert '$35 per guest' in followup['scope'] and not followup['preview']
    assert calls[-1][0] == 35


def test_discarding_second_preview_preserves_undo_and_original_shortlist_positions(scenario_chat):
    ask, _, _ = scenario_chat
    baseline = ask('Where should I look in Queens?')
    why = ask('Why the first one?', baseline['context'])
    preview = ask('What if I charge $50 per guest?', why['context'])
    discarded = ask('Discard preview', preview['context'])
    second = ask('Why the second one?', discarded['context'])
    assert second['cards'][0]['id'] == baseline['cards'][1]['id']
    preview = ask('What if I charge $50 per guest?', baseline['context'])
    applied = ask('Apply scenario', preview['context'])
    next_preview = ask('What if I charge $60 per guest?', applied['context'])
    assert next_preview['scenario']['before_label'] == '$50 per guest, all day'
    discarded = ask('Discard preview', next_preview['context'])
    assert '$50 per guest' in discarded['scope']
    assert discarded['actions'][0]['label'] == 'Undo applied scenario'
    undone = ask('Undo applied scenario', discarded['context'])
    assert '$35 per guest' in undone['scope']


def test_temporary_rent_calculation_cannot_apply_an_earlier_unrelated_preview(scenario_chat):
    ask, _, _ = scenario_chat
    preview = ask('What if I charge $45 per guest?')
    rent = ask('What if rent is $9,000 and I charge $60 per guest?', preview['context'])
    assert rent['temporary_calculation'] and not rent['preview']
    assert not any(action['label'] == 'Apply scenario' for action in rent['actions'])
    blocked = ask('Apply this scenario.', rent['context'])
    assert 'temporary calculations' in blocked['answer']
    followup = ask('Why the first one?', blocked['context'])
    assert followup['preview'] and '$45 per guest' in followup['scope']
    applied = ask('Apply this scenario.', followup['context'])
    assert not applied['preview'] and '$45 per guest' in applied['scope']


def test_missing_target_scores_are_not_invented_and_stale_preview_cannot_apply(scenario_chat):
    ask, _, package = scenario_chat
    missing = ask('What if I charge $50 per guest for tract 36081000004?', query='?sort_by=inverse_walkability')
    target, = missing['scenario']['targets']
    assert target['before']['status'] == target['after']['status'] == 'missing_score'
    assert target['score_delta'] is None and not target['factors']
    assert 'lacks a comparable score' in missing['answer']
    import app as module
    package['release_id'] = 'v2'
    with module.app.test_client() as client:
        stale = client.post('/api/site-brief/chat?sort_by=inverse_walkability',
                            json={'message': 'Apply this scenario.', 'context': missing['context']})
        assert stale.status_code == 409


def test_unavailable_scenario_controls_do_not_change_settings_or_rank(scenario_chat):
    ask, calls, _ = scenario_chat
    for question in ['Apply this scenario.', 'Discard this preview.', 'Undo']:
        response = ask(question)
        assert not response['preview'] and not response['cards']
        assert 'There is no' in response['answer']
    assert calls == []


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
