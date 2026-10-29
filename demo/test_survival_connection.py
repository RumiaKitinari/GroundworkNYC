"""Connection checks without training or substituting a test model into the app."""
from unittest.mock import patch

from app import app
from survival_inference import attach_predictions, model_state


def test_missing_bundle_is_explicit_and_preserves_screening(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"model_dir": "' + str(tmp_path / 'absent') + '"}')
    rows = [{"geoid": "36061000100", "opportunity": 72}]
    status = attach_predictions(rows, config)
    assert status['status'] == 'awaiting_artifact'
    assert rows[0]['survival']['probability'] is None
    assert rows[0]['opportunity'] == 72
    with patch.dict(app.config, SURVIVAL_CONFIG=str(config)):
        assert app.test_client().get('/api/models/survival').json['status'] == 'awaiting_artifact'


def test_predictions_join_by_geoid_instead_of_position():
    class Engine:
        def predict(self, rows):
            return {'36061000200': {'status': 'available', 'probability': .65}}
    rows = [{'geoid': '36061000100', 'opportunity': 80},
            {'geoid': '36061000200', 'opportunity': 60}]
    with patch('survival_inference.model_state', return_value=(Engine(), {'status': 'available'})):
        attach_predictions(rows)
    assert rows[0]['survival']['probability'] is None
    assert rows[1]['survival']['probability'] == .65
    assert [r['opportunity'] for r in rows] == [80, 60]


def test_invalid_config_remains_unavailable(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{broken')
    assert model_state(config)[1]['status'] == 'invalid_artifact'
