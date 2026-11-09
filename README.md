# UK wind and solar forecast research

This project explores whether simple machine learning can improve **UK wind and solar weather forecasts**. The current experiment uses ECMWF IFS forecasts from TIGGE and plans to compare them with ERA5 as a historical reference. The long-term aim is to connect weather forecasts to renewable generation and, later, electricity-market questions.

## Project targets

🟢 **Done** · 🟡 **Under way** · ⚪ **Planned**

| Status | Target by the end of the project | Current position |
| --- | --- | --- |
| 🟡 | Establish a repeatable way to access and match IFS and ERA5 data | An Open-Meteo pilot exists; the new TIGGE-to-ERA5 workflow has not yet been implemented or verified. |
| 🟡 | Build and audit a multi-year UK land and offshore wind/solar dataset | Two one-year TIGGE jobs have been submitted; their data and the matching ERA5 reference are not yet verified. |
| ⚪ | Train separate, understandable wind and solar correction models | Planned: compare uncorrected IFS, a mean-bias correction, then linear or Ridge models. No correction model has been trained. |
| ⚪ | Test whether more complex models improve on the simple models | Planned: compare random forests or gradient-boosted trees using the same inputs and time splits. |
| ⚪ | Verify performance and generalisation | Planned: chronological train/validation/test splits, seasonal and lead-time results, and separate onshore/offshore evaluation. |
| ⚪ | Check forecasts against independent measurements | Investigate UK station wind data, including 10 m observations; offshore and solar observation sources still need research. |
| ⚪ | Explore renewable generation and power-market applications | A later stage: weather variables alone are not power or energy forecasts. |

## Current position

**TIGGE is the chosen source for the next experiment.** We requested two years of ECMWF ensemble control forecasts over a UK and surrounding-seas bounding box on a 0.5° grid, for the 12 UTC run at +12, +18, +24 and +30 hours. The requested fields are 10 m wind components, 2 m temperature, total cloud cover and surface net solar radiation. These six-hourly samples do not cover every hour, and the rectangle includes non-UK areas. They are not the former 100 m wind and downward solar design.

As of 9 November 2026, the one-year jobs were running and accepted, respectively. A one-run sample was downloaded, but neither the two-year requests nor the sample's contents have been fully validated. ERA5 must still be acquired and matched. See the [data-access history and current request](docs/data-access-history.md) for job IDs, decisions, limitations and next checks.

The existing Open-Meteo downloader is a separate earlier workflow. It matches **100 m wind speed** and **surface shortwave radiation** at hourly UTC timestamps, using the previous day's 12:00 UTC IFS run at +12 to +35 hours. Its 0.5° sample grid contains 134 UK land and 431 offshore points within an approximate UK maritime-area mask; it is not every native model grid cell or a legal boundary. It does not download or process TIGGE.

A daily macOS job was installed on this machine at 02:15 local time and processes up to five days per run, including incomplete-day retries. It needs the Mac on, connected, and the user logged in. Its output is local and ignored by Git. Check progress with:

```bash
tail -f data/open-meteo-uk-eez/scheduled-download.log
```

Press Ctrl+C to stop watching the log; the download continues. Errors are in `data/open-meteo-uk-eez/scheduled-download-error.log`. See [dataset and schedule instructions](docs/open-meteo-dataset.md) for the download, limits, stopping the schedule and provenance.

**Data quality:** the downloader retries incomplete daily files and preserves older copies in an `incomplete/` folder. Missing or repeatedly unavailable values can still remain, so audit completeness and provenance before training. Docker Compose could not be checked on the current machine.

## Data and scientific background

