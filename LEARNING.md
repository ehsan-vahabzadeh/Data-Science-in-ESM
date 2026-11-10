# Learning notebook: UK weather forecast correction

**Last updated:** 10 November 2026. Start here when returning to the project. This living file explains the science, data, decisions, results and open questions for the current project. The [README](README.md) is the short project overview; [data access history](docs/data-access-history.md) records how the data was obtained. Update this file whenever the project meaningfully changes.

## 1. What are we trying to do?

We want to investigate whether a simple correction can make UK wind and solar **weather forecasts** agree more closely with a historical reference. Start with understandable statistical baselines, then compare linear models and only later consider more complex ML. The longer-term aim is renewable electricity and energy storage, potentially including power-market decisions. Weather forecasts are not themselves predictions of farm output or market price.

The proposed prediction chain is:

```text
Earlier IFS forecast + context → correction method → adjusted weather forecast
                                          ↓
                            compare against later ERA5
```

A useful correction must outperform the raw forecast on the same, previously unseen dates. Improving agreement with ERA5 alone does not prove a forecast is better against independent measurements or that it improves storage decisions.

## 2. The physical weather model and our reference

**ECMWF** is the European Centre for Medium-Range Weather Forecasts. Its **Integrated Forecasting System (IFS)** is a numerical weather prediction system that predicts weather from an estimated initial state. It evolves the atmosphere using mathematical descriptions of physical processes. Our forecast source is **TIGGE**, an archive with ensemble forecasts from different weather centres; we selected ECMWF's control forecast. An ensemble is a set of plausible forecasts; the control is one member, not the mean of all members.

**ERA5** is an ECMWF reanalysis: it combines a weather model with historical observations to estimate past weather consistently. It is a useful gridded reference, not a perfect measurement or a fully independent forecast. Later, actual station and farm observations would provide another assessment.

An IFS forecast has an **initialization time** (when its starting atmospheric state is defined), a **lead time** (how far ahead it predicts) and a **valid time** (the weather time it predicts):

```text
valid time = initialization time + lead time
```

For example, the 12:00 UTC forecast on 1 March at +24 hours predicts 12:00 UTC on 2 March. Forecast production and delivery take time; initialization is not necessarily the moment the forecast was available to a user. TIGGE has a 48-hour release delay, which is suitable for retrospective analysis but requires a separate timely source for a real-time day-ahead application.

## 3. What data do we have?

We downloaded two TIGGE GRIB files in the Git-ignored `data/tigge/` directory. Their forecast initialization dates cover **1 March 2024 through 28 February 2026**, with one 12:00 UTC run per day and +12, +18, +24 and +30-hour leads. The last valid times extend into March 2026. Two CDS ERA5 days are available locally for **2–3 March 2024**, not the whole two-year period. Files and credentials are local and are not committed.

The forecasts use a requested **0.5° grid** covering 48–62°N and 12°W–4°E: 957 grid points in a rectangle that also includes non-UK areas. The retained approximate land/maritime mask selects 519 of these points: 134 onshore and 385 offshore. It is a research mask, not a legal boundary; the other mask points fall outside our downloaded rectangle. The output grid is not necessarily the model's native grid. A one-run 0.25° sample was also requested; that does not prove all of the finer detail is independent or establish native historical resolution.

| Variable | What it means | Unit / handling |
| --- | --- | --- |
| `10u`, `10v` | East–west and north–south wind components at 10 m | m/s. Components can be negative. Wind speed is `sqrt(10u² + 10v²)` and is nonnegative. This is not 100 m turbine-hub wind. |
| `2t` | Air temperature at 2 m | Kelvin; subtract 273.15 for °C. |
| `tcc` | Total cloud cover | Percent in these files; nominally 0–100%. |
| `ssr` | Surface **net** solar radiation | J/m² accumulated from forecast start in these TIGGE files. Net means incoming minus reflected sunlight; it is not the same as downward irradiance or solar power. |

For an interval, subtract the earlier forecast accumulation from the later one and divide by the number of seconds to obtain mean W/m². ERA5's hourly accumulation convention differs: sum the matching hourly intervals first. Matching the correct quantity, unit, coordinates, run and valid interval is essential. The two-day comparison uses six-hour windows ending at 06, 12 and 18 UTC.

## 4. How we got here

Direct access to ECMWF's restricted MARS service was unavailable. Open-Meteo was explored and later removed after its point-based access and free-tier limitations made the intended large collection slow. NCAR GDEX was explored as another archive; a small subset request was submitted. WeatherBench 2 was considered but not established as the project's retrieval workflow. We chose TIGGE because its archive gives programmatic access to historical ECMWF ensemble forecasts and longer lead times, accepting the trade-offs in variables and time resolution. See the [detailed access history](docs/data-access-history.md) for job details and caveats.

