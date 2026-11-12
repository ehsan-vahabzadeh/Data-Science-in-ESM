# Learning notebook: UK weather forecast correction

**Last updated:** 11 November 2026. Start here when returning to the project. This living file explains the science, data, decisions, results and open questions for the current project. The [README](README.md) is the short project overview; [data access history](docs/data-access-history.md) records how the data was obtained. Update this file whenever the project meaningfully changes.

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

We downloaded two TIGGE GRIB files in the Git-ignored `data/tigge/` directory. Their forecast initialization dates cover **1 March 2024 through 28 February 2026**, with one 12:00 UTC run per day and +12, +18, +24 and +30-hour leads. On 10 November 2026, a further forecast file covering initializations **1 March–8 November 2026** and a 2026 +36-hour solar file were downloaded and checksum-verified. The main 2026 file had all 5,060 expected fields and no encoded missing or non-finite values; tiny cloud-cover overshoots and negative solar increments remain flagged. Files and credentials are local and are not committed.

ERA5 collection completed for the requested period from 1 January 2024 to 5 November 2026, with wind components at 00, 06, 12 and 18 UTC and hourly net solar radiation for later interval matching. On 11 November, all 70 monthly batches were marked downloaded and their local sizes and MD5 checksums matched the manifest. The earlier 2–3 March 2024 sample is separate. The files and resumable manifest are under `data/era5/monthly/`. Download integrity does not establish complete GRIB coverage or scientific validity; recent ERA5T is preliminary and may be revised.

On 10 November 2026 a macOS user job named `org.weather-forecast.era5-collection` was started to collect the monthly batches while the Mac remains awake and online. On 11 November, it stopped at 23 of 70 batches: Copernicus returned a valid December 2024 solar file with an MD5 checksum missing a leading zero, which our collector incorrectly rejected. The checksum comparison was corrected and tested; the restarted collection subsequently completed all 70 batches. Old `collector-error.log` lines can contain historical errors. The replacement was configured as a one-time job, without automatic restart on failure, logout or reboot.

For the daily 2024–2025 comparison, we additionally downloaded `early-2024.grib` for missing wind/solar forecasts and `solar-2024.grib` and `solar-2025.grib` for the +36-hour solar endpoints. These supplementary fields make full-calendar-year daily wind samples and full-day solar averages possible; they do not provide two full years of every variable.

The forecasts use a requested **0.5° grid** covering 48–62°N and 12°W–4°E: 957 grid points in a rectangle that also includes non-UK areas. The retained approximate land/maritime mask selects 519 of these points: 134 onshore and 385 offshore. It is a research mask, not a legal boundary; the other mask points fall outside our downloaded rectangle. The output grid is not necessarily the model's native grid. A one-run 0.25° sample was also requested; that does not prove all of the finer detail is independent or establish native historical resolution.

| Variable | What it means | Unit / handling |
| --- | --- | --- |
| `10u`, `10v` | East–west and north–south wind components at 10 m | m/s. Components can be negative. Wind speed is `sqrt(10u² + 10v²)` and is nonnegative. This is not 100 m turbine-hub wind. |
| `2t` | Air temperature at 2 m | Kelvin; subtract 273.15 for °C. |
| `tcc` | Total cloud cover | Percent in these files; nominally 0–100%. |
| `ssr` | Surface **net** solar radiation | J/m² accumulated from forecast start in these TIGGE files. Net means incoming minus reflected sunlight; it is not the same as downward irradiance or solar power. |

For an interval, subtract the earlier forecast accumulation from the later one and divide by the number of seconds to obtain mean W/m². ERA5's hourly accumulation convention differs: sum the matching hourly intervals first. Matching the correct quantity, unit, coordinates, run and valid interval is essential. The two-day comparison uses six-hour windows ending at 06, 12 and 18 UTC.

The existing 2026 +36-hour solar supplement begins with the 1 January initialization, so it does not include the endpoint from 31 December 2025 needed for the full 1 January 2026 daily interval. We also have not collected +6-hour solar accumulations for all runs, which are needed to form the six-hour interval ending at the +12-hour forecast. Do not treat the future solar modelling dataset as complete until these boundaries are resolved.

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

### Daily wind and solar variability across 2024 and 2025

The [relative-difference plot](outputs/wind-variability/daily-absolute-relative-difference.png) matches each calendar date in 2024 with the same date in 2025 and plots `100 × |2025 − 2024| / 2024`, separately for onshore and offshore. It is a year-on-year weather difference, **not forecast error or a measure of uncertainty**. A 2024 reference below 1 m/s for wind or 20 W/m² for solar is excluded to avoid unstable percentages; 29 February has no 2025 match and is omitted. Solar gaps are therefore expected.

Daily wind is the average of four forecast speeds at 00, 06, 12 and 18 UTC across 134 onshore or 385 offshore 0.5° grid points. Solar is the full 24-hour net radiation mean from the difference between +36 and +12 hour accumulations of the preceding day's 12 UTC run. Grid points are equally weighted, not area weighted. These values are forecasts, not measured weather or power.

