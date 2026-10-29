"""Translate real dated package columns to Atharv 40e0c0d's input schema.

Writes a separate training input; never changes the active dashboard release.
Missing/suppressed values stay missing. Storefront counts use the published
statistics, not the property's vacant/nonvacant filing counts.
"""
import argparse
import hashlib
import json
from pathlib import Path


def prepare(directory, storefront_statistics, output):
    import pandas as pd
    directory, output = Path(directory), Path(output)
    source = directory / 'master_tract_features.csv'
    master = pd.read_csv(source, dtype={'geoid': str})
    aliases = {
        'pickups_latest_month': 'pickups_may_2026',
        'dropoffs_latest_month': 'dropoffs_may_2026',
    }
    for target, original in aliases.items():
        if target not in master:
            master[target] = master[original]
    area = pd.to_numeric(master['land_area_sq_miles'], errors='coerce')
    departures = pd.to_numeric(master['citibike_departures_august_2026'], errors='coerce')
    if 'citibike_departures_per_sq_mile_latest_month' not in master:
        master['citibike_departures_per_sq_mile_latest_month'] = departures / area.where(area > 0)
    for target, original in [
        ('citibike_evening_departure_share_latest_month', 'citibike_evening_departures_august_2026'),
        ('citibike_weekend_departure_share_latest_month', 'citibike_weekend_departures_august_2026'),
    ]:
        if target not in master:
            master[target] = pd.to_numeric(master[original], errors='coerce') / departures.where(departures > 0)
    stats = pd.read_csv(storefront_statistics, dtype=str)
    year = str(max(int(v) for v in stats.reporting_year.dropna()))
    stats = stats[(stats.reporting_year == year) & (stats.geography_id_valid.str.lower() == 'true')
                  & (stats.aggregate_level_citywide_borough_council_district_census_tract == 'Census Tract')]
    if stats.census_tract_geoid.duplicated().any():
        raise ValueError('Duplicate GEOID in latest storefront statistics')
    stats = stats.set_index('census_tract_geoid')
    for target, original in [('registered_storefronts', 'total_number_storefronts'),
                             ('leased_storefronts', 'number_storefront_leased_to_tenants')]:
        if target not in master:
            master[target] = pd.to_numeric(master.geoid.map(stats[original]), errors='coerce')
    if 'neighbor_geoids' not in master:
        from atharv_master_spec import enrich
        # The team spec computes dated ratios, shared-boundary neighbors and
        # supported neighbor-income estimates; it leaves unsupported data blank.
        master['citibike_departures_latest_month'] = master['citibike_departures_august_2026']
        master['citibike_evening_departures_latest_month'] = master['citibike_evening_departures_august_2026']
        master['citibike_weekend_departures_latest_month'] = master['citibike_weekend_departures_august_2026']
        rows = master.fillna('').to_dict('records')
        enrich(rows, directory / 'geography/nyc_2020_census_tracts.geojson')
        master = pd.DataFrame(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(output, index=False)
    report = {'master': str(source), 'master_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'storefront_source': str(storefront_statistics), 'storefront_reporting_year': year,
              'storefront_sha256': hashlib.sha256(Path(storefront_statistics).read_bytes()).hexdigest(),
              'taxi_vintage': '2026-05', 'citibike_vintage': '2026-08', 'tracts': len(master),
              'missing_storefront_counts': int(pd.to_numeric(master.registered_storefronts, errors='coerce').isna().sum()),
              'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix('.provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integrated-data', type=Path)
    parser.add_argument('--storefront-statistics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from app import integrated_directory
    print(json.dumps(prepare(args.integrated_data or integrated_directory(), args.storefront_statistics, args.output), indent=2))
