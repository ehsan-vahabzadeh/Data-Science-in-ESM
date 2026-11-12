# UK wind and solar forecast research

This project explores whether simple machine learning can improve **UK wind and solar weather forecasts**. The current experiment uses ECMWF IFS forecasts from TIGGE and plans to compare them with ERA5 as a historical reference. The long-term aim is to connect weather forecasts to renewable generation and, later, electricity-market questions.

New to the project or returning after a break? Read [LEARNING.md](LEARNING.md) for the science, data, decisions and current results.

## Project targets

🟢 **Done** · 🟡 **Under way** · ⚪ **Planned**

| Status | Target by the end of the project | Current position |
| --- | --- | --- |
| 🟢 | Obtain multi-year TIGGE forecasts and ERA5 reference data | Requested files were downloaded and their transfer checksums verified; the data are six-hourly for TIGGE and cover a UK-area rectangle. |
| 🟡 | Match and audit a multi-year UK land and offshore wind/solar dataset | TIGGE underwent an initial audit; full ERA5 checks, matching and solar-interval checks remain. |
| 🟡 | Build understandable wind and solar correction models | A wind regression was trained and provisionally tested; official boundary verification and solar remain. |
| ⚪ | Test whether more complex models improve on the simple models | Planned: compare random forests or gradient-boosted trees using the same inputs and time splits. |
| ⚪ | Verify performance and generalisation | Planned: chronological train/validation/test splits, seasonal and lead-time results, and separate onshore/offshore evaluation. |
| ⚪ | Check forecasts against independent measurements | Investigate UK station wind data, including 10 m observations; offshore and solar observation sources still need research. |
| ⚪ | Explore renewable generation and power-market applications | A later stage: weather variables alone are not power or energy forecasts. |

## Current position

**TIGGE is the chosen source for the next experiment.** We requested two years of ECMWF ensemble control forecasts over a UK and surrounding-seas bounding box on a 0.5° grid, for the 12 UTC run at +12, +18, +24 and +30 hours. The requested fields are 10 m wind components, 2 m temperature, total cloud cover and surface net solar radiation. These six-hourly samples do not cover every hour, and the rectangle includes non-UK areas. They are not the former 100 m wind and downward solar design.

The original two-year files and additional 2026 TIGGE forecasts were downloaded under `data/tigge/` with matching checksums. Initial audits found all requested fields and no missing values; tiny cloud-cover overshoots and negative solar increments need investigation. Monthly ERA5 wind and solar requests from January 2024 through 5 November 2026 have downloaded under `data/era5/monthly/`. See [LEARNING.md](LEARNING.md) for findings and next checks.

## Data and scientific background

- **IFS** is ECMWF's numerical weather prediction model: it issues forecasts before the weather occurs. TIGGE archives ensemble forecasts from multiple centres, including ECMWF; the current request uses ECMWF's control forecast.
- **ERA5** is ECMWF's historical reanalysis, combining observations and modelling. It is a useful reference but is not an independent farm sensor or perfect ground truth.
- An IFS forecast has an initialization time and a lead time, giving the **valid time** being forecast. The run's initialization is not necessarily its public availability time.
- Wind components are forecast at a valid time. TIGGE net solar radiation is accumulated and differs from incoming downward solar radiation; compare like quantities over matching intervals and verify units and step metadata.
- IFS and ERA5 may select different grid centres. Their recorded distance is a source of uncertainty in the comparison.
- Some historical IFS runs are described as hindcasts; their provenance and model-cycle changes need assessment before claiming an as-issued operational backtest.

## Proposed modelling approach

Start with one shared pair of fixed linear models trained across onshore and offshore points on January 2024–June 2025, validate on July–December 2025, and reserve 2026 for testing. Predict the 10 m east–west and north–south wind component errors separately (`ERA5 − IFS`), add the corrections to the IFS components, and derive corrected wind speed and direction. Proposed inputs are forecast wind speed and components, lead time, location, land/sea and season, subject to verified coverage. Compare directly against the raw IFS forecast on the same cases, and report onshore and offshore results separately. A later experiment can investigate expanding-window retraining. Fit preprocessing on training data only, and never use same-valid-time ERA5 as a predictor.

Solar remains a separate later model: first establish compatible accumulation intervals and address missing endpoints. Net solar radiation is not the same as downward solar irradiance.