The [wind distribution plot](outputs/wind-variability/wind-daily-distributions.png) shows normalised histograms for the daily **regional mean**, not for an individual farm. Over the full calendar years, the median wind speed was 4.24 m/s onshore and 8.30 m/s offshore in 2024, and 4.05 m/s onshore and 7.82 m/s offshore in 2025. Population variance across daily regional means was 2.41 and 5.80 (m/s)² in 2024, and 2.13 and 5.73 (m/s)² in 2025, onshore and offshore respectively. These do not establish predictability: this requires forecasts compared with matched later reference data at specified lead times. Nearby cells and days are correlated.

The generated regional daily data and statistics are stored under `outputs/wind-variability/`. Reproduce with:

```bash
python -m scripts.daily_year_comparison data/tigge/early-2024.grib data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib data/tigge/solar-2024.grib data/tigge/solar-2025.grib --output outputs/wind-variability
```

Two earlier ERA5 comparison maps and a two-day bias exercise are described in the [access history](docs/data-access-history.md). They demonstrate the workflow only; a two-day retrospective result is not evidence of general performance.

## 6. What is bias correction and where does ML fit?

Bias is a systematic tendency for forecasts to differ from the reference. One simple **additive mean adjustment** estimates the average `ERA5 − forecast` on historical training data and adds it to future forecasts. Our single-day global-offset demonstration made the following day worse and used ERA5 that would not have been available at that next forecast's initialization. It is not a valid operational backtest and does not disprove bias correction.

More useful methods can estimate biases by location, lead or season, use trailing or exponentially weighted past errors, or adjust distributions. A linear regression can itself learn a bias/error correction, so a separate bias stage is optional. For the first experiment, compare the linear models directly with the raw forecasts on the same later held-out cases; do not include a mean-bias baseline. Fit all learned preprocessing on training data only; never use same-valid-time ERA5 as a predictor. Solar needs physically appropriate daylight/nighttime treatment.

**Experiment split:** train on valid dates 1 January 2024–30 June 2025, validate on 1 July–31 December 2025, and test on available 2026 valid dates. The 2026 results have now been inspected. Keep all locations for a valid day in the same split and preserve initialization/valid times. Temperature and cloud are missing for January–February 2024. The user also requested season; derive season information from the valid date and select its encoding using validation rather than assuming one representation improves the model. All fitted transforms and feature decisions use training/validation only. Forecast availability and the separate solar target remain to be settled before fitting.

**Agreed first experiment:** start with 10 m wind and fit one shared pair of fixed linear models across selected onshore and offshore locations once on the first 18 months; report the two regions separately and explore expanding-window retraining later. Predict the east–west and north–south wind component errors separately (`ERA5 − IFS`), add each correction to its forecast component, then derive wind speed and direction. Chosen candidate inputs are forecast speed and components, lead time, location, land/sea and season, subject to verified coverage. Compare categorical seasons with a sine/cosine annual cycle on the validation period and select by overall wind-speed MAE before testing. Train on available matched cases and report gaps and coverage by split rather than silently dropping them. Compare directly with the raw forecast, without a mean-bias baseline, using wind-speed MAE and RMSE, component errors and signed bias. Weight each matched grid-point and forecast-time case equally; this gives more total weight to the more numerous offshore points. This is a retrospective comparison with ERA5, not a demonstrated operational backtest; recent data may be preliminary ERA5T. The existing region mask is approximate, not an official maritime boundary, and needs verification against the requested UK area. Solar remains in scope after its accumulation intervals have been resolved. See [time-series training research](docs/time-series-training-research.md) for fixed versus expanding windows and reference-data availability.

