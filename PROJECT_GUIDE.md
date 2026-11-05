# Project guide: UK wind and solar weather forecasting

**Last reviewed:** 5 November 2026. Read this page first after a break. Update
the status and decision log when the work changes. The root [README](README.md)
is the short index; the two experiment notes contain the technical details.

## One minute summary

The aim is to learn how to collect UK weather data, evaluate a real numerical
weather forecast, and train a small machine learning model for wind and solar
farm locations. This is a staged path toward day ahead renewable generation
forecasting. **The current outputs are weather variables, not MW or MWh.**

There are two distinct experiments:

1. **Historical ML backtest:** train on older ERA5 weather and predict later
   ERA5 wind speed and sunlight at UK farm grid cells. Compare with a simple
   previous day baseline. Code: `UKDayAheadWeatherML.py`.
2. **Numerical forecast verification:** compare an ECMWF IFS forecast issued
   before the target day with ERA5T for 100 m wind and surface solar radiation.
   Code: `ECMWFForecastVerification.py`.

`UKWeather.py` collects the annual ERA5 data needed by the first experiment.
The [Docker guide](docker/README.md) provides portable commands for all three
workflows.

## What each name means

| Name | What it is | Role here |
| --- | --- | --- |
| ERA5 | ECMWF historical reanalysis, produced by combining observations with a weather model | ML training and historical reference |
| ERA5T | The near real time version of ERA5 | Reference for the saved IFS comparison |
| ECMWF IFS | A numerical weather prediction model that forecasts future atmospheric conditions | The actual model forecast being verified |
| REPD | UK Renewable Energy Planning Database | Wind and solar farm locations, technology, and capacity |
| `atlite` | Python tool for preparing weather cutouts and renewable energy calculations | Downloads and processes the ERA5 grid |
| `HistGradientBoostingRegressor` | A tree ensemble that improves predictions by fitting successive small decision trees | The current historical ML model |
| Persistence | Predict tomorrow's hour using the same hour yesterday | Baseline the ML model must beat |

**Forecast versus reference:** IFS is a forecast made before the weather
happens. ERA5/ERA5T is produced after observations become available. ERA5T is a
useful gridded reference, but it is not a direct reading from a wind farm or
solar panel. Both IFS and ERA5 are ECMWF products, so comparison with ERA5T is
not fully independent observational validation.

**Weather versus electricity:** 100 m wind speed is measured in m/s; incoming
surface solar radiation is measured in W/m². Generating power requires turbine
curves, hub height, PV panel configuration, temperature, losses, availability,
and ideally measured output. REPD capacity alone cannot supply that conversion.

## Data and where it lives

| File or folder | Contents | Status |
| --- | --- | --- |
| `REPD_Publication_Q2_2026.csv` | Farm coordinates, technology, capacity | Included; used by ML |
| `UKWindFarmConfigurations_initial.csv` | Preliminary turbine and proxy configuration research | Included; future power conversion input |
| `uk-era5-2026-08-20-to-2026-08-21.nc` | One day of UK ERA5T weather | Included; saved IFS example |
| `outputs/ecmwf-verification/` | Saved August 2026 comparison fields, maps, metrics, metadata | Included in Git |
| `data/` | New ERA5 cutouts, IFS GRIB files, and caches | Local working folder; ignored by Git |
| `outputs/container/` | New results from Docker runs | Local working folder; ignored by Git |
| `outputs/uk-land-comparison/` | Local UK land only CSV from the saved comparison | Present locally; ignored by Git |

The **annual** ERA5 cutout from 2 January 2025 through 2 January 2026 is not
included. It must be downloaded before the ML backtest runs. The raw IFS GRIB
files for the August 2026 case are also absent; the saved processed comparison
NetCDF is available. ECMWF's open data only retains recent runs, so this old
forecast cannot simply be fetched again from that rolling feed.

The weather scripts work on a 0.25° longitude/latitude grid over a box around
the UK, including some sea and neighbouring land. A grid cell is a small area,
not an individual farm measurement. The ML script maps farms to nearby cells;
several farms may share a cell.

## Experiment 1: historical ML backtest

The annual ERA5 cutout provides hourly weather. The ML script groups wind and
solar farms by unique grid cell, then trains **one wind model** and **one solar
model** across their respective cells. The wind target is 100 m wind speed.
The solar target is direct plus diffuse incoming surface radiation.

The shared predictors include the target 24, 48, and 168 hours earlier, time
of day, time of year, and grid location. Wind also uses recent wind direction
and surface roughness when available. Solar uses top of atmosphere radiation
and solar altitude. The script uses `HistGradientBoostingRegressor` from
scikit-learn, with fixed model settings in the code.

By default, the last 30 days are held out for testing and all preceding days
are training data. This **chronological split** matters: a random split could
let near identical neighbouring hours appear in both training and test sets.
The model is compared with persistence, which uses the value 24 hours earlier.
Solar scores use daylight rows so zero radiation at night does not make the
model seem artificially accurate.

