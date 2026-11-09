"""Download and match day-ahead Open-Meteo IFS forecasts and ERA5 on a UK grid."""
import argparse
import csv
import fcntl
import json
import math
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GRID = Path(__file__).resolve().parent / 'config/uk-land-and-eez-0.5deg.csv'
FORECAST = 'https://single-runs-api.open-meteo.com/v1/forecast'
ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
PREVIOUS_DATA = Path('data/open-meteo-matched/raw')
VARIABLES = ('wind_speed_100m', 'shortwave_radiation')


def request(endpoint, params):
    url = endpoint + '?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=90) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise SystemExit('Open-Meteo rate limit reached. Cached batches are safe; try the same command after the limit resets.') from error
        raise
    # Pace requests conservatively; the provider determines the weighted quota.
    time.sleep(7)
    return {'url': url, 'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'data': data}


def hourly(payload, day):
    if payload.get('utc_offset_seconds') != 0 or payload.get('hourly_units', {}).get('wind_speed_100m') != 'm/s' or payload.get('hourly_units', {}).get('shortwave_radiation') != 'W/m²':
        raise ValueError('Unexpected timezone or units')
    h = payload['hourly']
    if len(set(h['time'])) != len(h['time']) or any(len(h[v]) != len(h['time']) for v in VARIABLES):
        raise ValueError('Duplicate or misaligned hourly data')
    lookup = {t: i for i, t in enumerate(h['time'])}
    result = []
    for hour in range(24):
        stamp = f'{day}T{hour:02}:00'
        i = lookup.get(stamp)
        values = []
        for variable in VARIABLES:
            value = h[variable][i] if i is not None else None
            values.append(float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None)
        result.append((stamp, *values))
    return result


def complete_values(payload, day):
    return all(wind is not None and solar is not None for _, wind, solar in hourly(payload, day))


def complete_output(path, points, day):
    expected = {(str(day) + f'T{hour:02}:00Z', float(point['latitude']), float(point['longitude']))
                for point in points for hour in range(24)}
    try:
        with path.open(newline='') as stream:
            seen = set()
            for row in csv.DictReader(stream):
                key = (row['valid_time_utc'], float(row['requested_latitude']), float(row['requested_longitude']))
                if key not in expected or key in seen:
                    return False
                if not all(math.isfinite(float(row[column])) for column in ('ifs_wind_ms', 'era5_wind_ms', 'wind_reference_minus_forecast_ms', 'ifs_solar_wm2', 'era5_solar_wm2', 'solar_reference_minus_forecast_wm2')):
                    return False
                seen.add(key)
            return seen == expected
    except (OSError, KeyError, TypeError, ValueError, csv.Error):
        return False


def preserve_incomplete(path):
    backup_dir = path.parent / 'incomplete'
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f'{path.stem}.incomplete-{uuid.uuid4().hex}{path.suffix}'
    with path.open('rb') as source, backup.open('xb') as destination:
        shutil.copyfileobj(source, destination)
    return backup


def distance_km(a, b):
    lat1, lat2 = math.radians(a['latitude']), math.radians(b['latitude'])
    dlat = lat2 - lat1
    dlon = math.radians(b['longitude'] - a['longitude'])
    x = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 12742 * math.asin(min(1, math.sqrt(x)))


def matched_rows(points, forecast, reference, day):
    if len(points) != len(forecast) or len(points) != len(reference):
        raise ValueError('API location count does not match requested grid')
    for point, f, r in zip(points, forecast, reference):
        distance = distance_km(f, r)
        f_values, r_values = hourly(f, day), hourly(r, day)
        for (stamp, fw, fs), (other, rw, rs) in zip(f_values, r_values):
            if stamp != other:
                raise ValueError('Forecast and reference times do not match')
            yield {'valid_time_utc': stamp + 'Z', 'ifs_run_utc': str(day - timedelta(days=1)) + 'T12:00Z',
                   'forecast_lead_hours': int((datetime.fromisoformat(stamp) - datetime.combine(day - timedelta(days=1), datetime.min.time()) - timedelta(hours=12)).total_seconds() / 3600),
                   'requested_latitude': point['latitude'], 'requested_longitude': point['longitude'], 'region': point['region'],
                   'ifs_latitude': f['latitude'], 'ifs_longitude': f['longitude'], 'era5_latitude': r['latitude'], 'era5_longitude': r['longitude'], 'grid_centre_distance_km': round(distance, 3),
                   'ifs_wind_ms': fw, 'era5_wind_ms': rw, 'wind_reference_minus_forecast_ms': None if fw is None or rw is None else rw-fw,
                   'ifs_solar_wm2': fs, 'era5_solar_wm2': rs, 'solar_reference_minus_forecast_wm2': None if fs is None or rs is None else rs-fs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-date', type=date.fromisoformat, default=date(2024, 3, 15), help='first valid day (default: 2024-03-15; first IFS run is March 14)')
    parser.add_argument('--end-date', type=date.fromisoformat, help='last valid day (default: seven days ago to allow ERA5 lag)')
    parser.add_argument('--max-days', type=int, default=5, help='maximum days to process per run, including incomplete retries (default: 5)')
    parser.add_argument('--output-dir', type=Path, default=Path('data/open-meteo-uk-eez'))
    args = parser.parse_args()
    if args.max_days < 1 or args.start_date < date(2024, 3, 15):
        parser.error('--max-days must be positive and --start-date must be 2024-03-15 or later')
    with GRID.open(newline='') as f:
        points = [{'latitude': float(p['latitude']), 'longitude': float(p['longitude']), 'region': p['region']} for p in csv.DictReader(f)]
    end = args.end_date or datetime.now(timezone.utc).date() - timedelta(days=7)
    if end < args.start_date:
        raise SystemExit('No available dates in the requested range.')
    print(f'Target valid days {args.start_date} to {end}; {len(points)} grid points; processing at most {args.max_days} days, including retries.', flush=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / '.download.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another downloader is already running for this output directory.')
        download(args, points, end)


def download(args, points, end):
    # Rotate one incomplete-day retry per run, leaving capacity for new days.
    status = {}
    for path in args.output_dir.glob('matched-????-??-??.csv'):
        try:
            file_day = date.fromisoformat(path.stem[8:])
        except ValueError:
            continue
        if args.start_date <= file_day <= end:
            status[file_day] = complete_output(path, points, file_day)
    incomplete = sorted(day for day, complete in status.items() if not complete)
    cursor = args.output_dir / '.incomplete-retry-cursor'
    last_retry = cursor.read_text().strip() if cursor.exists() else ''
    retry_day = next((day for day in incomplete if str(day) > last_retry), incomplete[0] if incomplete else None)
    completed = 0
    day = args.start_date
    block_start = block_end = None
    while day <= end and completed < args.max_days:
        output = args.output_dir / f'matched-{day}.csv'
        if output.exists() and (status.get(day, False) or day != retry_day):
            day += timedelta(days=1)
            continue
        if output.exists():
            cursor.write_text(str(day) + '\n')
        if block_end is None or day > block_end:
            block_start = day
            block_end = min(day + timedelta(days=13), end)
            while block_end > day and (args.output_dir / f'matched-{block_end}.csv').exists():
                block_end -= timedelta(days=1)
        raw_dir = args.output_dir / 'raw' / str(day)
        raw_dir.mkdir(parents=True, exist_ok=True)
        # Reuse the earlier surrounding-sea run without changing its saved data.
        previous = PREVIOUS_DATA / str(day)
        reused = raw_dir / 'reused-wider-area'
        if previous.exists() and previous.resolve() != raw_dir.resolve() and not reused.exists():
            shutil.copytree(previous, reused)
        existing = {'ifs': {}, 'era5': {}}
        for label in existing:
            for cache in sorted(reused.glob(f'{label}-*.json')) if reused.exists() else []:
                payload = json.loads(cache.read_text())
                parsed_url = urllib.parse.urlparse(payload['url'])
                expected_endpoint = FORECAST if label == 'ifs' else ARCHIVE
                if f'{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}' != expected_endpoint:
                    raise ValueError(f'Unexpected source endpoint in cached response {cache}')
                args_in_url = urllib.parse.parse_qs(parsed_url.query)
                expected_model = 'ecmwf_ifs' if label == 'ifs' else 'era5'
                if args_in_url.get('models') != [expected_model] or args_in_url.get('hourly') != [','.join(VARIABLES)] or args_in_url.get('wind_speed_unit') != ['ms'] or args_in_url.get('timezone') != ['GMT'] or args_in_url.get('cell_selection') != ['nearest'] or any(v != 'nan' for v in args_in_url.get('elevation', [''])[0].split(',')):
                    raise ValueError(f'Unexpected settings in cached response {cache}')
                if label == 'ifs' and args_in_url.get('run') != [f'{day-timedelta(days=1)}T12:00']:
                    raise ValueError(f'Unexpected IFS run in cached response {cache}')
                if label == 'era5' and (args_in_url.get('start_date') != [str(day)] or args_in_url.get('end_date') != [str(day)]):
                    raise ValueError(f'Unexpected ERA5 dates in cached response {cache}')
                lats = [float(x) for x in args_in_url['latitude'][0].split(',')]
                lons = [float(x) for x in args_in_url['longitude'][0].split(',')]
                values = payload['data'] if isinstance(payload['data'], list) else [payload['data']]
                if not len(lats) == len(lons) == len(values):
                    raise ValueError(f'Invalid cached location count in {cache}')
                for lat, lon, value in zip(lats, lons, values):
                    if complete_values(value, day):
                        existing[label][(lat, lon)] = value
        batches = []
        for start in range(0, len(points), 50):
            batch = points[start:start+50]
            pair = []
            for label, endpoint, specific in [('ifs', FORECAST, {'models': 'ecmwf_ifs', 'run': f'{day-timedelta(days=1)}T12:00', 'forecast_hours': 36}), ('era5', ARCHIVE, {'models': 'era5', 'start_date': str(day), 'end_date': str(day)})]:
                missing = [p for p in batch if (p['latitude'], p['longitude']) not in existing[label]]
                if missing:
                    block_dir = args.output_dir / 'raw' / 'era5-blocks'
                    matching_blocks = []
                    if label == 'era5' and block_dir.exists():
                        for candidate in sorted(block_dir.glob(f'*_{start:03}.json')):
                            parts = candidate.stem.split('_')
                            if len(parts) == 3 and parts[0] <= str(day) <= parts[1]:
                                matching_blocks.append((candidate, parts[0], parts[1]))
                    if matching_blocks:
                        cache, first, last = matching_blocks[0]
                        missing = batch
                        specific = {'models': 'era5', 'start_date': first, 'end_date': last}
                    elif label == 'era5' and block_end > block_start:
                        # Stable full-batch blocks can be reused by subsequent days and resumed runs.
                        missing = batch
                        specific = {'models': 'era5', 'start_date': str(block_start), 'end_date': str(block_end)}
                        block_dir.mkdir(parents=True, exist_ok=True)
                        cache = block_dir / f'{block_start}_{block_end}_{start:03}.json'
                    else:
                        cache = raw_dir / f'{label}-{start:03}.json'
                    if cache.exists():
                        payload = json.loads(cache.read_text())
                        parsed_url = urllib.parse.urlparse(payload['url'])
                        if f'{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}' != endpoint:
                            raise ValueError(f'Unexpected source endpoint in cached response {cache}')
                        stored = urllib.parse.parse_qs(parsed_url.query)
                        stored_points = list(zip([float(x) for x in stored['latitude'][0].split(',')], [float(x) for x in stored['longitude'][0].split(',')]))
                        if stored_points != [(p['latitude'], p['longitude']) for p in missing] or any(stored.get(k) != [str(v)] for k, v in specific.items()) or stored.get('hourly') != [','.join(VARIABLES)] or stored.get('wind_speed_unit') != ['ms'] or stored.get('timezone') != ['GMT'] or stored.get('cell_selection') != ['nearest'] or stored.get('elevation') != [','.join('nan' for _ in missing)]:
                            raise ValueError(f'Cached request does not match the current grid and run: {cache}')
                    else:
                        payload = None
                    if payload is not None:
                        cached_values = payload['data'] if isinstance(payload['data'], list) else [payload['data']]
                        if len(cached_values) != len(missing) or not all(complete_values(value, day) for value in cached_values):
                            payload = None
                    if payload is None:
                        common = {'latitude': ','.join(str(p['latitude']) for p in missing), 'longitude': ','.join(str(p['longitude']) for p in missing), 'hourly': ','.join(VARIABLES), 'wind_speed_unit': 'ms', 'timezone': 'GMT', 'cell_selection': 'nearest', 'elevation': ','.join('nan' for _ in missing)}
                        print(f'{day}: {label} points {start+1}–{start+len(batch)} ({len(missing)} new) of {len(points)}', flush=True)
                        while True:
                            payload = request(endpoint, common | specific)
                            values = payload['data'] if isinstance(payload['data'], list) else [payload['data']]
                            if len(values) != len(missing):
                                raise ValueError('Unexpected number of API locations')
                            for value in values:
                                hourly(value, day)
                                if label == 'ifs' and any(f'{day}T{hour:02}:00' not in value['hourly']['time'] for hour in range(24)):
                                    raise ValueError(f'IFS response is missing required forecast hours for {day}; it was not cached.')
                            if label != 'era5':
                                break
                            first = date.fromisoformat(specific['start_date'])
                            last = date.fromisoformat(specific['end_date'])
                            unavailable = next((first + timedelta(days=offset) for offset in range((last - first).days + 1)
                                                if not any(w is not None and solar is not None for value in values
                                                           for _, w, solar in hourly(value, first + timedelta(days=offset)))), None)
                            if unavailable is None:
                                break
                            if unavailable <= day:
                                raise SystemExit(f'ERA5 has no paired values for {unavailable} in this batch yet. No incomplete block was cached.')
                            block_end = unavailable - timedelta(days=1)
                            specific['end_date'] = str(block_end)
                            block_dir.mkdir(parents=True, exist_ok=True)
                            cache = block_dir / f"{specific['start_date']}_{specific['end_date']}_{start:03}.json"
                            print(f'ERA5 unavailable from {unavailable}; retrying through {block_end}.', flush=True)
                        temp = cache.with_suffix('.part')
                        try:
                            temp.write_text(json.dumps(payload, allow_nan=False))
                            if cache.exists():
                                preserve_incomplete(cache)
                            temp.replace(cache)
                        finally:
                            temp.unlink(missing_ok=True)
                    values = payload['data'] if isinstance(payload['data'], list) else [payload['data']]
                    if len(values) != len(missing):
                        raise ValueError('Cached API location count does not match the grid')
                    for point, value in zip(missing, values):
                        existing[label][(point['latitude'], point['longitude'])] = value
                pair.append([existing[label][(p['latitude'], p['longitude'])] for p in batch])
            batches.extend(matched_rows(batch, pair[0], pair[1], day))
        temp = output.with_suffix('.part')
        try:
            with temp.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(batches[0]))
                writer.writeheader()
                writer.writerows(batches)
            if output.exists():
                preserve_incomplete(output)
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)
        complete_wind = sum(row['wind_reference_minus_forecast_ms'] is not None for row in batches)
        complete_solar = sum(row['solar_reference_minus_forecast_wm2'] is not None for row in batches)
        print(f'Saved {output}: {len(batches)} rows, matched wind {complete_wind}, solar {complete_solar}.', flush=True)
        completed += 1
        day += timedelta(days=1)
    print(f'Processed {completed} days. Repeat the same command to resume or retry incomplete data.', flush=True)


if __name__ == '__main__':
    main()
