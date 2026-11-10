# Weather data access and decisions

Last checked: 9 November 2026. This note records how we arrived at the current experiment and what remains unverified. The [README](../README.md) is the project starting point.

## Goal

Train simple models to correct historical UK weather forecasts against ERA5, starting with separate wind and solar experiments and later comparing more complex models. Evaluate against the original forecast and a simple bias baseline. ERA5 is a reanalysis combining observations and modelling, not direct ground truth; independent observations and renewable-generation impacts are later work.

## How the data-source plan evolved

An earlier ERA5-only machine-learning prototype was removed during repository cleanup because it did not implement forecast error correction. It remains available in Git history; its historical datasets and outputs were retained locally.

| Source | What we learned and why we moved on or retained it |
| --- | --- |
| Direct ECMWF MARS operational archive | The user's ECMWF Web API request returned `no access to services/mars`. The archive catalogue describes data but does not grant MARS access. Research access was investigated; it was not obtained in this project. |
| Open-Meteo | The project built a pilot and a resumable IFS/ERA5 matching downloader for 100 m wind and downward shortwave radiation. Point-based access and free-service limits made a large UK-wide historical collection slow. Some archived forecast provenance needs confirmation. The downloader, its local schedule and Open-Meteo data were removed when the project moved to TIGGE. |
| NCAR GDEX `d113001` | NCAR offers a global archive of operational ECMWF IFS products and spatial subsetting. A one-day UK-area request for 100 m wind and downward solar was submitted; request `965103` was last seen in `Wait`. Metadata showed 100 m wind at products labelled +6 and +12 hours, but file timestamps and longer leads were not verified. This is still a possible complementary source. |
| WeatherBench 2 | Considered for cloud-hosted forecast and reference data. We did not establish a complete, suitable UK wind/solar retrieval workflow, so it remains an alternative rather than a tested source. |
| TIGGE through ECMWF Data Store (ECDS) | Chosen for the next experiment because the historical ECMWF ensemble archive covers the period, provides longer forecast leads and can be requested programmatically for a region. A small UK forecast request succeeded and a 25 KB GRIB sample was downloaded and checksum-verified; its contents have not yet been inspected. TIGGE is a compromise: this request is six-hourly, uses 10 m wind and net solar radiation, and uses an ensemble control forecast rather than the exact operational high-resolution product studied in the paper. |

TIGGE contains forecasts from several centres; this experiment selects ECMWF. The control forecast is one member, not an ensemble mean. Its identity, forecast initialization and lead must be retained when matching or training. TIGGE's [dataset description](https://ecds.ecmwf.int/datasets/tigge-forecasts), [parameter list](https://confluence.ecmwf.int/spaces/TIGGE/pages/40109884/Parameters) and [licence](https://ecds.ecmwf.int/licences/tigge-licence) describe the archive. Its published 48-hour release delay does not prevent a historical study, but affects use as a real-time forecast source.

## Current TIGGE requests

On 9 November 2026, the user accepted the TIGGE licence and configured the ECDS API. The previous two-year request failed because ECMWF reported a maximum of one year per forecast base time. Superseded jobs were removed and replaced with these two jobs:

| Forecast initialization dates, inclusive | ECMWF job ID | Last observed status |
| --- | --- | --- |
| 1 March 2024–28 February 2025 | `b90ad4cf-8435-42a8-b560-1b8e89c8536f` | Successful; downloaded |
| 1 March 2025–28 February 2026 | `0c73b683-a97b-4847-a72e-a2967e9b8d7c` | Successful; downloaded |

Both request ECMWF control forecasts initialized at 12:00 UTC, at +12, +18, +24 and +30 hours, on a 0.5° grid over 48–62°N, 12°W–4°E. The rectangle includes UK land, surrounding seas and areas outside UK waters. The forecast initialization date range is not the same as the valid-time range: the final valid times extend into March 2026.

The requested parameters are 10 m eastward and northward wind components (`10u`, `10v`), 2 m temperature (`2t`), total cloud cover (`tcc`) and surface net solar radiation (`ssr`). Wind speed can be calculated from the components. TIGGE's listed solar radiation is accumulated net radiation, not incoming downward irradiance; inspect its accumulation metadata and choose a compatible ERA5 comparison before modelling. Do not infer hourly coverage from six-hourly steps.

Pressure, precipitation, dew point and land/sea mask are candidates listed in TIGGE, but were not included in these jobs. Their availability for the chosen centre, dates, run and leads has not been verified. The sample is stored locally at `data/tigge-pilot/uk-2024-03-01.grib`; `data/` is ignored by Git. Both one-year files were downloaded to `data/tigge/` and their checksums verified; their contents and completeness have not yet been audited.

## Access and next checks

- ECDS uses the official `cdsapi` Python client and a personal token in `~/.cdsapirc`; the account must accept the dataset licence. See [ECDS API setup](https://ecds.ecmwf.int/how-to-api). Credentials belong outside the repository and must never be committed or pasted into chat. `cdsapi` was installed in the local `.venv`; this alone is not a reproducible project dependency declaration or a TIGGE downloader.
- The TIGGE files are downloaded locally. The old NCAR request is independent of these ECDS jobs.
- On 9 November 2026, a two-day CDS ERA5 sample for 2–3 March 2024 was downloaded to `data/era5/`. Preliminary relative forecast-minus-ERA5 maps of 10 m wind speed and six-hour net solar radiation were generated under `outputs/tigge-era5-comparison/` using previous-day 12 UTC runs at +18, +24 and +30 hours. Each percentage is the absolute difference between the three-time means divided by the ERA5 three-time mean; ERA5 means below 1 m/s for wind or 20 W/m² for solar are masked. Colours are capped at 100%. ERA5 coordinates were matched exactly to TIGGE grid centres; the entire bounding rectangle, including non-UK areas, was retained. Averaging can conceal individual-time errors.
- A further comparison for 2 March 2024 at 12 UTC used a +24-hour forecast initialized on 1 March at 12 UTC and a +12-hour forecast initialized on 2 March at 00 UTC. The 06 UTC 2 March initialization at +6 hours returned no data for the requested ECMWF control fields; this is one unsuccessful request, not proof that no six-hour forecasts exist anywhere. The resulting same-valid-time maps use the same percentage thresholds and compare solar energy for 06–12 UTC.
- A one-run 0.25° TIGGE sample was retrieved to `data/tigge-pilot/quarter-degree-2024-03-01.grib` and compared on the same 0.25° ERA5 coordinates for 2 March 12 UTC. The resulting map is `outputs/tigge-era5-comparison/quarter-degree-absolute-error-2024-03-02.png`. This was a one-off comparison; requesting a finer output grid does not establish the native archived resolution or add independent ERA5 detail.
- Inspect the sample and resulting GRIB files for field names, units, actual runs, leads, grid, missing records and coverage; acceptance of a request does not prove complete data delivery. Check ECDS request logs and failures if needed.
- Obtain matching ERA5 reference variables, dates and spatial coverage through a suitable source. Align grid locations and solar accumulation intervals, and record provenance. A TIGGE-to-ERA5 pipeline has not yet been implemented.
- Split by time before fitting transformations, keep the final test period unseen and compare raw forecasts, a mean-bias baseline and a simple linear or Ridge model. Any new weather predictor must be available from the forecast at the decision time, not from same-valid-time ERA5.
