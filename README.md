# Data Science in ESM: containerised weather workflows

This repository has three documented weather workflows. Docker supplies their
Python environment; data and results live in folders on your machine. The
older exploratory scripts are not part of this image.

## What containerising a repository requires

1. Identify the command or service that should run and its required inputs.
2. Record the runtime and dependencies, including native libraries.
3. Separate source code from datasets, generated files, caches, and secrets.
4. Define the image and the commands that run inside it.
5. Test the build, the commands, and whether files survive container removal.

This project uses one Python 3.12 image and three one-off Compose services.
The image includes the scripts and the REPD farm CSV. `data/` holds downloaded
NetCDF and GRIB files; `outputs/container/` holds generated figures, metrics,
and CSVs without replacing the example outputs already checked in.
Neither folder is copied into the image. `requirements.txt` lists the direct
dependencies and `requirements.lock` records the exact versions resolved by
the first image build. The image installs both files and checks their
compatibility. Update the lockfile deliberately when changing dependencies.

## Prerequisites

- Docker Engine or Docker Desktop with Compose, running.
- Network access to pull the base image and Python packages when building.
- For ERA5 downloads, a valid `~/.cdsapirc` and accepted Copernicus ERA5
  licence terms. The file is mounted read only for the `era5` and `verify`
  commands, so it must exist before either command starts. It must stay
  outside the repository and image.

Create the host folders before running Compose so your user owns them:

```bash
mkdir -p data outputs
docker compose build
```

## Run the workflows

Download the 2025-01-02 through 2026-01-02 ERA5 cutout and draw the daily
weather map:

```bash
docker compose run --rm era5
```

This needs CDS credentials and network access. The request covers a full UK
year and can take substantial time and storage. The cutout is saved as
`data/uk-era5-2025-01-02-to-2026-01-02.nc`; the map is saved in
`outputs/container/`.
Rerunning can reuse fields already present in the cutout.

Run the historical day-ahead ML backtest after the annual cutout exists:

```bash
docker compose run --rm ml
```

This reads the cutout from `data/` and the bundled REPD CSV. Its results appear
in `outputs/container/day-ahead-weather/`. The model uses local files, but
Cartopy may download map features on the first run. Those features are cached
under `data/.cache/cartopy/` for later offline runs.

Cache a recent ECMWF forecast and request its one-day ERA5T reference:

```bash
docker compose run --rm verify
```

By default, `verify` selects today's UTC valid day and yesterday's 12:00 UTC
forecast run. ECMWF Open Data retains only about 2–3 days of runs, while ERA5T
normally becomes available about five days later. The first run therefore
usually caches forecast GRIB files in `data/ecmwf/` and reports that its ERA5T
reference is missing. Save the date you chose, then rerun once ERA5T is ready:

```bash
VERIFY_VALID_DAY=YYYY-MM-DD docker compose run --rm verify
```

Use the actual first-run UTC date in place of `YYYY-MM-DD`. The second run
reuses the cached GRIB files, downloads the reference to `data/`, and writes
results in `outputs/container/ecmwf-verification/`. Both runs need network
access; the
ERA5T request uses the mounted CDS credentials. [ECMWF documents the rolling
forecast archive](https://www.ecmwf.int/en/forecasts/datasets/open-data). The August
2026 example in `ECMWF_NWP_VERIFICATION.md` requires previously cached GRIB
files because it is no longer in that archive. Its one-day ERA5 file is
checked into this repository and can be copied to `data/` for such a rerun.

The container reads `~/.cdsapirc` from the host at run time; neither the
credential nor downloaded datasets are used during image build. On a host
where `$HOME` does not point to the credential file, set `HOME` for Compose
or edit the credential mount path in `compose.yaml`.

## Check the setup

```bash
docker compose config --quiet
docker compose run --rm --no-deps ml python UKDayAheadWeatherML.py --help
docker compose run --rm --no-deps ml python ECMWFForecastVerification.py --help
```

The image also checks the GRIB decoder during build with
`python -m cfgrib selfcheck`. The annual cutout is not included in this
repository, so a full ML run requires the preceding ERA5 download.
