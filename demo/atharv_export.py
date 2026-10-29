"""Read Atharv's documented tract_survival_scores.csv without retraining.

Contract: ADM6112-complete-v1/40e0c0d, codes/train_survival.py.
These are archive-based research estimates, not verified closure predictions.
"""
import csv
import hashlib
import math
from functools import lru_cache
from pathlib import Path


class TractExport:
    def __init__(self, path):
        self.path = Path(path)
        content = self.path.read_bytes()
        self.model_id = 'atharv-tract-' + hashlib.sha256(content).hexdigest()[:12]
        self.predictions = {}
        with self.path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            required = {'geoid', 'borough', 'nta_code', 'survival_3yr', 'survival_3yr_rank_in_borough'}
            if not required <= set(reader.fieldnames or []):
                raise ValueError('Atharv tract export requires: ' + ', '.join(sorted(required)))
            for row in reader:
                geoid = row['geoid'].strip()
                probability = float(row['survival_3yr'])
                rank = float(row['survival_3yr_rank_in_borough'])
                if (len(geoid) != 11 or not geoid.isdigit() or geoid in self.predictions
                        or not math.isfinite(probability) or not 0 <= probability <= 1
                        or not math.isfinite(rank) or not 0 <= rank <= 1):
                    raise ValueError('Invalid or duplicate GEOID/probability in Atharv tract export')
                self.predictions[geoid] = {
                    'status': 'available', 'probability': probability, 'horizon_years': 3,
                    'model_version': self.model_id, 'assessment_type': 'Archive-based research estimate',
                    'source_type': 'atharv_tract_export', 'borough': row['borough'],
                    'borough_percentile': rank, 'feature_coverage': None,
                    'limitations': 'Archive disappearance is a closure proxy; current-context features and reference opening year apply.',
                }
        if not self.predictions:
            raise ValueError('Atharv tract export is empty')

    def predict(self, rows):
        # Preserve tract identity; never infer GEOIDs by row order or nearest point.
        return {str(row['geoid']): self.predictions[str(row['geoid'])]
                for row in rows if str(row['geoid']) in self.predictions}


@lru_cache(maxsize=2)
def load_export(path, signature):
    return TractExport(path)


def export_state(path):
    path = Path(path).expanduser().resolve()
    signature = (path.stat().st_mtime_ns, path.stat().st_size)
    engine = load_export(str(path), signature)
    return engine, {
        'status': 'available', 'label': 'Atharv tract model export connected',
        'model_version': engine.model_id, 'horizon_years': 3, 'ranking_mode': 'screening',
        'assessment_type': 'Archive-based research estimate',
        'source_type': 'atharv_tract_export', 'tract_count': len(engine.predictions),
        'limitations': ['Archive disappearance is a closure proxy, not verified permanent closure.',
                       'Current-context covariates and reference opening year limit interpretation.',
                       'Screening ranking is separate from this exported estimate.'],
    }
