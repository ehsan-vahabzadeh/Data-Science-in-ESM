# UK wind and solar forecast research

This project explores whether simple machine learning can improve **UK day-ahead wind and solar weather forecasts**. The planned models will correct forecasts from ECMWF's IFS using ERA5 as a historical reference, with both datasets accessed through Open-Meteo. The long-term aim is to connect weather forecasts to renewable generation and, later, electricity-market questions.

## Project targets

🟢 **Done** · 🟡 **Under way** · ⚪ **Planned**

| Status | Target by the end of the project | Current position |
| --- | --- | --- |
| 🟢 | Establish a repeatable way to access and match IFS and ERA5 data | A pilot and a resumable hourly downloader exist and have been exercised on small samples. |
| 🟡 | Build and audit a multi-year UK land and offshore wind/solar dataset | Six daily files had been saved at the last check on 9 November 2026; the full period is not yet collected or validated. |
| ⚪ | Train separate, understandable wind and solar correction models | Planned: compare uncorrected IFS, a mean-bias correction, then linear or Ridge models. No correction model has been trained. |
| ⚪ | Test whether more complex models improve on the simple models | Planned: compare random forests or gradient-boosted trees using the same inputs and time splits. |
| ⚪ | Verify performance and generalisation | Planned: chronological train/validation/test splits, seasonal and lead-time results, and separate onshore/offshore evaluation. |
| ⚪ | Check forecasts against independent measurements | Investigate UK station wind data, including 10 m observations; offshore and solar observation sources still need research. |
| ⚪ | Explore renewable generation and power-market applications | A later stage: weather variables alone are not power or energy forecasts. |

## Current position

The downloader matches **100 m wind speed** and **surface shortwave radiation** at hourly UTC timestamps. It uses the previous day's 12:00 UTC IFS run, with +12 to +35-hour forecast leads, and selects nearby grid cells separately for IFS and ERA5. The 0.5° sample grid contains 134 UK land and 431 offshore points within an approximate published UK maritime-area mask. It is a coarse sample, not every native model grid cell or a legal boundary.

A daily macOS job was installed on this machine at 02:15 local time and processes up to five days per run, including incomplete-day retries. It needs the Mac on, connected, and the user logged in. Its output is local and ignored by Git. Check progress with:

```bash
tail -f data/open-meteo-uk-eez/scheduled-download.log
```

Press Ctrl+C to stop watching the log; the download continues. Errors are in `data/open-meteo-uk-eez/scheduled-download-error.log`. See [dataset and schedule instructions](docs/open-meteo-dataset.md) for the download, limits, stopping the schedule and provenance.

**Data quality:** the downloader retries incomplete daily files and preserves older copies in an `incomplete/` folder. Missing or repeatedly unavailable values can still remain, so audit completeness and provenance before training. Docker Compose could not be checked on the current machine.

## Data and scientific background

- **IFS** is ECMWF's numerical weather prediction model: it issues forecasts before the weather occurs. Open-Meteo is the delivery service used here.
- **ERA5** is ECMWF's historical reanalysis, combining observations and modelling. It is a useful reference but is not an independent farm sensor or perfect ground truth.
- An IFS forecast has an initialization time and a lead time, giving the **valid time** being forecast. The run's initialization is not necessarily its public availability time.
- Wind is instantaneous at the timestamp. Open-Meteo's shortwave-radiation value is the mean over the **preceding hour**. Both sources must describe the same interval and use compatible units.
- IFS and ERA5 may select different grid centres. Their recorded distance is a source of uncertainty in the comparison.
- Some historical IFS runs are described as hindcasts; their provenance and model-cycle changes need assessment before claiming an as-issued operational backtest.

## Proposed modelling approach

Train two models, one for wind and one for solar, each predicting `ERA5 − IFS`. Add the predicted correction to the original IFS forecast. Start with the same forecast wind, forecast solar, lead time, cyclic time-of-day and time-of-year, location and land/sea inputs for each model. Fit all preprocessing on the training period only. Same-valid-time ERA5 is the **target**, never a predictor.

Compare MAE, RMSE and signed bias against the raw forecast. For solar report both daylight and all-hour scores. Test later dates and seasons without leaking future information; improving agreement with ERA5 alone does not establish improved real-world skill. The existing [forecast postprocessing research](docs/forecast-postprocessing-models.md) explains model options and published examples.

`UKDayAheadWeatherML.py` is a retained **legacy ERA5-only** forecasting experiment. It uses gradient-boosted trees and an atlite-format ERA5 cutout; it does not accept the Open-Meteo dataset or implement the planned IFS correction model. See [legacy model notes](UK_DAY_AHEAD_WEATHER.md).

## Run and test

The pilot uses Python's standard library and needs internet access. The downloader also uses POSIX file locking, supported on macOS and Linux.

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
| [docs/open-meteo-pilot.md](docs/open-meteo-pilot.md) | Results and limitations of the two-site pilot. |
| [docs/forecast-reference-matching.md](docs/forecast-reference-matching.md) | Forecast/reference matching research. |
| [docs/forecast-correction-examples.md](docs/forecast-correction-examples.md) | Research examples of forecast correction. |
| [REPD_Publication_Q2_2026.csv](REPD_Publication_Q2_2026.csv) | UK renewable farm locations and capacities. |
| `data/`, `outputs/` | Local data and generated results; ignored by Git. |

## Decisions so far

We first explored an ERA5-only ML forecast and direct IFS/ERA5 comparisons. We then selected Open-Meteo as the data source, chose the previous day's 12:00 UTC IFS run, opted for a 0.5° UK land and maritime-area sample, and decided to start with ERA5 as the reference. The model, multi-year dataset and independent-observation evaluation remain future work.
