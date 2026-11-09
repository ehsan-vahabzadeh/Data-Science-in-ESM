"""Prepare a macOS launchd schedule for the resumable Open-Meteo downloader."""
import argparse
import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'org.data-science-in-esm.openmeteo'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'config' / f'{LABEL}.plist')
    args = parser.parse_args()
    log_dir = ROOT / 'data' / 'open-meteo-uk-eez'
    if args.output.exists():
        raise SystemExit(f'Refusing to overwrite {args.output}')
    log_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    job = {'Label': LABEL, 'ProgramArguments': [sys.executable, str(ROOT / 'OpenMeteoMatch.py'), '--max-days', '5'],
           'WorkingDirectory': str(ROOT), 'StartCalendarInterval': {'Hour': 2, 'Minute': 15},
           'StandardOutPath': str(log_dir / 'scheduled-download.log'),
           'StandardErrorPath': str(log_dir / 'scheduled-download-error.log')}
    with args.output.open('xb') as f:
        plistlib.dump(job, f)
    print(f'Prepared {args.output}; it is not installed or running.')


if __name__ == '__main__':
    main()
