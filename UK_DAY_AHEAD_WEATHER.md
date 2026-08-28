# UK farm-level day-ahead weather forecasting

## What this experiment predicts

This stage predicts weather at the ERA5 grid cell nearest each operational
farm. It does **not** predict electricity yet.

| Fleet | Hourly target | Unit | Later energy conversion |
|---|---|---|---|
| Wind | 100 m wind speed | m/s | hub-height adjustment, turbine power curve, losses |
| Solar | direct + diffuse surface irradiance | W/m² | panel geometry, PV model, temperature, inverter/losses |

Several farms can occupy the same 0.25° ERA5 cell. Those farms receive the
same weather prediction at this stage, but will produce different power later
because their capacity, equipment, orientation, and losses differ.

## The important data distinction

- **ERA5** is a historical reanalysis. It is excellent for learning, training,
  and backtesting, but it is not tomorrow's forecast.
- **ECMWF IFS/AIFS or Met Office forecast data** supplies future weather for an
  operational day-ahead run.
- **REPD** supplies farm names, technologies, capacities, and coordinates. It
  does not supply hourly weather or complete operational telemetry.
- **SCADA/meters or site weather stations**, when available, provide the best
  site-specific observations for bias correction and eventual production
  modelling.

The included script is therefore a historical backtest. It asks: “If only
older ERA5 values had been known, how well could a simple ML model predict a
later day that we deliberately hid?”

## Current model design

`UKDayAheadWeatherML.py` trains two independent
`HistGradientBoostingRegressor` models. A single model is trained across the
unique wind-farm grid cells and another across the unique solar-farm cells.
This is more data-efficient than trying to train thousands of farm models.

Inputs shared by both models are:

- the target observed 24, 48, and 168 hours earlier;
- hour-of-day and day-of-year represented as circular sine/cosine values;
- grid-cell longitude and latitude.

The wind model can also use the previous day's wind direction and surface
roughness. The solar model uses deterministic top-of-atmosphere radiation and
solar altitude. It predicts total downward surface irradiance:

```text
surface irradiance = influx_direct + influx_diffuse
```

The forecast is treated as issued at 23:00 UTC on the preceding day. That is
why every 24-hour lag needed for the following day is already available. If a
real market forecast must be issued earlier, such as noon, the feature cutoff
must be moved earlier and an NWP forecast should be the main input.

## Leakage-safe evaluation

The final 30 days are held out by default. The model trains only on preceding
dates and is evaluated on those later dates. A random train/test split would
mix neighbouring weather hours between training and testing and make the score
look unrealistically good.

Two predictions are compared:

1. ML forecast;
2. persistence baseline: the value at the same hour yesterday.

The main metrics are:

- **MAE:** average absolute error in m/s or W/m²; lower is better;
- **RMSE:** penalises large errors more heavily; lower is better;
- **R²:** one measure of explained variation; higher is better;
- **skill versus persistence:** positive means ML beats yesterday's value.

Solar metrics are calculated only in daylight (`influx_toa > 20 W/m²`) so
easy all-zero night hours do not inflate apparent performance.

## Run the experiment

First, `UKWeather.py` is configured to retrieve the continuous hourly period
from 2 January 2025 through 2 January 2026. The final midnight is required for
the last solar accumulation interval.

```bash
python UKWeather.py
```

This needs valid CDS credentials and accepted ERA5 licence terms. A year for
the full UK grid is a substantial download and can take time.

Then run the backtest:

```bash
python UKDayAheadWeatherML.py \
  --cutout uk-era5-2025-01-02-to-2026-01-02.nc \
  --forecast-day 2026-01-01 \
  --test-days 30
```

The output directory is `outputs/day-ahead-weather/` and contains:

- `wind_farm_weather_forecast.csv` — 24 rows per wind farm;
- `solar_farm_weather_forecast.csv` — 24 rows per solar farm;
- `backtest_metrics.json` — ML and persistence scores;
- `farm_weather_forecast_maps.png` — daily mean predictions at farm locations.

The CSVs retain the held-out ERA5 value beside each prediction so individual
hours and farms can be inspected. For solar, timestamps are interval-ending:
01:00 represents 00:00–01:00, and the next midnight represents 23:00–00:00.

## Moving from the lesson to a real forecast

A practical pipeline normally uses numerical weather prediction first and ML
second:

```text
latest ECMWF/Met Office run
        ↓
forecast u/v wind, radiation, clouds, temperature at each farm
        ↓
ML bias correction trained on archived forecasts versus observations
        ↓
corrected hourly weather plus uncertainty
        ↓
turbine/PV conversion model
        ↓
farm generation forecast
```

Useful NWP predictors include 100 m `u` and `v` wind components, short-wave
radiation, cloud cover, 2 m temperature, pressure, and precipitation. For the
production version, train on **archived forecasts as they were issued**, not
only ERA5 analyses. Otherwise the model has not learned the actual errors made
by a day-ahead weather forecast.

Start with gradient-boosted trees and a persistence/NWP baseline before trying
LSTMs or transformers. More complex sequence models need much more data and do
not automatically improve an operational forecast. The next useful extension
is probabilistic output (for example P10/P50/P90), because a single number
hides the large uncertainty in wind ramps and cloud movement.

Official starting points:

- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)
- [ECMWF forecast access](https://www.ecmwf.int/en/forecasts/accessing-forecasts)
- [Met Office Weather DataHub](https://datahub.metoffice.gov.uk/)
- [Copernicus ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)

