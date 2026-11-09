"""Check a small set of IFS forecasts and ERA5 references at two UK sites."""

import argparse
import calendar
import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


SITES = [
    {"name": "South Beach Wind Turbine (Somerton)", "kind": "wind", "latitude": 52.709894, "longitude": 1.654462},
    {"name": "Fen Farm Solar Park", "kind": "solar", "latitude": 53.41731, "longitude": 0.08515},
]
RUN_DATES = [date(2024, 10, 15), date(2025, 10, 15), date(2026, 10, 15)]
OUTPUT = Path("data/open-meteo-pilot/pilot.json")


def fetch(endpoint, parameters):
    url = endpoint + "?" + urllib.parse.urlencode(parameters)
    with urllib.request.urlopen(url, timeout=30) as response:
        return {"url": url, "response": json.load(response)}


def target_values(payload, variable, target_day):
    """Select 24 UTC hours; radiation timestamps end the preceding hour."""
    hourly = payload["hourly"]
    times, values = hourly["time"], hourly[variable]
    if len(times) != len(values) or len(set(times)) != len(times):
        raise ValueError(f"Invalid or duplicate {variable} timestamps")
    by_time = dict(zip(times, values))
    start = datetime.combine(target_day, time())
    if variable == "shortwave_radiation":
        start += timedelta(hours=1)
    selected = [by_time.get((start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")) for i in range(24)]
    missing = sum(value is None or not isinstance(value, (int, float)) or not math.isfinite(value) for value in selected)
    return {"expected_hours": 24, "missing_hours": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", help="Sample each run date in YYYY-MM, instead of the three default dates")
    args = parser.parse_args()
    if args.month:
        try:
            first = date.fromisoformat(args.month + "-01")
        except ValueError:
            parser.error("--month must be a valid YYYY-MM")
        run_dates = [first + timedelta(days=i) for i in range(calendar.monthrange(first.year, first.month)[1])]
        output_path = OUTPUT.with_name(f"pilot-{args.month}.json")
    else:
        run_dates, output_path = RUN_DATES, OUTPUT
    if output_path.exists():
        raise SystemExit(f"Refusing to overwrite {output_path}; move it to retain the existing sample.")
    samples = []
    common = {"hourly": "wind_speed_100m,shortwave_radiation", "wind_speed_unit": "ms", "timezone": "GMT"}
    for run_day in run_dates:
        target_day = run_day + timedelta(days=1)
        for site in SITES:
            location = {"latitude": site["latitude"], "longitude": site["longitude"]}
            forecast = fetch("https://single-runs-api.open-meteo.com/v1/forecast", common | location | {
                "models": "ecmwf_ifs", "run": f"{run_day}T12:00", "forecast_days": 2,
            })
            reference = fetch("https://archive-api.open-meteo.com/v1/archive", common | location | {
                "models": "era5", "start_date": str(target_day), "end_date": str(target_day + timedelta(days=1)),
            })
            audit = {}
            for label, data in (("forecast", forecast), ("reference", reference)):
                payload = data["response"]
                if payload.get("utc_offset_seconds") != 0 or payload.get("hourly_units", {}).get("wind_speed_100m") != "m/s" or payload.get("hourly_units", {}).get("shortwave_radiation") != "W/m²":
                    raise ValueError(f"Unexpected timezone or units for {label}: {site['name']} {run_day}")
                audit[label] = {variable: target_values(payload, variable, target_day) for variable in ("wind_speed_100m", "shortwave_radiation")}
                print(f"{run_day} {site['kind']} {label}: grid ({payload['latitude']}, {payload['longitude']}), missing hours "
                      f"wind={audit[label]['wind_speed_100m']['missing_hours']}, solar={audit[label]['shortwave_radiation']['missing_hours']}", flush=True)
            samples.append({"site": site, "run_utc": f"{run_day}T12:00Z", "target_day_utc": str(target_day),
                            "forecast": forecast, "reference": reference, "audit": audit})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        json.dump({"retrieved_utc": datetime.now(timezone.utc).isoformat(), "samples": samples}, output, indent=2, allow_nan=False)
        output.write("\n")
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
