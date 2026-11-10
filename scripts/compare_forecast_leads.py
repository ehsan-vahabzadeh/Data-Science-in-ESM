"""Map two forecast lead times for the same valid time against ERA5."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from compare_tigge_era5 import absolute_relative_error, on_grid, read_grib, six_hour_solar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--long-forecast', type=Path, required=True)
    parser.add_argument('--short-forecast', type=Path, required=True)
    parser.add_argument('--short-lead', type=int, choices=[6, 12], required=True)
    parser.add_argument('--era5', type=Path, required=True)
    parser.add_argument('--valid', type=datetime.fromisoformat, required=True, help='UTC valid time in ISO format')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    valid = args.valid
    if valid.tzinfo is not None:
        parser.error('--valid must be a naive UTC time')
    names = {'10u', '10v', 'ssr'}
    e = read_grib(args.era5, lambda n, i, v, s: n in names and valid - timedelta(hours=5) <= v <= valid)
    ref = {}
    for (name, init, time, step), field in e.items():
        if (name, time) in ref:
            raise ValueError(f'Duplicate ERA5 field {name} {time}')
        ref[name, time] = field
    runs = []
    for path, step in [(args.short_forecast, args.short_lead), (args.long_forecast, 24)]:
        init = valid - timedelta(hours=step)
        fields = read_grib(path, lambda n, i, v, s: n in names and i == init and s in {step, step - 6})
        lat, lon, u = fields['10u', init, valid, step]
        v = fields['10v', init, valid, step][2]
        ssr = fields['ssr', init, valid, step][2]
        # TIGGE solar energy is accumulated from forecast start.
        prior = np.zeros_like(ssr) if step == 6 else fields['ssr', init, valid - timedelta(hours=6), step - 6][2]
        solar_hours = [on_grid(ref['ssr', valid - timedelta(hours=h)], lat, lon) for h in range(5, -1, -1)]
        forecast_solar, ref_solar = six_hour_solar(ssr, prior, solar_hours)
        wind = np.hypot(u, v)
        ref_wind = np.hypot(on_grid(ref['10u', valid], lat, lon), on_grid(ref['10v', valid], lat, lon))
        runs.append((step, lat, lon, wind, ref_wind, forecast_solar, ref_solar))
    if not np.array_equal(runs[0][1], runs[1][1]) or not np.array_equal(runs[0][2], runs[1][2]):
        raise ValueError('Forecast grids differ')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    fig, axes = plt.subplots(2, 2, figsize=(13, 12), subplot_kw={'projection': ccrs.PlateCarree()}, constrained_layout=True)
    for row, (step, lat, lon, wind, ref_wind, solar, ref_solar) in enumerate(runs):
        lats, lons = np.unique(lat), np.unique(lon)
        order = np.lexsort((lon, lat))
        if len(lats) * len(lons) != len(lat):
            raise ValueError('Grid is not rectangular')
        for col, (pred, obs, title, minimum) in enumerate([(wind, ref_wind, '10 m wind speed', 1.), (solar, ref_solar, '6-hour net solar radiation', 20.)]):
            if not np.isfinite(pred).all() or not np.isfinite(obs).all():
                raise ValueError('Non-finite inputs')
            values = absolute_relative_error(np.array([pred]), np.array([obs]), minimum)
            grid = values[order].reshape(len(lats), len(lons))
            ax = axes[row, col]
            im = ax.pcolormesh(lons, lats, np.ma.masked_invalid(grid), transform=ccrs.PlateCarree(), cmap='YlOrRd', vmin=0, vmax=100, shading='nearest')
            ax.coastlines(resolution='110m'); ax.set_extent([-12, 4, 48, 62]); ax.gridlines(draw_labels={'left':'y','bottom':'x'}, linestyle=':', alpha=.5)
            ax.set_title(f'{title} · +{step} h')
            fig.colorbar(im, ax=ax, shrink=.7, label='Absolute relative error (%)', extend='max')
            print(f'+{step} h {title}: {np.isfinite(values).sum()}/{len(values)} grid points above reference threshold')
    fig.suptitle(f'100 × |forecast − ERA5| / ERA5 · valid {valid:%Y-%m-%d %H:%M UTC}\nSolar covers previous 6 hours; ERA5 <1 m/s wind or <20 W/m² solar masked; colours capped at 100%')
    args.output.parent.mkdir(parents=True, exist_ok=True);fig.savefig(args.output, dpi=150);plt.close(fig);print('Saved', args.output)


if __name__ == '__main__':
    main()
