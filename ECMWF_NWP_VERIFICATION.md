# ECMWF NWP verification at 00:00 and 12:00 UTC

## The worked case

The reproducible example uses:

- IFS initialization: **19 August 2026 at 12:00 UTC**;
- valid day: **20 August 2026**;
- selected times: **00:00 and 12:00 UTC**;
- forecast: ECMWF deterministic IFS open data;
- reference: ERA5T downloaded through Copernicus and processed by atlite.

The run was initialized before the target day, so this is genuinely a
day-ahead forecast rather than a forecast started during the day being tested.

## Forecast time terminology

| Term | Example | Meaning |
|---|---|---|
| Initialization time | 19 Aug, 12 UTC | When IFS began the forecast |
| Lead time or `step` | +12 h | Time elapsed since initialization |
| Valid time | 20 Aug, 00 UTC | When the predicted weather applies |

For this run, 20 August 00:00 is lead +12 h and 20 August 12:00 is lead
+24 h.

## Relative error

The mapped percentage error uses ERA5T in the denominator:

```text
relative error (%) = 100 × (IFS − ERA5T) / ERA5T
```

- positive/red: IFS is higher than ERA5T;
- negative/blue: IFS is lower than ERA5T;
- zero/white: they agree;
- gray: ERA5T is too close to zero for a meaningful percentage.

To prevent tiny denominators producing enormous percentages, relative error is
masked where ERA5T wind is below 0.5 m/s or solar radiation is below 10 W/m².
The NetCDF also retains the signed absolute error in m/s or W/m².

## Wind comparison

IFS provides eastward and northward 100 m wind components:

```text
wind speed = sqrt(100u² + 100v²)
```

Wind is instantaneous at 00:00 and 12:00 in both datasets.

## Solar comparison

IFS `ssrd` is accumulated energy in J/m², not instantaneous power in W/m².
The open deterministic fields are three-hourly at these lead times. Therefore,
each selected solar time represents the aligned three-hour interval beginning
at that time:

```text
00:00 map = mean solar radiation from 00:00 to 03:00 UTC
12:00 map = mean solar radiation from 12:00 to 15:00 UTC

IFS interval mean = [ssrd(end) − ssrd(start)] / 10,800 seconds
ERA5T interval mean = mean(influx_direct + influx_diffuse)
```

At midnight in this example, IFS and ERA5T are both 0 W/m². The absolute error
is zero, but relative error is undefined because it would require division by
zero. The gray midnight solar panel is intentional.

## Do ERA5T and IFS use the same grid?

For the files used in this exercise, **yes**:

- both are distributed on a regular 0.25° latitude/longitude output grid;
- both contain the same UK coordinates from 49.5° to 61.25° north and −8.75°
  to 2.25° east;
- the script changes ECMWF's names `latitude`/`longitude` to atlite's `y`/`x`,
  reverses ECMWF's descending latitude order, and then requires exact coordinate
  alignment with `xr.align(..., join="exact")`.

The native internal model grids are not the same. IFS performs its calculations
on its operational model grid, while ERA5 uses the ERA5 assimilation/model
system. Both products have been interpolated to matching 0.25° regular grids
for distribution. Matching output coordinates make cell-by-cell subtraction
possible, but do not make the underlying models identical.

## What “recorded” means

There is no instrument measuring 100 m wind and solar radiation in every UK
grid cell. ERA5T is an observation-informed reanalysis: it combines many
observations with a numerical model through data assimilation. It is a useful
gridded verification reference, but it is not literal ground truth.

Later comparisons can use solar stations or satellite radiation, and wind
masts, lidar, offshore buoys, or wind-farm SCADA where available.

## Run it

```bash
python ECMWFForecastVerification.py
```

Different three-hourly comparison times can be selected, for example:

```bash
python ECMWFForecastVerification.py --hours 6 12 18
```

Outputs in `outputs/ecmwf-verification/` include:

- `ecmwf_20260820_0000_relative_error_maps.png`;
- `ecmwf_20260820_1200_relative_error_maps.png`;
- `selected_times_verification_metrics.csv`;
- `ecmwf_selected_times_vs_era5t.nc`;
- `selected_times_run_metadata.json`.

For 24 August, after its ERA5T reference becomes available:

```bash
python ECMWFForecastVerification.py \
  --valid-day 2026-08-24 \
  --download-era5 \
  --output-dir outputs/ecmwf-verification-2026-08-24
```

Official documentation:

- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)
- [ECMWF open-data Python client](https://github.com/ecmwf/ecmwf-opendata)
- [Copernicus ERA5 hourly single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)

