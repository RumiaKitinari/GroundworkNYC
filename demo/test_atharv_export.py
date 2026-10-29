"""Validate the author's exported schema and GEOID join; no training in tests."""
import csv
import json

import pytest
from atharv_export import TractExport
from survival_inference import attach_predictions, model_state


def write_export(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['geoid', 'borough', 'nta_code', 'survival_3yr', 'survival_3yr_rank_in_borough'])
        writer.writerows(rows)


def test_export_joins_by_tract_and_retains_screening(tmp_path, monkeypatch):
    monkeypatch.delenv('GROUNDWORK_ATHARV_SCORES', raising=False)
    path = tmp_path / 'tract_survival_scores.csv'
    write_export(path, [['36061000200', 'Manhattan', 'MN01', .73, .8]])
    config = tmp_path / 'pointer.json'
    config.write_text(json.dumps({'tract_scores': str(path)}))
    rows = [{'geoid': '36061000100', 'opportunity': 80}, {'geoid': '36061000200', 'opportunity': 50}]
    state = attach_predictions(rows, config)
    assert state['status'] == 'available'
    assert state['source_type'] == 'atharv_tract_export'
    assert rows[0]['survival']['probability'] is None
    assert rows[1]['survival']['probability'] == .73
    assert [r['opportunity'] for r in rows] == [80, 50]


@pytest.mark.parametrize('geoid,probability', [('123', .5), ('36061000100', 1.1), ('36061000100', 'nan')])
def test_rejects_invalid_identity_or_probability(tmp_path, geoid, probability):
    path = tmp_path / 'bad.csv'
    write_export(path, [[geoid, 'Manhattan', 'MN01', probability, .5]])
    with pytest.raises(ValueError):
        TractExport(path)


def test_missing_explicit_export_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv('GROUNDWORK_ATHARV_SCORES', str(tmp_path / 'missing.csv'))
    assert model_state(tmp_path / 'no-config.json')[1]['status'] == 'invalid_artifact'
