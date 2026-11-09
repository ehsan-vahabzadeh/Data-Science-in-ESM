# Matching UK IFS and ERA5 data from Open-Meteo

## Scope and method

`OpenMeteoMatch.py` downloads 100 m wind speed and downward shortwave radiation, and pairs IFS with ERA5 at the same hourly UTC valid time. It selects the 12:00 UTC IFS run from the previous day, with lead times +12 to +35 hours. Wind is instantaneous; each solar value is the **mean over the hour ending at the timestamp**. Thus the 00:00 solar value refers to 23:00–00:00, not the following hour. Both sources use the same convention.

The candidate grid contains 565 locations at 0.5° spacing: 134 UK land points and 431 offshore points within the British EEZ or UK/Faroe joint regime in Marine Regions v12. Land classification uses Natural Earth 1:50m country boundaries. This is an approximate published representation, not a legal boundary determination; islands and waters outside the UK are excluded. Small islands may be omitted. This is a sample grid, not all of the native 9 km IFS or 0.25° ERA5 cells.

The offshore polygon is [Marine Regions EEZ v12](https://marineregions.org/eezmethodology.php), Flanders Marine Institute (2023), accessed via [this polygon service](https://services1.arcgis.com/ZdmoaKLXhx5EdwBs/ArcGIS/rest/services/MarineRegions_EEZ/FeatureServer/0). We selected `ISO_TER1=GBR` (including the joint-regime polygon) and used point-centre coverage. The original GeoJSON fetched on 6 November 2026 has SHA-256 `cbe0b19793d80e636fdcc197693d2b96c0aba0eb29691fb61aa3e061c08db532`. This is a research mask and must not be used as an official legal boundary.

For each requested point, Open-Meteo selects the nearest grid point separately for each product; elevation adjustment is disabled. The result records the requested location, selected IFS and ERA5 grid centres and their distance. These grid centres are generally different; the paired values are not point observations and the difference includes spatial mismatch. The CSV columns labelled `reference_minus_forecast` are ERA5 minus IFS, not independent observational errors.

The forecast endpoint requests only `wind_speed_100m,shortwave_radiation`, with `forecast_hours=36`. This includes the 12 hours between initialization and the beginning of the target day, which the endpoint returns as part of the run. ERA5 requests only the same hourly variables over bounded blocks of up to 14 consecutive target days; those values are matched against the IFS valid hours locally. No unrelated variables or annual ERA5 grid are downloaded. A multi-day block is fetched once per grid batch and reused for each forecast day, including across scheduled runs and after interruption. A block may fetch ERA5 for later dates within the requested range before their IFS runs are downloaded; these hours are retained for matching later. Full API responses are retained for provenance, including request URLs and retrieval times.

Open-Meteo documents IFS HRES single runs from **14 March 2024**. The first paired valid day is **15 March 2024**. Some early IFS runs are hindcasts: don't treat the whole archive as operational forecasts as issued or combine periods into a backtest without establishing provenance. ERA5 is reanalysis, and recent data may be preliminary. See [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), [Historical Weather](https://open-meteo.com/en/docs/historical-weather-api), and the [pilot](open-meteo-pilot.md).

## Download and resume

From the repository root, with Python 3 and internet access:

```bash
python3 OpenMeteoMatch.py
```

By default, the command begins on 15 March 2024, processes up to five days per invocation, including retries of incomplete days, and stops seven days before the current UTC date to allow for ERA5 latency. Override the end with `--end-date YYYY-MM-DD` when appropriate. It skips daily CSVs only when every expected location and hour has finite wind and solar values, retries incomplete days and reuses validated raw batches, so **repeat the command to resume**. Each run selects at most one incomplete day to retry and rotates between incomplete days; its remaining budget can collect new days. It stops on an Open-Meteo rate limit; wait for the limit to reset and run the same command again. If ERA5 is not available yet, the command stops without caching the empty batch. Open-Meteo free access is for non-commercial use and has per-minute, hourly and daily limits; location count and time span affect usage. See [pricing](https://open-meteo.com/en/pricing) and [terms](https://open-meteo.com/en/terms).

To download a smaller date range, for example:

```bash
python3 OpenMeteoMatch.py --start-date 2024-03-15 --end-date 2024-03-20 --max-days 2
```

Daily results are `data/open-meteo-uk-eez/matched-YYYY-MM-DD.csv`, with source responses under `data/open-meteo-uk-eez/raw/`. Blank values mean data was missing; inspect the reported matched counts. The data folder is ignored by Git. The default end date is seven days before today UTC; this is a buffer, not proof that data is final or that it is the latest available day. If a later ERA5 day in a block is unavailable, the downloader retries a shorter block so earlier days can be saved; if the current day is unavailable, it stops and can be retried later. IFS responses missing requested forecast timestamps are rejected rather than saved as complete. Incomplete daily outputs and caches are retained under `incomplete/` before replacement. Files can still contain missing values when a source returns null data; subsequent runs rotate through incomplete days and attempt to refresh them.

A preliminary wider-seas grid produced 11,880 fully matched rows on 15 March 2024, but it is not the UK maritime-area dataset. Its validated raw batches are reused automatically where possible and copied into the new raw-data directory for provenance. At the observed storage rate, the 565-point candidate grid over 961 days is roughly **3.2 GB** including raw responses and CSV; this is an estimate. The UK maritime-area dataset has not yet been fully collected or audited.

## Request efficiency and schedule

For a fresh five-day batch of 565 locations, the old design made up to **120 HTTP requests** (12 location batches × 5 days × 2 data sources). The new design makes up to **72** (60 IFS requests plus 12 ERA5 block requests), before accounting for already cached data; that first block can also supply up to nine additional days in subsequent runs. Across 14 days the corresponding fresh counts are 336 and 180. These are HTTP request counts, **not guaranteed Open-Meteo quota-call counts**: the provider weights multi-location and long-range queries. Its published free limits and terms still apply. The fixed seven-second pause remains conservative; request overhead decreases, but minimum download time and quota use are not yet known.

On macOS, `python3 scripts/create_openmeteo_schedule.py` prepares `config/org.data-science-in-esm.openmeteo.plist` for 02:15 local time every day. This does not install or start the job. The generator refuses to overwrite an existing plist; use that file or supply a different `--output` path. The prepared file is machine-specific and ignored by Git. It processes at most five days per invocation, including retries, stops on a 429 response and resumes cached work next time. A file lock prevents overlapping runs for the same output directory. The job needs the Mac to be powered on and able to run; it is not a cloud scheduler. Logs are written to `data/open-meteo-uk-eez/scheduled-download.log` and `scheduled-download-error.log`.

To install **only if you want automatic requests**:

```bash
mkdir -p ~/Library/LaunchAgents
cp -n config/org.data-science-in-esm.openmeteo.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/org.data-science-in-esm.openmeteo.plist
```

`cp -n` preserves an existing file, so inspect or remove an old copy before expecting changes to take effect. Stop and unload with:

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/org.data-science-in-esm.openmeteo.plist
```

The generated plist contains absolute paths. Regenerate it if the repository or Python interpreter moves. The lock uses POSIX `fcntl` and is supported on macOS and Linux; Windows needs an alternative locking implementation.
