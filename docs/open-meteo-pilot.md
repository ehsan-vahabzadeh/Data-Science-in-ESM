# Open-Meteo forecast and reference data pilot

**Checked:** 6 November 2026. This pilot tests access and coverage for a small
sample; it does not establish model skill or suitability for an operational
backtest.

## What was requested

`OpenMeteoPilot.py` requests the ECMWF IFS HRES model (`ecmwf_ifs`) from
Open-Meteo's [Single Runs API](https://open-meteo.com/en/docs/single-runs-api),
and ERA5 from its [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api).
Both requests ask for 100 m wind speed in m/s and downward shortwave radiation
in W/m² at two example locations:

| Example location | Use | Requested coordinates | Location source |
| --- | --- | --- | --- |
| South Beach Wind Turbine (Somerton), Norfolk | Wind | 52.709894, 1.654462 | [Wind Farm Data](https://windfarmdata.co.uk/wind-farms/south-beach-wind-turbine-somerton) |
| Fen Farm Solar Park, Lincolnshire | Solar | 53.41731, 0.08515 | [Mapcarta / OpenStreetMap](https://mapcarta.com/W673825036) |

These are approximate site locations, not measurements of weather or power at
the sites. Each request selects a 12:00 UTC IFS run and checks the next UTC
day. Wind is instantaneous at 00:00–23:00 UTC. Radiation is the mean over the
preceding hour, so the target day's intervals use timestamps 01:00 through
00:00 on the following day. This avoids comparing different solar intervals.

## What worked

- Three run dates—15 October in 2024, 2025 and 2026—returned forecasts and
  ERA5 references for both sites, with matching requested units and 24 non-null
  target-day hours for both variables.
- All 31 October 2025 run dates were then checked at both sites. Each of the
  62 site/run cases had 24 valid target-day wind values and 24 valid target-day
  solar values in both sources: **0 missing out of 5,952 checked values**.
  The corresponding target days are 2 October through 1 November 2025 UTC.
- Full API responses, request URLs, retrieval time, and checks are stored in
  `data/open-meteo-pilot/pilot.json` and `pilot-2025-10.json`. They are local
  working data and are not committed to Git.

These results demonstrate small requests worked on this machine on the stated
date. They do not prove that every run or location in a two-year period exists.

## Limits and next steps

- Open-Meteo returned different IFS and ERA5 grid centres: approximately
  14 km apart for the wind example and 12 km for the solar example. A difference
  can therefore reflect spatial mismatch as well as forecast error. The default
  selection also favours land cells with similar elevation; it is not always
  the closest cell. A follow-up nearest-cell check and its limitations are in
  [forecast matching research](forecast-reference-matching.md).
- Open-Meteo describes early IFS HRES archive data as **49r1 hindcasts** in its
  [Single Runs documentation](https://open-meteo.com/en/docs/single-runs-api).
  ECMWF says 49r1 entered operation on 12 November 2024. Thus the October 2024
  sample cannot yet be described as the forecast issued operationally that day;
  clarify which dates are hindcasts and what information initialized them before
  claiming an as-issued backtest. [ECMWF IFS history](https://www.ecmwf.int/en/forecasts/documentation-and-support/changes-ecmwf-model).
- The requested model is IFS, but the JSON response itself does not independently
  attest the model identity. Open-Meteo derives some fields and may interpolate
  data; preserve the explicit model selection and request settings.
- ERA5 is an observation-informed reanalysis, not an independent farm sensor.
  ERA5 values close to the present may be preliminary ERA5T.
- Initialization at 12:00 UTC is not public availability at 12:00; allow for
  dissemination delay when defining any operational decision time.
- Open-Meteo's [free API terms](https://open-meteo.com/en/terms) allow
  noncommercial use with limits; check current terms before any commercial use.

Next, resolve the historical-run provenance, choose a spatial matching method,
and check additional dates, locations and seasons. Then build a reproducible
chronological split and compare a linear correction with the raw forecast.
