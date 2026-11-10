"""Demonstrate a training-day mean bias correction on the following day."""
import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from scripts.compare_tigge_era5 import on_grid, read_grib, six_hour_solar


def checked_pairs(forecast, reference):
    forecast = np.asarray(forecast, dtype=float)
    reference = np.asarray(reference, dtype=float)
    if forecast.size == 0 or forecast.shape != reference.shape or not np.isfinite(forecast).all() or not np.isfinite(reference).all():
        raise ValueError('Forecast and reference must be nonempty, finite, and identically shaped')
    return forecast, reference


def fit_bias(forecast, reference):
    forecast, reference = checked_pairs(forecast, reference)
    return float(np.mean(reference - forecast))


def score_forecast(forecast, reference, offset):
    forecast, reference = checked_pairs(forecast, reference)
    if not np.isfinite(offset):
        raise ValueError('Offset must be finite')
    adjusted = np.maximum(forecast + offset, 0.)
    scores = {'count': int(forecast.size)}
    for label, prediction in [('raw', forecast), ('adjusted', adjusted)]:
        residual = prediction - reference
        scores[f'{label}_bias'] = float(np.mean(residual))
        scores[f'{label}_mae'] = float(np.mean(np.abs(residual)))
        scores[f'{label}_rmse'] = float(np.sqrt(np.mean(residual**2)))
    return scores


def run(args):
    days = [args.train_date, args.train_date + timedelta(days=1)]
    runs = {datetime.combine(day - timedelta(days=1), datetime.min.time()).replace(hour=12) for day in days}
    forecast_fields = read_grib(args.forecast, lambda n, i, v, s: i in runs and n in {'10u', '10v', 'ssr'} and s in {12, 18, 24, 30})
    era_fields = read_grib(args.era5, lambda n, i, v, s: v.date() in days and 1 <= v.hour <= 18 and n in {'10u', '10v', 'ssr'})
    references = {}
    for (name, init, valid, step), field in era_fields.items():
        if (name, valid) in references:
            raise ValueError(f'Duplicate ERA5 field {name} {valid}')
        references[name, valid] = field
    with args.grid.open(newline='') as stream:
        mask = {(round(float(row['latitude']), 4), round(float(row['longitude']), 4)): row['region'] for row in csv.DictReader(stream)}
    dataset = {}
    for day in days:
        init = datetime.combine(day - timedelta(days=1), datetime.min.time()).replace(hour=12)
        lat, lon, _ = forecast_fields['10u', init, init + timedelta(hours=18), 18]
        indices = [i for i, (a, b) in enumerate(zip(lat, lon)) if (round(float(a), 4), round(float(b), 4)) in mask]
        if not indices:
            raise ValueError('No forecast points match the UK grid mask')
        by_type = {'wind': ([], []), 'solar': ([], [])}
        for step in (18, 24, 30):
            valid = init + timedelta(hours=step)
            def forecast_field(name, at, lead):
                return on_grid(forecast_fields[name, init, at, lead], lat, lon)
            u = forecast_field('10u', valid, step); v = forecast_field('10v', valid, step)
            ref_u = on_grid(references['10u', valid], lat, lon); ref_v = on_grid(references['10v', valid], lat, lon)
            solar, solar_ref = six_hour_solar(forecast_field('ssr', valid, step), forecast_field('ssr', valid - timedelta(hours=6), step - 6),
                [on_grid(references['ssr', valid - timedelta(hours=h)], lat, lon) for h in range(5, -1, -1)])
            for variable, predicted, observed in [('wind', np.hypot(u, v), np.hypot(ref_u, ref_v)), ('solar', solar, solar_ref)]:
                by_type[variable][0].extend(predicted[indices]); by_type[variable][1].extend(observed[indices])
        dataset[day] = by_type
    report = {'training_valid_date': str(days[0]), 'evaluation_valid_date': str(days[1]),
              'grid_points': len(indices), 'forecast_leads_hours': [18, 24, 30],
              'reference': 'ERA5 reanalysis', 'scope': 'approximate UK land and maritime grid',
              'warning': 'Retrospective demonstration only: ERA5 for the training day was not available by the next forecast initialization.', 'variables': {}}
    for variable, unit in [('wind', 'm/s'), ('solar', 'W/m²')]:
        offset = fit_bias(*dataset[days[0]][variable])
        report['variables'][variable] = {'unit': unit, 'offset': offset, **score_forecast(*dataset[days[1]][variable], offset)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print('Saved', args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast', type=Path, required=True)
    parser.add_argument('--era5', type=Path, required=True)
    parser.add_argument('--grid', type=Path, default=Path('config/uk-land-and-eez-0.5deg.csv'))
    parser.add_argument('--train-date', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
