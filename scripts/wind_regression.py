"""Retrospective linear correction of TIGGE 10 m wind against ERA5."""
import argparse
import calendar
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release

LEADS = (12, 18, 24, 30)
START = date(2024, 1, 1)
END = date(2026, 11, 5)


def split(day):
    if START <= day <= date(2025, 6, 30): return 'train'
    if date(2025, 7, 1) <= day <= date(2025, 12, 31): return 'validation'
    if date(2026, 1, 1) <= day <= END: return 'test'
    return None


def read_fields(paths, forecast):
    fields = {}; grid = None
    for path in paths:
        with path.open('rb') as stream:
            while message := codes_grib_new_from_file(stream):
                try:
                    name = codes_get(message, 'shortName')
                    if name not in ('10u', '10v'): continue
                    init = datetime.strptime(str(codes_get(message, 'dataDate')) + f"{codes_get(message, 'dataTime'):04d}", '%Y%m%d%H%M')
                    valid = datetime.strptime(str(codes_get(message, 'validityDate')) + f"{codes_get(message, 'validityTime'):04d}", '%Y%m%d%H%M')
                    step = int(codes_get(message, 'endStep'))
                    if forecast and (init.hour != 12 or step not in LEADS or valid != init + timedelta(hours=step)): continue
                    if not split(valid.date()): continue
                    if codes_get(message, 'units') != 'm s**-1' or codes_get(message, 'stepType') != 'instant':
                        raise ValueError(f'Unexpected wind metadata in {path}')
                    coordinates = np.column_stack((codes_get_array(message, 'latitudes'), (codes_get_array(message, 'longitudes') + 180) % 360 - 180))
                    if grid is None: grid = coordinates
                    elif not np.array_equal(grid, coordinates): raise ValueError(f'Inconsistent grid in {path}')
                    values = codes_get_array(message, 'values').astype(np.float32)
                    if codes_get(message, 'numberOfMissing') or not np.isfinite(values).all(): raise ValueError(f'Missing wind values in {path}')
                    key = (valid, name)
                    if key in fields: raise ValueError(f'Duplicate field {key} in {path}')
                    fields[key] = values
                finally:
                    codes_release(message)
    if grid is None: raise ValueError('No wind fields found')
    return grid, fields


def match(forecast_grid, forecast, reference_grid, reference, mask_path, end=END):
    with mask_path.open(newline='') as f:
        region_map = {}
        for row in csv.DictReader(f):
            key = (round(float(row['latitude']), 4), round(float(row['longitude']), 4))
            if row['region'] not in ('onshore', 'offshore') or key in region_map:
                raise ValueError(f'Invalid or duplicate mask coordinate {key} with region {row["region"]!r}')
            region_map[key] = row['region']
    regions = np.array([region_map.get((round(float(a), 4), round(float(b), 4)), '') for a, b in forecast_grid])
    selected = np.flatnonzero(np.isin(regions, ['onshore', 'offshore']))
    if not len(selected) or set(regions[selected]) != {'onshore', 'offshore'}: raise ValueError('Mask must contain both onshore and offshore grid points')
    ref_indices = {(round(float(a), 4), round(float(b), 4)): i for i, (a, b) in enumerate(reference_grid)}
    if len(ref_indices) != len(reference_grid): raise ValueError('Duplicate rounded ERA5 coordinates')
    try: ix = np.array([ref_indices[(round(float(a), 4), round(float(b), 4))] for a, b in forecast_grid[selected]])
    except KeyError as exc: raise ValueError(f'ERA5 grid lacks forecast coordinate {exc}') from exc
    datasets = {k: [] for k in ('train', 'validation', 'test')}; missing = {k: [] for k in datasets}
    day = START
    while day <= end:
        part = split(day)
        for hour in (0, 6, 12, 18):
            valid = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
            keys = [(valid, '10u'), (valid, '10v')]
            absent = [f'{source}:{key[1]}' for source, data in [('forecast', forecast), ('era5', reference)] for key in keys if key not in data]
            if absent:
                missing[part].append({'valid_time': valid.isoformat() + 'Z', 'missing': absent}); continue
            lead = (valid - (datetime.combine(day - timedelta(days=1), datetime.min.time()) + timedelta(hours=12))).total_seconds() / 3600
            u, v = [forecast[key][selected] for key in keys]; ru, rv = [reference[key][ix] for key in keys]
            coords = forecast_grid[selected]; offshore = (regions[selected] == 'offshore').astype(float)
            n = len(selected); days_year = 366 if calendar.isleap(day.year) else 365
            phase = 2 * np.pi * ((day.timetuple().tm_yday - 1) / days_year)
            season = (day.month % 12) // 3
            base = np.column_stack((u, v, np.hypot(u, v), np.full(n, lead), coords, offshore))
            datasets[part].append((base, np.full(n, phase), np.full(n, season), np.column_stack((ru-u, rv-v)), np.column_stack((ru, rv)), offshore))
        day += timedelta(days=1)
    return datasets, missing, {name: int(np.sum(regions[selected] == name)) for name in ('onshore', 'offshore')}


def design(base, phase, season, encoding):
    if encoding == 'cyclic': extra = np.column_stack((np.sin(phase), np.cos(phase)))
    elif encoding == 'season': extra = np.column_stack([season == s for s in (1, 2, 3)]).astype(float)
    else: raise ValueError('Unknown season encoding')
    return np.column_stack((np.ones(len(base)), base, extra))


