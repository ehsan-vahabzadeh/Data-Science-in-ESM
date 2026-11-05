# UK wind and solar weather forecasting

This repository collects UK weather data, tests a historical machine learning
forecast, and compares an ECMWF weather forecast with ERA5T. The current models
predict **weather at wind and solar farm locations**, not electricity output.

Start with [PROJECT_GUIDE.md](PROJECT_GUIDE.md) when returning to the project.
It explains the goal, models, data, concepts, completed work, results, limits,
and next steps.

## Main files

| File | Purpose |
| --- | --- |
| `UKWeather.py` | Download a UK ERA5 cutout and draw a daily weather map |
| `UKDayAheadWeatherML.py` | Train and evaluate wind and solar weather models |
| `ECMWFForecastVerification.py` | Compare IFS forecasts with ERA5T |
| `REPD_Publication_Q2_2026.csv` | Farm locations, technologies, and capacities |
| `UKWindFarmConfigurations_initial.csv` | Preliminary turbine configuration research |
| `UK_DAY_AHEAD_WEATHER.md` | Detailed ML experiment and evaluation notes |
| `ECMWF_NWP_VERIFICATION.md` | Detailed forecast comparison notes |
| `docker/` | Docker image, Compose commands, dependency files, and run guide |

The saved August 2026 comparison is in `outputs/ecmwf-verification/`, with its
one-day ERA5T source file in the repository root. Local downloads belong in
`data/`; new generated results belong in `outputs/container/`. See
[docker/README.md](docker/README.md) for prerequisites and commands.