**Provisional validation, 11 November 2026:** the wind pipeline matched all requested six-hourly valid times from 1 January 2024 to 5 November 2026, using coordinates rounded to four decimal degrees and 519 points selected by the approximate mask. It found no missing wind fields at the timestamp level and rejected missing or non-finite field values. On July–December 2025, cyclic season encoding gave overall wind-speed MAE 0.750 m/s versus 0.756 m/s for raw IFS. Onshore it increased from 0.701 to 0.706 m/s; offshore it decreased from 0.774 to 0.766 m/s. These are validation results against ERA5, not independent verification or final test results; correlated grid points mean the apparent sample size does not establish statistical significance. Obtain and verify an official UK maritime mask before interpreting results as covering official UK waters. The [UK Hydrographic Office](https://www.gov.uk/guidance/uk-maritime-limits-and-law-of-the-sea) provides maritime limit data; the execution environment could not resolve its data service. The command and report location are in the README.

**Provisional test, 12 November 2026:** at the user's request the already selected model was evaluated on the 2026 period using the same approximate mask. Raw versus corrected wind-speed MAE was 0.757 versus 0.760 m/s; RMSE was 1.039 versus 1.036 m/s, and R² was 0.9278 versus 0.9283. The result does not establish skill against independent measurements or for the official UK maritime area. The 2026 score has now been viewed: if it influences future model choices, a different untouched test period is needed for an unbiased final assessment. The plot and report are under `outputs/wind-regression/`.

The predicted-versus-reference figure `outputs/wind-regression/predicted-vs-era5.png` shows the corrected forecast against ERA5 for training, validation and test. The diagonal represents perfect agreement. The points are a reproducible sample for readability; R² and RMSE use all matched cases. ERA5 is a reanalysis reference, not direct ground truth.

**Model review:** This is ordinary least-squares regression for the east–west and north–south component errors, not an hourly time-series model. It uses forecast variables and calendar/location inputs but no past-error history. Additive linear terms cannot directly learn interactions such as a wind-dependent coastal effect unless those features are explicitly provided. Wind at 10 m is not turbine-hub wind; six-hour snapshots miss intra-hour changes; the approximate mask and equal grid-point weighting constrain the geographic interpretation. Training minimizes squared component errors, whereas selection uses wind-speed MAE, so improving the former does not guarantee improvement in speed. ERA5 is not an independent observation, and the inspected 2026 test cannot be reused as an untouched final test after tuning to it. Compare raw and corrected errors by lead, season and region, with time-blocked uncertainty intervals, before interpreting small differences as skill.

The matching code rounds coordinates to four decimal degrees; it does not perform an exact-bitwise match or interpolate. It now rejects duplicate rounded ERA5 coordinates, duplicate mask entries and unrecognised region labels. The mask remains incomplete by design relative to the surrounding rectangle; excluded points have not been proven to match official UK waters. The existing provisional-mask warning is based on a filename and can be bypassed by renaming a mask, so a filename or an absent warning is not evidence of geographic verification.

## 7. What should we inspect next, and can clustering help?

First, investigate the flagged cloud and solar values without automatically deleting unusual weather; check extrema by date, location and lead, plus daylight and coast/sea cases. Audit forecast-to-ERA5 matching, missingness and physical bounds before analysing errors by season, lead, time of day and onshore/offshore. Report signed bias, MAE and RMSE alongside carefully masked percentage errors. Spatially adjacent values and adjacent times are correlated; thousands of grid values are not thousands of independent storms.

**Clustering** groups similar examples, such as windy/cloudy or calm/clear forecast conditions. It may help explore whether forecast errors differ between weather regimes. It does not itself correct a forecast or prove unusual data is wrong. Results depend on selected variables, scaling and the number of clusters. If used for prediction, fit scaling and cluster definitions on the training period only and use forecast-available inputs. Two ERA5 days are insufficient to evaluate seasonal error clusters; clustering has not yet been run. See [weather data quality research](docs/weather-data-quality-research.md) and [bias-adjustment research](docs/weather-forecast-bias-adjustment.md).

## 8. Aurora: a weather foundation model

Microsoft's Aurora predicts future atmospheric fields from global weather states. Its original weather model uses surface temperature, the two horizontal 10 m wind components and mean sea-level pressure; temperature, wind components, humidity and geopotential at 13 atmospheric pressure levels; and static land, soil and elevation information. Aurora 1.5 expands the surface inputs to include 100 m wind, dew point, cloud cover, soil conditions and other fields. Its solar radiation and precipitation fields are outputs, not required surface inputs. The exact inputs depend on the model version. [Microsoft's model documentation](https://github.com/microsoft/aurora/blob/main/docs/models.md) lists them.

Aurora combines a Perceiver encoder, a 3D Swin Transformer U-Net and a Perceiver decoder. The U-Net processes the weather representation at different spatial scales: it compresses it, processes the broader patterns, and expands it again, combining information from corresponding scales through skip connections. Shifted-window attention allows neighbouring regions to exchange information. The Perceiver components convert between physical weather fields and the internal representation. See the [Aurora research paper](https://www.nature.com/articles/s41586-025-09005-y) and its [architecture supplement](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/05/Aurora__A_Foundation_Model_of_the_Atmosphere.pdf).

Our proposed first model has a different purpose: it learns to adjust an existing IFS forecast towards ERA5 over the UK, rather than generating a global forecast from an atmospheric state. Our limited UK dataset alone is not the full global, multi-level input required by the standard Aurora checkpoints.

## 9. Reproduce the audit

Install `numpy`, `eccodes`, `matplotlib` and `cartopy` in a Python environment; the current minimal Docker setup does not include this workflow. With local source files present, run:

```bash
python -m scripts.audit_tigge data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib --start 2024-03-01 --end 2026-02-28 --output outputs/data-audit/tigge-2024-2026.json
python -m scripts.explore_tigge data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib --output outputs/data-audit/tigge-monthly-conditions.png
python -m unittest discover -s tests
```

The next substantial data step is to obtain and audit a longer matching ERA5 period, including the correct six-hour solar intervals. Establish chronological training, validation and final test periods, preserve forecast/reanalysis availability timing, and then evaluate bias corrections and ML models without future-data leakage.
