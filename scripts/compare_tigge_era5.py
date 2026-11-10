"""Compare two TIGGE forecast days with matching hourly ERA5 GRIB data."""
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release


def six_hour_solar(current, previous, hourly):
    """Convert TIGGE cumulative and ERA5 hourly energy to six-hour mean W/m²."""
    if len(hourly) != 6:
        raise ValueError('Exactly six hourly ERA5 accumulations are required')
    return (current - previous) / 21600, np.sum(hourly, axis=0) / 21600


def absolute_relative_error(forecast, reference, minimum):
    """Absolute percentage error of time-averaged values; mask weak references."""
    forecast_mean = np.mean(forecast, axis=0)
    reference_mean = np.mean(reference, axis=0)
    result = np.full_like(reference_mean, np.nan, dtype=float)
    np.divide(100 * np.abs(forecast_mean - reference_mean), reference_mean,
              out=result, where=reference_mean >= minimum)
    return result


def read_grib(path, wanted):
    fields = {}
    with open(path, 'rb') as stream:
        while message := codes_grib_new_from_file(stream):
            try:
                name = codes_get(message, 'shortName')
                valid = datetime.strptime(str(codes_get(message, 'validityDate')) + f"{codes_get(message, 'validityTime'):04d}", '%Y%m%d%H%M')
                init = datetime.strptime(str(codes_get(message, 'dataDate')) + f"{codes_get(message, 'dataTime'):04d}", '%Y%m%d%H%M')
                step = int(codes_get(message, 'endStep'))
                if not wanted(name, init, valid, step):
                    continue
                lat = codes_get_array(message, 'latitudes')
                lon = (codes_get_array(message, 'longitudes') + 180) % 360 - 180
                values = codes_get_array(message, 'values')
                key = (name, init, valid, step)
                if key in fields:
                    raise ValueError(f'Duplicate GRIB field {key}')
                fields[key] = (lat, lon, values)
            finally:
                codes_release(message)
    return fields


def on_grid(field, lat, lon):
    source_lat, source_lon, values = field
    indices = {(round(float(a), 4), round(float(b), 4)): i for i, (a, b) in enumerate(zip(source_lat, source_lon))}
    try:
        return np.array([values[indices[(round(float(a), 4), round(float(b), 4))]] for a, b in zip(lat, lon)])
    except KeyError as exc:
        raise ValueError(f'ERA5 grid lacks requested TIGGE coordinate {exc}') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast', type=Path, required=True)
    parser.add_argument('--era5', type=Path, required=True)
    parser.add_argument('--start-date', type=date.fromisoformat, required=True, help='First valid date; compare this and the following day')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dates = [args.start_date + timedelta(days=i) for i in range(2)]
    runs = {datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=12) for d in dates}
    f = read_grib(args.forecast, lambda n, i, v, s: i in runs and n in {'10u', '10v', 'ssr'} and s in {12, 18, 24, 30})
    e = read_grib(args.era5, lambda n, i, v, s: v.date() in dates and 1 <= v.hour <= 18 and n in {'10u', '10v', 'ssr'})
    by_valid = {}
    for (name, init, valid, step), field in e.items():
        if (name, valid) in by_valid:
            raise ValueError(f'Duplicate ERA5 valid time {name} {valid}')
        by_valid[name, valid] = field
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    args.output.mkdir(parents=True, exist_ok=True)
    for day in dates:
        run = datetime.combine(day - timedelta(days=1), datetime.min.time()).replace(hour=12)
        first = f['10u', run, run + timedelta(hours=18), 18]
        lat, lon, _ = first
        lats, lons = np.unique(lat), np.unique(lon)
        if len(lats) * len(lons) != len(lat):
            raise ValueError('TIGGE grid is not a complete rectangle')
        order = np.lexsort((lon, lat))
        winds, reference_winds, solar, reference_solar = [], [], [], []
        for step in (18, 24, 30):
            valid = run + timedelta(hours=step)
            u = f['10u', run, valid, step][2]; v = f['10v', run, valid, step][2]
            ref_u = on_grid(by_valid['10u', valid], lat, lon); ref_v = on_grid(by_valid['10v', valid], lat, lon)
            winds.append(np.hypot(u, v)); reference_winds.append(np.hypot(ref_u, ref_v))
            now = f['ssr', run, valid, step][2]; prev = f['ssr', run, valid - timedelta(hours=6), step - 6][2]
            hourly = [on_grid(by_valid['ssr', valid - timedelta(hours=h)], lat, lon) for h in range(5, -1, -1)]
            pred_solar, ref_solar = six_hour_solar(now, prev, hourly)
            solar.append(pred_solar); reference_solar.append(ref_solar)
        fig, axes = plt.subplots(1, 2, figsize=(14, 7), subplot_kw={'projection': ccrs.PlateCarree()}, constrained_layout=True)
        comparisons = [(winds, reference_winds, '10 m wind speed', 1., '1 m/s'),
                       (solar, reference_solar, 'Net solar radiation', 20., '20 W/m²')]
        for ax, (forecast, reference, title, minimum, threshold) in zip(axes, comparisons):
            if not np.isfinite(forecast).all() or not np.isfinite(reference).all():
                raise ValueError('Missing or non-finite values in comparison')
            values = absolute_relative_error(np.asarray(forecast), np.asarray(reference), minimum)
            grid = values[order].reshape(len(lats), len(lons))
            im = ax.pcolormesh(lons, lats, np.ma.masked_invalid(grid), cmap='YlOrRd', vmin=0, vmax=100, shading='nearest', transform=ccrs.PlateCarree())
            ax.coastlines(resolution='110m'); ax.set_extent([-12, 4, 48, 62]); ax.gridlines(draw_labels={'left': 'y', 'bottom': 'x'}, linestyle=':', alpha=0.5)
            ax.set_title(f'{title}\nERA5 mean below {threshold} masked')
            fig.colorbar(im, ax=ax, shrink=0.7, label='Absolute relative error (%)', extend='max')
            print(f'{day} {title}: valid grid points {np.isfinite(values).sum()}/{len(values)}')
        fig.suptitle(f'{day}: 100 × |mean TIGGE − mean ERA5| / mean ERA5\n06, 12, 18 UTC; previous day 12 UTC run; colours capped at 100%')
        path = args.output / f'relative-forecast-error-{day}.png'; fig.savefig(path, dpi=150); plt.close(fig); print('Saved', path)


if __name__ == '__main__':
    main()