A first mean-bias demonstration fits one wind offset and one solar offset on 2 March 2024 and evaluates on 3 March. On the 519 UK-grid points available within the downloaded rectangle, adjusted MAE was worse than the raw forecast for both variables. This is a retrospective two-day plumbing check, not a reliable estimate of model skill: ERA5 for the training day was not available by the following forecast initialization. The result and reproducible command are recorded in [the data-access history](docs/data-access-history.md#two-day-bias-adjustment-demonstration).

Weight each matched grid-point and forecast-time case equally, and report wind-speed MAE and RMSE, component errors and signed bias against the raw forecast, including separate onshore and offshore results. Compare categorical seasons and a smooth annual cycle on validation, select by overall wind-speed MAE, then test on 2026. Train on available matched cases and report gaps and coverage for each split. This is a retrospective comparison, not a demonstrated operational backtest. The current regional mask is approximate, not an official maritime boundary, and needs verification against the requested UK area. For solar report both daylight and all-hour scores. Test later dates and seasons without leaking future information; improving agreement with ERA5 alone does not establish improved real-world skill. The existing [forecast postprocessing research](docs/forecast-postprocessing-models.md) explains model options and published examples.

## Run and test

The multi-year wind workflow is provisional; a corresponding solar matching workflow has not yet been implemented. The [Docker setup](docker/README.md) is a minimal Python environment and does not yet download or process TIGGE data.

The first wind-only workflow matches instantaneous TIGGE and ERA5 wind by UTC valid time and coordinates rounded to four decimal degrees, reports missing fields, and fits two linear component-error models. It checks wind units, step type and missing values. The current mask is approximate, so results must not be presented as the official UK maritime experiment. This command reproduces the validation-only run:

```bash
python -m scripts.wind_regression --forecast data/tigge/early-2024.grib data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib data/tigge/forecast-2026.grib --era5 data/era5/monthly/*-wind.grib --grid config/uk-land-and-eez-0.5deg.csv --provisional-mask --validation-only --output outputs/wind-regression/validation.json
```

Install `numpy` and `eccodes` for this command. On the approximate mask, the 2025 validation selected the cyclic season model: wind-speed MAE was 0.756 m/s raw and 0.750 m/s corrected overall, 0.701 and 0.706 onshore, and 0.774 and 0.766 offshore. On request, a provisional 2026 test was then scored: raw versus corrected MAE was 0.757 versus 0.760 m/s and RMSE was 1.039 versus 1.036 m/s. See `outputs/wind-regression/performance.png` and `provisional-test.json`. These values compare with ERA5, not independent observations. Because the 2026 scores have been inspected, they are no longer an untouched test set for future model decisions. UK maritime data are available from the [UK Hydrographic Office](https://www.gov.uk/guidance/uk-maritime-limits-and-law-of-the-sea); the boundary still needs to be obtained and checked against the mask.

To reproduce the provisional 2026 scores, use the command above with `--provisional-test` in place of `--validation-only` and a different output path. Run `python -m scripts.plot_wind_performance outputs/wind-regression/provisional-test.json --output outputs/wind-regression/performance.png` to plot them (requires `matplotlib`).

For corrected wind versus ERA5 scatter plots, run:

```bash
python -m scripts.plot_wind_scatter --forecast data/tigge/early-2024.grib data/tigge/2024-03-01_to_2025-02-28.grib data/tigge/2025-03-01_to_2026-02-28.grib data/tigge/forecast-2026.grib --era5 data/era5/monthly/*-wind.grib --grid config/uk-land-and-eez-0.5deg.csv --report outputs/wind-regression/provisional-test.json --output outputs/wind-regression/predicted-vs-era5.png
```

The points are sampled for readability; the displayed RMSE and R² use all matched cases. ERA5 is a reanalysis reference, not direct measurements.

The resumable ERA5 collector uses `cdsapi` and `requests`. It fetches monthly UK-area GRIB batches, writes a local manifest and checks download sizes and checksums. The collection through 5 November 2026 completed; inspect `data/era5/monthly/manifest.json` or `data/era5/monthly/collector.log` for its status. To resume the same request if needed, run:

```bash
python -m scripts.collect_era5 --end 2026-11-05 --output data/era5/monthly
```

The collector's lock prevents another instance using that output folder. It does not validate all GRIB data or automatically restart after logout or reboot; credentials must be configured locally first. A separate 5 November wind sample was confirmed available; see [LEARNING.md](LEARNING.md).

An initial two-day comparison on 2–3 March 2024 produced maps under `outputs/tigge-era5-comparison/`. The `scripts/compare_tigge_era5.py` script requires Python packages `eccodes`, `numpy`, `matplotlib` and `cartopy`, plus matching ERA5 GRIB files. It compares 10 m wind and six-hour mean net solar radiation ending at 06, 12 and 18 UTC on each valid day. The relative maps show 100 × |mean TIGGE − mean ERA5| / mean ERA5; ERA5 means below 1 m/s for wind or 20 W/m² for solar are masked, and colours are capped at 100%. Cartopy may download coastline data on its first run. These are preliminary grid comparisons, not independent validation or evidence of model skill.

## Files and further reading

| File | Purpose |
| --- | --- |
| [docs/data-access-history.md](docs/data-access-history.md) | Data-source decisions, TIGGE requests, access setup and outstanding checks. |
| [docs/weather-data-quality-research.md](docs/weather-data-quality-research.md) | Data quality, exploratory analysis and clustering research. |
| [docs/weather-forecast-bias-adjustment.md](docs/weather-forecast-bias-adjustment.md) | Weather forecast bias correction methods and evaluation. |
| [docs/forecast-reference-matching.md](docs/forecast-reference-matching.md) | Forecast/reference matching research. |
| [docs/forecast-correction-examples.md](docs/forecast-correction-examples.md) | Research examples of forecast correction. |
| [docs/time-series-training-research.md](docs/time-series-training-research.md) | Chronological splits, model updates and data availability. |
| [REPD_Publication_Q2_2026.csv](REPD_Publication_Q2_2026.csv) | UK renewable farm locations and capacities. |
| `data/`, `outputs/` | Local data and generated results; ignored by Git. |

## Decisions so far

We explored direct ECMWF archive access, Open-Meteo and NCAR before selecting TIGGE for the next experiment. TIGGE offers a historical ECMWF ensemble archive and longer lead times, with trade-offs in variables and six-hourly resolution. ERA5 is the reference for the provisional wind experiment. The [data-access history](docs/data-access-history.md) records why the plan changed. Official-boundary verification, final testing and independent-observation evaluation remain future work.