- **IFS** is ECMWF's numerical weather prediction model: it issues forecasts before the weather occurs. TIGGE archives ensemble forecasts from multiple centres, including ECMWF; the current request uses ECMWF's control forecast.
- **ERA5** is ECMWF's historical reanalysis, combining observations and modelling. It is a useful reference but is not an independent farm sensor or perfect ground truth.
- An IFS forecast has an initialization time and a lead time, giving the **valid time** being forecast. The run's initialization is not necessarily its public availability time.
- Wind components are forecast at a valid time. TIGGE net solar radiation is accumulated and differs from incoming downward solar radiation; compare like quantities over matching intervals and verify units and step metadata. Open-Meteo's earlier shortwave-radiation value is a preceding-hour mean.
- IFS and ERA5 may select different grid centres. Their recorded distance is a source of uncertainty in the comparison.
- Some historical IFS runs are described as hindcasts; their provenance and model-cycle changes need assessment before claiming an as-issued operational backtest.

## Proposed modelling approach

Plan separate wind and solar models that predict `ERA5 − IFS`, then add the predicted correction to the forecast. Start with forecast wind, net solar radiation, cloud cover and temperature where available, plus lead time, cyclic time and location; a land/sea indicator still needs to be obtained and aligned. Wind speed is derived from the 10 m components. Establish a compatible solar target before modelling: net solar radiation is not the same as downward solar irradiance. Fit all preprocessing on the training period only. Same-valid-time ERA5 is the **target**, never a predictor.

Compare MAE, RMSE and signed bias against the raw forecast. For solar report both daylight and all-hour scores. Test later dates and seasons without leaking future information; improving agreement with ERA5 alone does not establish improved real-world skill. The existing [forecast postprocessing research](docs/forecast-postprocessing-models.md) explains model options and published examples.

`UKDayAheadWeatherML.py` is a retained **legacy ERA5-only** forecasting experiment. It uses gradient-boosted trees and an atlite-format ERA5 cutout; it does not accept the Open-Meteo dataset or implement the planned IFS correction model. See [legacy model notes](UK_DAY_AHEAD_WEATHER.md).

## Run and test

These commands run the earlier Open-Meteo pilot and downloader, not the TIGGE experiment. The pilot uses Python's standard library and needs internet access. The downloader also uses POSIX file locking, supported on macOS and Linux.

```bash
python3 OpenMeteoPilot.py
python3 OpenMeteoMatch.py
```

The downloader makes network requests and is already scheduled on this Mac. The file lock prevents simultaneous runs against the same output directory. Existing pilot results are not overwritten. Check Open-Meteo's current non-commercial terms and limits before substantial use.

The full test suite needs the dependencies listed in `docker/requirements.txt`:

```bash
python -m pip install -r docker/requirements.txt
python -m unittest discover -s tests
```

Tests use synthetic or mocked data and do not require network access. Live access, full historical coverage and model performance need separate verification. For the container setup, see [docker/README.md](docker/README.md).

## Files and further reading

| File | Purpose |
| --- | --- |
| [OpenMeteoPilot.py](OpenMeteoPilot.py) | Small IFS/ERA5 access and completeness pilot. |
| [OpenMeteoMatch.py](OpenMeteoMatch.py) | Resumable forecast/reference downloader and matcher. |
| [docs/open-meteo-dataset.md](docs/open-meteo-dataset.md) | Grid, timing, dataset provenance, download and schedule details. |
| [docs/data-access-history.md](docs/data-access-history.md) | Data-source decisions, TIGGE requests, access setup and outstanding checks. |
| [docs/open-meteo-pilot.md](docs/open-meteo-pilot.md) | Results and limitations of the two-site pilot. |
| [docs/forecast-reference-matching.md](docs/forecast-reference-matching.md) | Forecast/reference matching research. |
| [docs/forecast-correction-examples.md](docs/forecast-correction-examples.md) | Research examples of forecast correction. |
| [REPD_Publication_Q2_2026.csv](REPD_Publication_Q2_2026.csv) | UK renewable farm locations and capacities. |
| `data/`, `outputs/` | Local data and generated results; ignored by Git. |

## Decisions so far

We explored direct ECMWF archive access, Open-Meteo and NCAR before selecting TIGGE for the next experiment. TIGGE offers a historical ECMWF ensemble archive and longer lead times, with trade-offs in variables and six-hourly resolution. ERA5 remains the planned reference. The [data-access history](docs/data-access-history.md) records why the plan changed. The model, validated multi-year dataset and independent-observation evaluation remain future work.
