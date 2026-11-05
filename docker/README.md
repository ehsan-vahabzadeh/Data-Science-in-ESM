# Docker setup for the weather workflows

Run these commands **from the repository root**. The Compose file is in this
folder, while its build context and the mounted `data/` and `outputs/` folders
are at the repository root. Use `-f docker/compose.yaml` in every command.

## What is here

- `Dockerfile` builds one Python 3.12 image with the three weather scripts and
  the REPD farm CSV.
- `compose.yaml` defines named `era5`, `ml`, and `verify` jobs.
- `requirements.txt` lists direct Python dependencies; `requirements.lock`
  pins the resolved versions.
- `Dockerfile.dockerignore` limits the build context to the scripts,
  dependencies, and REPD CSV. Datasets, generated results, caches, and
  credentials are excluded from the image.

The image is disposable. Downloads and results stay on the host through mounts
of `data/` and `outputs/`. The Copernicus credential file is mounted read only
for the jobs that need it.

## Prerequisites and build

- Docker Engine or Docker Desktop with the **Compose plugin** installed and
  running. A Docker client alone does not provide `docker compose`.
- Network access to download the base image and Python packages for the build.
- For the `era5` and `verify` jobs, configure `~/.cdsapirc` and accept the
  Copernicus ERA5 licence. Keep this credential outside the repository.

```bash
mkdir -p data outputs
docker compose -f docker/compose.yaml build
```

The build checks installed packages and the GRIB decoder. It does not request
weather data.

## Run the jobs

Download the full UK ERA5 cutout from 2 January 2025 through 2 January 2026
and create a daily mean map:

```bash
docker compose -f docker/compose.yaml run --rm era5
```

This requires CDS access and network connectivity. The download is large and
may take considerable time. It writes
`data/uk-era5-2025-01-02-to-2026-01-02.nc` and a map in
`outputs/container/`.

Train the historical day ahead wind and solar weather models after that cutout
exists:

```bash
docker compose -f docker/compose.yaml run --rm ml
```

The job reads the cutout and bundled REPD CSV. It writes farm forecasts, maps,
and backtest metrics to `outputs/container/day-ahead-weather/`. Cartopy may
fetch map features on its first run; its cache is stored under `data/.cache/`.

Cache a recent ECMWF IFS forecast and request its ERA5T reference:

```bash
docker compose -f docker/compose.yaml run --rm verify
```

The default selects today's UTC valid day and the preceding day's 12:00 UTC
forecast. Recent IFS data can be cached before ERA5T is available. Record the
chosen valid day, then rerun after ERA5T has appeared:

```bash
VERIFY_VALID_DAY=YYYY-MM-DD docker compose -f docker/compose.yaml run --rm verify
```

Both runs require network access; the reference request needs CDS access.
Forecast GRIB files are cached in `data/ecmwf/`, the ERA5T cutout goes into
`data/`, and maps, metrics, and NetCDF comparisons go into
`outputs/container/ecmwf-verification/`. ECMWF's open forecast data is a
rolling recent archive, so the August 2026 example requires forecast GRIB
files that were cached at the time. Its saved processed comparison is already
in `outputs/ecmwf-verification/`.

The credential mount uses `${HOME}/.cdsapirc`. If `HOME` does not identify the
host directory holding the file, set it for Compose or change the mount in
`compose.yaml`.

## Check the setup

```bash
docker compose -f docker/compose.yaml config --quiet
docker compose -f docker/compose.yaml run --rm --no-deps ml python UKDayAheadWeatherML.py --help
docker compose -f docker/compose.yaml run --rm --no-deps ml python ECMWFForecastVerification.py --help
```

The annual cutout is not included in the repository, so the full ML backtest
depends on the ERA5 download. For an explanation of the models and data, read
[PROJECT_GUIDE.md](../PROJECT_GUIDE.md).
