"""Collect monthly UK ERA5 wind and solar batches with a resumable job manifest."""
import argparse
import calendar
from datetime import date
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import cdsapi
import requests

CDS_URL = 'https://cds.climate.copernicus.eu/api'
DATASET = 'reanalysis-era5-single-levels'


def monthly_requests(end):
    """Plan from Jan 2024 through end: wind at TIGGE times, solar hourly."""
    if end < date(2024, 1, 1):
        raise ValueError('End date must be in 2024 or later')
    year, month = 2024, 1
    while (year, month) <= (end.year, end.month):
        last = min(calendar.monthrange(year, month)[1], end.day if (year, month) == (end.year, end.month) else 31)
        common = {'product_type': ['reanalysis'], 'year': [str(year)], 'month': [f'{month:02d}'],
                  'day': [f'{day:02d}' for day in range(1, last + 1)],
                  'data_format': 'grib', 'download_format': 'unarchived', 'area': [62, -12, 48, 4]}
        for kind, variables, hours in (
            ('wind', ['10m_u_component_of_wind', '10m_v_component_of_wind'], (0, 6, 12, 18)),
            ('solar', ['surface_net_solar_radiation'], range(24)),
        ):
            name = f'{year}-{month:02d}-{kind}'
            yield name, {**common, 'variable': variables, 'time': [f'{hour:02d}:00' for hour in hours]}
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def read_key(path):
    for line in path.read_text().splitlines():
        if line.strip().startswith('key:'):
            value = line.split(':', 1)[1].strip().strip("'\"")
            if value:
                return value
    raise ValueError('No API key in ~/.cdsapirc')


def save_manifest(path, manifest):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest, indent=2) + '\n')
    tmp.replace(path)


def update_plan(manifest, end):
    for name, payload in monthly_requests(end):
        if name not in manifest['jobs']:
            manifest['jobs'][name] = {'request': payload, 'state': 'pending'}
            continue
        job = manifest['jobs'][name]
        if job['request'] == payload:
            continue
        previous = job['request']
        same_settings = {k: v for k, v in previous.items() if k != 'day'} == {k: v for k, v in payload.items() if k != 'day'}
        extended = payload['day'][:len(previous['day'])] == previous['day']
        if job['state'] != 'pending' or not same_settings or not extended:
            raise ValueError(f'Existing batch {name} has a different request; use a new output folder')
        job['request'] = payload


def fetch_result(session, base, job_id, target):
    response = session.get(f'{base}/jobs/{job_id}/results', timeout=60)
    response.raise_for_status()
    asset = response.json()['asset']['value']
    size = int(asset['file:size'])
    checksum = str(asset['file:checksum']).lower()
    if not re.fullmatch(r'[0-9a-f]{1,32}', checksum):
        raise ValueError(f'Invalid MD5 checksum for {target.name}')
    # CDS may omit leading zeroes from a hexadecimal MD5 digest.
    checksum = checksum.zfill(32)
    if target.exists():
        digest = hashlib.md5()
        with target.open('rb') as existing:
            for chunk in iter(lambda: existing.read(1024 * 1024), b''):
                digest.update(chunk)
        if target.stat().st_size != size or digest.hexdigest() != checksum:
            raise ValueError(f'Existing file differs from requested data: {target.name}')
        return size, checksum
    temporary = target.with_suffix('.part'); digest = hashlib.md5(); count = 0
    with session.get(asset['href'], stream=True, timeout=120) as download:
        download.raise_for_status()
        with temporary.open('wb') as out:
            for chunk in download.iter_content(1024 * 1024):
                if chunk:
                    out.write(chunk); digest.update(chunk); count += len(chunk)
    if count != size or digest.hexdigest() != checksum:
        temporary.unlink(missing_ok=True)
        raise ValueError(f'Checksum or size mismatch for {target.name}')
    temporary.replace(target)
    return size, checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end', required=True, type=date.fromisoformat, help='Last ERA5 valid date to request')
    parser.add_argument('--output', type=Path, default=Path('data/era5/monthly'))
    parser.add_argument('--max-active', type=int, default=4)
    parser.add_argument('--poll-seconds', type=int, default=20)
    args = parser.parse_args()
    if args.max_active < 1 or args.poll_seconds < 1:
        parser.error('Concurrency and poll interval must be positive')
    key = read_key(Path.home() / '.cdsapirc')
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / '.collection.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Another collector is using this output directory') from None
    path = args.output / 'manifest.json'
    manifest = json.loads(path.read_text()) if path.exists() else {'dataset': DATASET, 'jobs': {}}
    update_plan(manifest, args.end)
    save_manifest(path, manifest)
    client = cdsapi.Client(url=CDS_URL, key=key, quiet=True, timeout=60, wait_until_complete=False,
                           retry_max=3, sleep_max=5)
    session = requests.Session(); session.headers['PRIVATE-TOKEN'] = key
    base = CDS_URL + '/retrieve/v1'
    while True:
        jobs = manifest['jobs']
        active = sum(j['state'] in ('accepted', 'running') for j in jobs.values())
        submission_failed = False
        for name, job in jobs.items():
            if active >= args.max_active:
                break
            if job['state'] != 'pending':
                continue
            try:
                result = client.retrieve(DATASET, job['request'])
                match = re.search(r'/jobs/([a-f0-9-]+)', str(result))
                if not match:
                    raise ValueError('No job ID returned')
                job.update(state='accepted', job_id=match.group(1)); active += 1
                save_manifest(path, manifest)
                print(f'{name}: submitted {job["job_id"]}', flush=True)
            except Exception as exc:
                message = str(exc).replace(key, '[REDACTED]')
                print(f'{name}: submission failed: {type(exc).__name__}: {message[:500]}', file=sys.stderr, flush=True)
                save_manifest(path, manifest)
                submission_failed = True
                break
        for name, job in jobs.items():
            if job['state'] not in ('accepted', 'running'):
                continue
            response = session.get(f'{base}/jobs/{job["job_id"]}', timeout=60); response.raise_for_status()
            state = response.json().get('status')
            if state in ('accepted', 'running'):
                job['state'] = state
            elif state == 'successful':
                size, checksum = fetch_result(session, base, job['job_id'], args.output / f'{name}.grib')
                job.update(state='downloaded', size_bytes=size, md5=checksum)
                print(f'{name}: downloaded {size} bytes; checksum verified', flush=True)
            else:
                job.update(state='failed', remote_status=state)
                print(f'{name}: remote job ended with status {state}; inspect job {job["job_id"]}', file=sys.stderr, flush=True)
            save_manifest(path, manifest)
        counts = {state: sum(job['state'] == state for job in jobs.values()) for state in ('pending','accepted','running','downloaded','failed')}
        print('Progress:', counts, flush=True)
        if counts['failed']:
            return 1
        if submission_failed and not (counts['accepted'] or counts['running']):
            print('No requests are active; restart to retry pending batches.', flush=True)
            return 1
        if not (counts['pending'] or counts['accepted'] or counts['running']):
            return 0
        time.sleep(args.poll_seconds)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Collection stopped: {type(exc).__name__}; inspect local manifest and retry.', file=sys.stderr)
        sys.exit(1)
