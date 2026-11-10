# UK wind and solar forecast research

This project explores whether simple machine learning can improve **UK wind and solar weather forecasts**. The current experiment uses ECMWF IFS forecasts from TIGGE and plans to compare them with ERA5 as a historical reference. The long-term aim is to connect weather forecasts to renewable generation and, later, electricity-market questions.

## Project targets

🟢 **Done** · 🟡 **Under way** · ⚪ **Planned**

| Status | Target by the end of the project | Current position |
| --- | --- | --- |
| 🟡 | Establish a repeatable way to access and match IFS and ERA5 data | TIGGE forecast files were downloaded; the TIGGE-to-ERA5 matching workflow has not yet been implemented or verified. |
| 🟡 | Build and audit a multi-year UK land and offshore wind/solar dataset | Two one-year TIGGE files were downloaded and checksum-verified; their contents and the matching ERA5 reference are not yet audited. |
| ⚪ | Train separate, understandable wind and solar correction models | Planned: compare uncorrected IFS, a mean-bias correction, then linear or Ridge models. No correction model has been trained. |
| ⚪ | Test whether more complex models improve on the simple models | Planned: compare random forests or gradient-boosted trees using the same inputs and time splits. |
| ⚪ | Verify performance and generalisation | Planned: chronological train/validation/test splits, seasonal and lead-time results, and separate onshore/offshore evaluation. |
| ⚪ | Check forecasts against independent measurements | Investigate UK station wind data, including 10 m observations; offshore and solar observation sources still need research. |
| ⚪ | Explore renewable generation and power-market applications | A later stage: weather variables alone are not power or energy forecasts. |

## Current position

**TIGGE is the chosen source for the next experiment.** We requested two years of ECMWF ensemble control forecasts over a UK and surrounding-seas bounding box on a 0.5° grid, for the 12 UTC run at +12, +18, +24 and +30 hours. The requested fields are 10 m wind components, 2 m temperature, total cloud cover and surface net solar radiation. These six-hourly samples do not cover every hour, and the rectangle includes non-UK areas. They are not the former 100 m wind and downward solar design.

Both one-year requests completed and the GRIB files were downloaded under `data/tigge/` with matching checksums. Their fields, timestamps and completeness have not yet been audited. ERA5 must still be acquired and matched. See the [data-access history and current request](docs/data-access-history.md) for details and next checks.

## Data and scientific background

- **IFS** is ECMWF's numerical weather prediction model: it issues forecasts before the weather occurs. TIGGE archives ensemble forecasts from multiple centres, including ECMWF; the current request uses ECMWF's control forecast.
- **ERA5** is ECMWF's historical reanalysis, combining observations and modelling. It is a useful reference but is not an independent farm sensor or perfect ground truth.
- An IFS forecast has an initialization time and a lead time, giving the **valid time** being forecast. The run's initialization is not necessarily its public availability time.
- Wind components are forecast at a valid time. TIGGE net solar radiation is accumulated and differs from incoming downward solar radiation; compare like quantities over matching intervals and verify units and step metadata.
- IFS and ERA5 may select different grid centres. Their recorded distance is a source of uncertainty in the comparison.
- Some historical IFS runs are described as hindcasts; their provenance and model-cycle changes need assessment before claiming an as-issued operational backtest.

## Proposed modelling approach

Plan separate wind and solar models that predict `ERA5 − IFS`, then add the predicted correction to the forecast. Start with forecast wind, net solar radiation, cloud cover and temperature where available, plus lead time, cyclic time and location; a land/sea indicator still needs to be obtained and aligned. Wind speed is derived from the 10 m components. Establish a compatible solar target before modelling: net solar radiation is not the same as downward solar irradiance. Fit all preprocessing on the training period only. Same-valid-time ERA5 is the **target**, never a predictor.

Compare MAE, RMSE and signed bias against the raw forecast. For solar report both daylight and all-hour scores. Test later dates and seasons without leaking future information; improving agreement with ERA5 alone does not establish improved real-world skill. The existing [forecast postprocessing research](docs/forecast-postprocessing-models.md) explains model options and published examples.

## Run and test

A complete TIGGE-to-ERA5 processing workflow and its end-to-end tests have not yet been implemented. The [Docker setup](docker/README.md) is a minimal Python environment and does not yet download or process TIGGE data.

An initial two-day comparison on 2–3 March 2024 produced maps under `outputs/tigge-era5-comparison/`. The `scripts/compare_tigge_era5.py` script requires Python packages `eccodes`, `numpy`, `matplotlib` and `cartopy`, plus matching ERA5 GRIB files. It compares 10 m wind and six-hour mean net solar radiation ending at 06, 12 and 18 UTC on each valid day. The relative maps show 100 × |mean TIGGE − mean ERA5| / mean ERA5; ERA5 means below 1 m/s for wind or 20 W/m² for solar are masked, and colours are capped at 100%. Cartopy may download coastline data on its first run. These are preliminary grid comparisons, not independent validation or evidence of model skill.

## Files and further reading

| File | Purpose |
| --- | --- |
| [docs/data-access-history.md](docs/data-access-history.md) | Data-source decisions, TIGGE requests, access setup and outstanding checks. |
| [docs/forecast-reference-matching.md](docs/forecast-reference-matching.md) | Forecast/reference matching research. |
| [docs/forecast-correction-examples.md](docs/forecast-correction-examples.md) | Research examples of forecast correction. |
| [REPD_Publication_Q2_2026.csv](REPD_Publication_Q2_2026.csv) | UK renewable farm locations and capacities. |
| `data/`, `outputs/` | Local data and generated results; ignored by Git. |

## Decisions so far

We explored direct ECMWF archive access, Open-Meteo and NCAR before selecting TIGGE for the next experiment. TIGGE offers a historical ECMWF ensemble archive and longer lead times, with trade-offs in variables and six-hourly resolution. ERA5 remains the planned reference. The [data-access history](docs/data-access-history.md) records why the plan changed. The model, validated multi-year dataset and independent-observation evaluation remain future work.
