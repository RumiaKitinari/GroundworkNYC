"""Consumer dashboard response and backward-compatible saved-brief contracts."""
from app import app, valid_workspace


def test_dashboard_exposes_top_35_without_truncating_comparison_population():
    with app.test_client() as client:
        response = client.get('/api/dashboard?borough=Queens&concept_name=Canal%20Noodle%20House&cuisine=japanese')
    assert response.status_code == 200
    data = response.json
    assert len(data['locations']) == min(35, data['comparison']['eligible_count'])
    assert data['comparison']['count'] > len(data['locations'])
    assert data['comparison']['geography'] == 'Queens'
    assert data['meta']['concept_name'] == 'Canal Noodle House'
    assert all(row['borough'] == 'Queens' for row in data['locations'])
    assert len({row['id'] for row in data['locations']}) == len(data['locations'])


def test_workspace_keeps_legacy_briefs_and_explicit_other_choice():
    for brief in [{'conceptName': 'Modern Bistro'},
                  {'conceptName': 'Bistro', 'ideaChoice': 'other', 'profile': 'coffee'}]:
        assert valid_workspace({'active_brief': brief, 'briefs': [brief], 'shortlists': {}, 'menus': {}})
