# Comparing ECMWF and Open-Meteo IFS deliveries

This experiment checks access to and consistency between two deliveries of the **same ECMWF IFS forecast**. It does not compare two independent forecasting models, evaluate forecast accuracy, or use observations or ERA5. A difference between providers is not an error against the real weather.

## Run it

Python 3.12 or later and an internet connection are needed. In the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install 'ecmwf-opendata>=0.3,<0.4' 'cfgrib>=0.9,<1' 'eccodes' 'xarray>=2025.1,<2027' 'numpy>=1.26,<3' 'pandas>=2.2,<3' 'matplotlib>=3.9,<4' 'cartopy>=0.26,<0.27'
python IFSVsOpenMeteo.py
```

The command picks the latest UTC date for which noon has passed, then the preceding two dates. Specify `--end-date YYYY-MM-DD` to select another ending day: the freely available ECMWF forecasts are only retained for a limited rolling period, so older dates may not be available unless already cached. Availability can lag: a failed download does not mean data has been verified unavailable permanently. Both services are subject to their terms and rate limits; ECMWF Open Data does not need a MARS account. The first run downloads Natural Earth boundaries too.

Raw direct GRIB files, Open-Meteo responses and boundary files are cached in `data/ifs-openmeteo/`. Three maps, a table of grid points, a summary and metadata go into `outputs/ifs-openmeteo/START_to_END/`. The command refuses to overwrite an existing output folder; use `--output-dir` to choose another destination. Both directories are ignored by Git. For options, run `python IFSVsOpenMeteo.py --help`.

## What is matched

- Each date's 00:00 UTC initialization, with wind at 12:00 UTC (+12 hours). This is a same-day comparison, not a day-ahead forecast.
- Direct ECMWF IFS 0.25° data and Open-Meteo `ecmwf_ifs025`; matching grid coordinates are selected, with Open-Meteo elevation adjustment disabled. Points are sampled every 0.5°; only centres inside the UK's land boundary are included. Offshore areas and some small islands are excluded. The map shows cells around sampled centres, not a high-resolution view.
- Wind is speed at 100 m, in m/s. Solar is the average surface shortwave radiation over 09:00–12:00 UTC, in W/m². ECMWF reports energy accumulated from the run start: subtract the 9-hour accumulation from the 12-hour accumulation and divide by 10,800 seconds. Open-Meteo reports means for preceding hours: average the values labelled 10:00, 11:00 and 12:00. Open-Meteo's 0.25° IFS product is three-hourly and its hourly values are interpolated. See [Open-Meteo's ECMWF documentation](https://open-meteo.com/en/docs/ecmwf-api).
- The difference is **Open-Meteo minus direct ECMWF**. Differences can reflect processing, interpolation or other factors; this experiment does not determine their causes. The summary gives equally weighted grid-point means, not land-area or renewable-capacity-weighted averages.

## Example result: 4–6 November 2026

The live experiment returned 134 UK land points per day. Mean absolute differences between the two deliveries were 0.024–0.027 m/s for wind and 2.93–4.30 W/m² for solar across the three dates. These values measure agreement between sources for this sample only; they say nothing about forecast accuracy and do not establish access to a two-year direct ECMWF archive.

The next scientific step is to pair forecasts **as issued** with a later independent reference, such as ERA5 or observations, at matching valid times and locations, before training and evaluating a correction model. The historical coverage and provenance of Open-Meteo's earlier runs need separate checking.