## 5. What data analysis has been done?

On 10 November 2026, the two full TIGGE files were audited across the entire rectangle, not only UK points. The audit checked requested dates, initialization times, variables, leads, duplicate keys, valid-time arithmetic, units, grid consistency, encoded missing values, non-finite values and basic ranges:

- **14,600 expected GRIB messages and 14,600 found**, with no missing combinations, duplicates or unexpected combinations.
- Each of five variables contains **2,794,440 values**; no encoded missing or non-finite values were detected.
- Cloud cover had **183,689 values (6.57%) slightly above 100%**, with a maximum of 100.00098%. None exceeded the audit's ±0.01 percentage-point tolerance. These are physically out of bounds but very small; interpolation or packing is a possible explanation, not a confirmed cause. We did not change the source values.
- There were **15,136 negative six-hour differences (0.72%)** among 2,095,830 successive solar accumulation comparisons. The largest decrease was 542.7 J/m², equivalent to about 0.025 W/m² over six hours. Such decreases warrant investigation; rounding or encoding is possible but unconfirmed. No values were silently clipped.
- ERA5's two-day sample contained 36 valid hourly times for each of 10 m u wind, v wind and net solar radiation, with no encoded missing or non-finite values found. This limited check is not a full multi-year ERA5 audit.

These checks do **not** prove every value is correct, identify the cause of anomalies, or validate wind and solar against observations. The complete machine-readable result is `outputs/data-audit/tigge-2024-2026.json`; the generated [monthly conditions figure](outputs/data-audit/tigge-monthly-conditions.png) compares onshore and offshore averages of forecast wind, temperature and cloud cover. It groups by initialization month and equally weights selected grid points and lead times; nearby grid points are correlated and it is not area-weighted. The plot describes forecasts, not measured weather or forecast errors.

Two earlier ERA5 comparison maps and a two-day bias exercise are described in the [access history](docs/data-access-history.md). They demonstrate the workflow only; a two-day retrospective result is not evidence of general performance.

## 6. What is bias correction and where does ML fit?

Bias is a systematic tendency for forecasts to differ from the reference. One simple **additive mean adjustment** estimates the average `ERA5 − forecast` on historical training data and adds it to future forecasts. Our single-day global-offset demonstration made the following day worse and used ERA5 that would not have been available at that next forecast's initialization. It is not a valid operational backtest and does not disprove bias correction.

More useful methods can estimate biases by location, lead or season, use trailing or exponentially weighted past errors, or adjust distributions. A linear regression can itself learn a bias/error correction, so a separate bias stage is optional. We will compare raw forecasts, simple bias baselines and then linear models on the same later held-out data. Fit all learned preprocessing on training data only; never use same-valid-time ERA5 as a predictor. Solar needs physically appropriate daylight/nighttime treatment.

## 7. What should we inspect next, and can clustering help?

First, investigate the flagged cloud and solar values without automatically deleting unusual weather; check extrema by date, location and lead, plus daylight and coast/sea cases. Audit forecast-to-ERA5 matching, missingness and physical bounds before analysing errors by season, lead, time of day and onshore/offshore. Report signed bias, MAE and RMSE alongside carefully masked percentage errors. Spatially adjacent values and adjacent times are correlated; thousands of grid values are not thousands of independent storms.

**Clustering** groups similar examples, such as windy/cloudy or calm/clear forecast conditions. It may help explore whether forecast errors differ between weather regimes. It does not itself correct a forecast or prove unusual data is wrong. Results depend on selected variables, scaling and the number of clusters. If used for prediction, fit scaling and cluster definitions on the training period only and use forecast-available inputs. Two ERA5 days are insufficient to evaluate seasonal error clusters; clustering has not yet been run. See [weather data quality research](docs/weather-data-quality-research.md) and [bias-adjustment research](docs/weather-forecast-bias-adjustment.md).

## 8. Reproduce the audit

Install `numpy`, `eccodes`, `matplotlib` and `cartopy` in a Python environment; the current minimal Docker setup does not include this workflow. With local source files present, run:

```bash
python -m scripts.audit_tigge data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib --start 2024-03-01 --end 2026-02-28 --output outputs/data-audit/tigge-2024-2026.json
python -m scripts.explore_tigge data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib --output outputs/data-audit/tigge-monthly-conditions.png
python -m unittest discover -s tests
```

The next substantial data step is to obtain and audit a longer matching ERA5 period, including the correct six-hour solar intervals. Establish chronological training, validation and final test periods, preserve forecast/reanalysis availability timing, and then evaluate bias corrections and ML models without future-data leakage.