The script reports MAE, RMSE, R², persistence MAE, and skill against
persistence. Smaller MAE/RMSE is better. Positive skill means the ML MAE is
smaller than persistence MAE. The issue time is treated as 23:00 UTC on the
preceding day; an earlier operational issue time would need different
features. **No completed annual ML run or backtest score is stored here yet.**

See [UK_DAY_AHEAD_WEATHER.md](UK_DAY_AHEAD_WEATHER.md) for the feature and
evaluation details.

## Experiment 2: IFS versus ERA5T

The saved worked case uses an IFS forecast initialized at **12:00 UTC on
19 August 2026**. It checks **00:00 and 12:00 UTC on 20 August 2026**. Wind is
instantaneous 100 m speed, calculated from forecast eastward and northward
components: `sqrt(u100² + v100²)`. Solar is the mean incoming surface radiation
over 00:00–03:00 or 12:00–15:00 UTC. The IFS accumulated energy is converted
to W/m² by taking the interval difference and dividing by 10,800 seconds.

The saved `selected_times_verification_metrics.csv` covers the **whole
rectangular grid**, including sea. A later local comparison selected the 527
grid cells whose centres lie inside the Natural Earth UK country boundary.
These UK land cell means are not weighted by cell area:

| UK land case | IFS mean | ERA5T mean | Bias (IFS − ERA5T) | MAE |
| --- | ---: | ---: | ---: | ---: |
| 00:00 wind at 100 m | 6.06 m/s | 6.11 m/s | −0.04 m/s | 0.72 m/s |
| 12:00 wind at 100 m | 6.82 m/s | 6.47 m/s | +0.36 m/s | 0.81 m/s |
| 12:00–15:00 solar | 456 W/m² | 431 W/m² | +25 W/m² | 86 W/m² |

Both solar fields were zero in the 00:00–03:00 interval. The local full
precision table is `outputs/uk-land-comparison/ifs_vs_era5t_2026-08-20_uk_land.csv`.
Because that folder is Git ignored, this guide preserves the summary for a
fresh checkout. The saved comparison NetCDF in `outputs/ecmwf-verification/`
can be used to recalculate it.

**Bias** is the average signed difference; positive means IFS is higher.
**MAE** is the average absolute difference. **RMSE** gives larger mistakes more
weight. Percentage errors are masked where ERA5T is near zero: below 0.5 m/s
for wind or 10 W/m² for solar. A percentage error at midnight solar would be
undefined. Two times on one day illustrate the method; they do not establish
seasonal accuracy.

See [ECMWF_NWP_VERIFICATION.md](ECMWF_NWP_VERIFICATION.md) for timing, grid
alignment, formulas, and saved output details.

## How to resume work

1. Read this guide, then the detailed note for the experiment you are changing.
2. Check `git status` so you know which files have local edits.
3. Check whether the annual cutout exists under `data/` and whether you have
   CDS access before attempting the ML or ERA5 download jobs.
4. Use [docker/README.md](docker/README.md) to build and run the named jobs.
5. Record the data period, forecast initialization, target day, metrics, and
   limitations whenever you add a result. Update this guide's status and
   decision log so the next session starts with the right context.

## Current limits and next useful steps

- The annual ERA5 cutout and completed ML backtest are still missing. Obtain
  the cutout, run the ML job, and record both model and persistence scores.
- The August IFS example has processed fields but no raw GRIB files. For a
  repeatable new case, cache a **recent** forecast first, then compare it after
  ERA5T becomes available. Save issue times and raw forecast provenance.
- Evaluate many forecast days and seasons before drawing conclusions about
  model performance. Include separate onshore, offshore, and solar results.
- Add independent observations when available. ERA5T is a useful reference,
  but weather stations, buoys, lidar, satellite radiation, or site telemetry
  would strengthen validation.
- For electricity forecasts, add site equipment models and measured generation
  data. Train any future bias correction on archived forecasts as issued,
  paired with later observations.
- On this machine, Docker's client was present on 5 November 2026 but the
  `docker compose` plugin was unavailable. The relocated Docker setup has
  therefore not yet been built here.

## Decision log

| When | Decision or completed work | Why it matters |
| --- | --- | --- |
| August 2026 case | Saved IFS versus ERA5T fields and metrics for 20 August, 00:00 and 12:00 UTC | Provides a worked model verification example |
| October 2026 | Added Docker jobs for ERA5 collection, ML backtest, and IFS verification | Makes the workflows portable and keeps data on the host |
| October 2026 | Calculated a UK land only comparison from the saved NetCDF | Separates UK land results from the wider rectangular grid |
| November 2026 | Removed unrelated exploratory exercises and grouped Docker files under `docker/` | Keeps the repository focused and easier to revisit |

The personal Codex skill `containerize-repository` is installed outside this
Git repository in `~/.codex/skills/`. It instructs Codex how to inspect and
containerise other repositories; the Docker files here are this project's
concrete implementation.