def scores(pred, ref, raw, offshore):
    result = {}
    for name, choose in [('all', np.ones(len(raw), dtype=bool)), ('onshore', offshore == 0), ('offshore', offshore == 1)]:
        if not choose.any(): raise ValueError(f'No cases for {name}')
        group = {}
        for label, value in [('raw', raw[choose]), ('corrected', pred[choose])]:
            truth = ref[choose]; diff = value - truth
            speed_err = np.hypot(value[:, 0], value[:, 1]) - np.hypot(truth[:, 0], truth[:, 1])
            group[label] = {'speed_mae': float(np.mean(np.abs(speed_err))), 'speed_rmse': float(np.sqrt(np.mean(speed_err**2))),
                'speed_bias': float(np.mean(speed_err)), 'u_mae': float(np.mean(np.abs(diff[:, 0]))), 'v_mae': float(np.mean(np.abs(diff[:, 1]))),
                'u_rmse': float(np.sqrt(np.mean(diff[:, 0]**2))), 'v_rmse': float(np.sqrt(np.mean(diff[:, 1]**2))),
                'u_bias': float(np.mean(diff[:, 0])), 'v_bias': float(np.mean(diff[:, 1]))}
            truth_speed = np.hypot(truth[:, 0], truth[:, 1])
            denominator = np.sum((truth_speed - np.mean(truth_speed)) ** 2)
            group[label]['speed_r2'] = float(1 - np.sum(speed_err ** 2) / denominator) if denominator > 0 else None
        group['cases'] = int(choose.sum()); result[name] = group
    return result


def run_model(datasets, include_test=True):
    parts = {k: tuple(np.concatenate(items) for items in zip(*v)) for k, v in datasets.items() if v}
    if not {'train', 'validation'}.issubset(parts): raise ValueError('Training and validation data are required')
    fitted = {}; validation = {}
    for enc in ('season', 'cyclic'):
        base, phase, season, target, _, _ = parts['train']
        coefficients = np.linalg.lstsq(design(base, phase, season, enc), target, rcond=None)[0]
        b, ph, se, _, ref, offshore = parts['validation']; raw = b[:, :2]
        pred = raw + design(b, ph, se, enc) @ coefficients
        fitted[enc] = coefficients
        validation[enc] = scores(pred, ref, raw, offshore)
    winner = min(('season', 'cyclic'), key=lambda x: validation[x]['all']['corrected']['speed_mae'])
    result = {'selected_season_encoding': winner, 'validation': validation, 'coefficients': fitted[winner].tolist()}
    b, ph, se, _, ref, offshore = parts['train']; raw = b[:, :2]
    result['train'] = scores(raw + design(b, ph, se, winner) @ fitted[winner], ref, raw, offshore)
    if include_test:
        if 'test' not in parts: raise ValueError('Test data are required')
        b, ph, se, _, ref, offshore = parts['test']; raw = b[:, :2]
        result['test'] = scores(raw + design(b, ph, se, winner) @ fitted[winner], ref, raw, offshore)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast', type=Path, nargs='+', required=True)
    parser.add_argument('--era5', type=Path, nargs='+', required=True)
    parser.add_argument('--grid', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provisional-mask', action='store_true', help='Explicitly acknowledge that the region mask is not verified as the UK maritime boundary')
    parser.add_argument('--validation-only', action='store_true', help='Do not score or select based on the 2026 test set')
    parser.add_argument('--provisional-test', action='store_true', help='Explicitly score 2026 using an unverified mask; results are provisional')
    args = parser.parse_args()
    if args.grid.name == 'uk-land-and-eez-0.5deg.csv' and not args.provisional_mask:
        parser.error('Existing UK mask is approximate; pass --provisional-mask for a provisional experiment')
    if args.provisional_mask and not args.validation_only and not args.provisional_test:
        parser.error('The final test requires a verified geographic mask; use --validation-only or explicitly request --provisional-test')
    if args.provisional_test and (not args.provisional_mask or args.validation_only):
        parser.error('--provisional-test requires --provisional-mask and cannot be combined with --validation-only')
    fg, forecast = read_fields(args.forecast, True); rg, reference = read_fields(args.era5, False)
    datasets, missing, points = match(fg, forecast, rg, reference, args.grid)
    result = run_model(datasets, include_test=not args.validation_only)
    result.update({'reference': 'ERA5; retrospective, recent ERA5T may be preliminary', 'mask': str(args.grid), 'provisional_mask': args.provisional_mask,
                   'forecast_files': [str(p) for p in args.forecast], 'era5_files': [str(p) for p in args.era5], 'grid_points': points,
                   'valid_time_coverage': {k: {'matched': len(datasets[k]), 'missing': len(missing[k]),
                                              'expected': len(datasets[k]) + len(missing[k])} for k in datasets},
                   'missing_valid_times': {k: len(v) for k, v in missing.items()}, 'missing_details': missing,
                   'coefficient_features': ['intercept', 'forecast_u', 'forecast_v', 'forecast_speed', 'lead_hours',
                                            'latitude', 'longitude', 'offshore'] +
                                           (['sin_year', 'cos_year'] if result['selected_season_encoding'] == 'cyclic'
                                            else ['spring', 'summer', 'autumn'])})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(f'Saved {args.output}; selected {result["selected_season_encoding"]}; missing times: {result["missing_valid_times"]}')


if __name__ == '__main__': main()
