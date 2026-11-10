"""Measure local wording inference against real, server-generated dashboard evidence."""
import argparse
import csv
import json
import time

from site_advisor import MODEL, build_evidence, loaded_models, local_summary, wording_choices


def benchmark(query, export=None):
    started = time.perf_counter()
    if export:
        with open(export, newline='', encoding='utf-8') as stream:
            rows = [row for row in csv.DictReader(stream) if row['method'] == 'screening'
                    and row['cuisine_key'] == query['cuisine'] and float(row['average_check']) == 35]
        rows.sort(key=lambda row: int(row['rank']))
        result = {'locations': [{'id': row['property_id'], 'name': row['neighborhood'] + ' scenario',
                                 'opportunity': float(row['screening_score'])} for row in rows[:3]],
                  'meta': {'data_release': '2026-11-02 offline synthetic scenarios',
                           'assessment_type': 'Uncalibrated screening score'}}
    else:
        from app import app
        with app.test_client() as client:
            response = client.get('/api/dashboard', query_string=query)
        if response.status_code != 200:
            raise RuntimeError(f'Dashboard returned HTTP {response.status_code}.')
        result = response.get_json()
    dashboard_seconds = round(time.perf_counter() - started, 3)
    evidence = build_evidence(result)
    options = wording_choices(evidence)
    if not options:
        raise RuntimeError('The configured dashboard dataset returned no eligible locations.')
    initial = loaded_models()
    if any(row.get('name', row.get('model')) != MODEL for row in initial):
        raise RuntimeError('Another Ollama model is loaded; benchmark skipped without interrupting it.')
    trials = []
    for trial in range(4):
        started = time.perf_counter()
        reply, timing = local_summary(options, keep_alive='30s', timeout=60)
        wall = time.perf_counter() - started
        valid = isinstance(reply, dict) and set(reply) == set(options) and all(reply[k] in v for k, v in options.items())
        trials.append({'trial': trial + 1, 'initially_loaded': bool(initial) if trial == 0 else True,
                       'wall_seconds': round(wall, 3), 'load_seconds': round(timing.get('load_duration', 0) / 1e9, 3),
                       'generated_tokens': timing.get('eval_count'), 'valid': valid})
    print(json.dumps({'model': MODEL, 'release': evidence['release'], 'locations': len(options),
                      'evidence_seconds': dashboard_seconds, 'trials': trials,
                      'loaded': [{k: row.get(k) for k in ('name', 'size', 'size_vram', 'context_length')} for row in loaded_models()]}, indent=2))
    if not all(trial['valid'] for trial in trials):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--borough', default='Queens')
    parser.add_argument('--offline-export', help='Use checked-in top_selections.csv instead of the dashboard.')
    args = parser.parse_args()
    benchmark({'borough': args.borough, 'cuisine': 'italian', 'average_check': '35'}, args.offline_export)
