"""Replay the published screening selections to evaluate the scenario comparison."""
import argparse
import csv
import json
from collections import defaultdict

from site_advisor import compare_rankings


def evaluate(path):
    groups = defaultdict(list)
    with open(path, newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row['method'] == 'screening':
                groups[row['cuisine_key'], float(row['average_check'])].append(row)
    cuisines = sorted({cuisine for cuisine, _ in groups})
    outcomes = []
    for cuisine in cuisines:
        for low, high in ((18, 35), (35, 65)):
            snapshots = []
            for price in (low, high):
                rows = sorted(groups[cuisine, price], key=lambda row: int(row['rank']))
                if len(rows) < 3:
                    raise ValueError(f'Missing top-three records for {cuisine} at ${price}.')
                snapshots.append({'locations': [{'id': row['property_id'], 'name': row['neighborhood'],
                                                 'opportunity': float(row['selected_score'])} for row in rows],
                                  'meta': {'data_release': '2026-11-02 offline scenarios'}})
            result = compare_rankings(*snapshots)
            expected = [[row['id'] for row in snapshot['locations'][:3]] for snapshot in snapshots]
            first, second = (set(ids) for ids in expected)
            actual = [[row['id'] for row in result[side]] for side in ('before', 'after')]
            valid = (actual == expected and {row['id'] for row in result['entered']} == second - first and
                     {row['id'] for row in result['left']} == first - second and
                     {row['id']: (row['previous_rank'], row['current_rank']) for row in result['retained']}
                     == {i: (expected[0].index(i) + 1, expected[1].index(i) + 1) for i in first & second})
            outcomes.append({'valid': valid, 'membership_changed': first != second, 'order_changed': expected[0] != expected[1]})
    return {'source': 'Published 2026-11-02 synthetic property screening selections; no new scoring or observed outcomes',
            'cuisines': len(cuisines), 'comparisons': len(outcomes),
            'passed': sum(row['valid'] for row in outcomes),
            'membership_changed': sum(row['membership_changed'] for row in outcomes),
            'order_changed_including_membership': sum(row['order_changed'] for row in outcomes),
            'model_requests': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export')
    result = evaluate(parser.parse_args().export)
    print(json.dumps(result, indent=2))
    if not result['comparisons'] or result['passed'] != result['comparisons']:
        raise SystemExit(1)
