"""Audit downloaded TIGGE surface GRIB messages without changing source data."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release

PARAMETERS = {'2t': ('K', 'instant'), 'tcc': ('%', 'instant'), '10u': ('m s**-1', 'instant'), '10v': ('m s**-1', 'instant'), 'ssr': ('J m**-2', 'accum')}
LEADS = (12, 18, 24, 30)


def expected_fields(start, end):
    if end < start:
        raise ValueError('End date must not precede start date')
    return {(start + timedelta(days=i), lead, name) for i in range((end-start).days+1) for lead in LEADS for name in PARAMETERS}


def summarize_values(name, arrays):
    values = np.concatenate(arrays)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError(f'No finite values for {name}')
    report = {'count': int(values.size), 'nonfinite': int(values.size-finite.size),
              'min': float(np.min(finite)), 'p01': float(np.percentile(finite, 1)),
              'median': float(np.median(finite)), 'p99': float(np.percentile(finite, 99)), 'max': float(np.max(finite))}
    if name == 'tcc':
        report.update(below_zero=int(np.sum(finite < 0)), above_100=int(np.sum(finite > 100)),
                      materially_outside=int(np.sum((finite < -0.01) | (finite > 100.01))))
    if name == 'ssr': report['negative_accumulations'] = int(np.sum(finite < 0))
    return report


def audit(paths, start, end):
    expected = expected_fields(start, end); observed = Counter(); values = defaultdict(list)
    issues = Counter(); grid = None; solar = {}; solar_count = 0; solar_decreases = 0; solar_most_negative = 0.
    for path in paths:
        with path.open('rb') as stream:
            while message := codes_grib_new_from_file(stream):
                try:
                    name = codes_get(message, 'shortName'); raw_date = str(codes_get(message, 'dataDate'))
                    day = datetime.strptime(raw_date, '%Y%m%d').date(); lead = int(codes_get(message, 'endStep'))
                    observed[(day, lead, name)] += 1
                    if name not in PARAMETERS:
                        issues['unexpected_parameter'] += 1; continue
                    if codes_get(message, 'units') != PARAMETERS[name][0]: issues['unexpected_units'] += 1
                    if codes_get(message, 'stepType') != PARAMETERS[name][1]: issues['unexpected_step_type'] += 1
                    if codes_get(message, 'dataTime') != 1200: issues['unexpected_initialization_time'] += 1
                    valid = datetime.strptime(str(codes_get(message, 'validityDate')) + f"{codes_get(message, 'validityTime'):04d}", '%Y%m%d%H%M')
                    if valid != datetime.combine(day, time(12)) + timedelta(hours=lead): issues['invalid_valid_time'] += 1
                    if name == 'ssr' and int(codes_get(message, 'startStep')) != 0: issues['unexpected_solar_start_step'] += 1
                    coordinates = np.column_stack((codes_get_array(message, 'latitudes'), (codes_get_array(message, 'longitudes') + 180) % 360 - 180))
                    if grid is None: grid = coordinates
                    elif not np.array_equal(grid, coordinates): issues['inconsistent_grid'] += 1
                    array = codes_get_array(message, 'values'); missing = int(codes_get(message, 'numberOfMissing'))
                    issues['encoded_missing_values'] += missing
                    if missing:
                        missing_value = codes_get(message, 'missingValue'); array = np.where(array == missing_value, np.nan, array)
                    values[name].append(array.astype(np.float32))
                    if name == 'ssr': solar[(day, lead)] = array
                finally:
                    codes_release(message)
    for day in sorted({d for d, _, n in observed if n == 'ssr'}):
        for before, after in zip(LEADS, LEADS[1:]):
            if (day, before) in solar and (day, after) in solar:
                diff = solar[day, after] - solar[day, before]; finite = diff[np.isfinite(diff)]
                solar_count += int(finite.size); solar_decreases += int(np.sum(finite < 0))
                if finite.size: solar_most_negative = min(solar_most_negative, float(np.min(finite)))
    extra = set(observed)-expected; absent = expected-set(observed)
    return {'start_initialization_date': str(start), 'end_initialization_date': str(end), 'expected_messages': len(expected),
            'observed_messages': sum(observed.values()), 'missing_combinations': len(absent), 'unexpected_combinations': len(extra),
            'duplicate_messages': sum(max(0, n-1) for n in observed.values()), 'issues': dict(issues),
            'grid_points': int(len(grid)) if grid is not None else 0,
            'grid_extent': {'latitude_min': float(grid[:,0].min()), 'latitude_max': float(grid[:,0].max()), 'longitude_min': float(grid[:,1].min()), 'longitude_max': float(grid[:,1].max())} if grid is not None else None,
            'variables': {n: summarize_values(n, vals) for n, vals in values.items()},
            'solar_increment_checks': {'pairs_checked': solar_count, 'negative_increments': solar_decreases, 'most_negative_j_m2': solar_most_negative}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('files', type=Path, nargs='+'); p.add_argument('--start', type=date.fromisoformat, required=True); p.add_argument('--end', type=date.fromisoformat, required=True); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); result = audit(args.files, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result, indent=2)); print('Saved', args.output)


if __name__ == '__main__': main()
