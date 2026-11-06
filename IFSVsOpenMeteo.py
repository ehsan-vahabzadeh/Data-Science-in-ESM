"""Compare three recent UK IFS forecasts delivered by ECMWF and Open-Meteo."""
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end-date', type=date.fromisoformat, help='last initialization date (YYYY-MM-DD, UTC)')
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/ifs-openmeteo'), help='parent directory for maps and tables')
    parser.add_argument('--data-dir', type=Path, default=Path('data/ifs-openmeteo'), help='download cache')
    args = parser.parse_args()
    run_comparison(args)


def run_comparison(args):
    import json
    import math
    import urllib.parse
    import urllib.request
    import numpy as np
    import pandas as pd
    import cartopy
    import cartopy.crs as ccrs
    import cartopy.io.shapereader as shapereader
    import cfgrib
    import eccodes
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ecmwf.opendata import Client
    from shapely.geometry import Point
    from shapely.prepared import prep

    now = datetime.now(timezone.utc)
    end = args.end_date or (now.date() if now.hour >= 12 else now.date() - timedelta(days=1))
    days = [end - timedelta(days=n) for n in (2, 1, 0)]
    output = args.output_dir / f'{days[0]}_to_{end}'
    if output.exists():
        raise SystemExit(f'Output already exists: {output}. Choose a different --output-dir to preserve it.')
    args.data_dir.mkdir(parents=True, exist_ok=True)
    cartopy.config['data_dir'] = args.data_dir / 'cartopy'
    shapes = shapereader.natural_earth(resolution='50m', category='cultural', name='admin_0_countries')
    uk = next((r.geometry for r in shapereader.Reader(shapes).records() if r.attributes.get('ADM0_A3') == 'GBR'), None)
    if uk is None:
        raise ValueError('United Kingdom boundary not found')
    land = prep(uk)
    latitudes = np.arange(49.5, 61.01, 0.5)
    longitudes = np.arange(-8.5, 2.01, 0.5)
    points = [(float(lat), float(lon)) for lat in latitudes for lon in longitudes if land.covers(Point(lon, lat))]
    if not points:
        raise ValueError('No UK grid centres found')
    records = []
    client = Client(source='ecmwf', model='ifs', resol='0p25')
    for day in days:
        grib = args.data_dir / f'ifs-{day}-00.grib2'
        if not grib.exists():
            temporary = grib.with_suffix('.part')
            try:
                print(f'Downloading ECMWF IFS {day} 00 UTC...', flush=True)
                client.retrieve(date=str(day), time=0, stream='oper', type='fc', step=[9, 12], param=['100u', '100v', 'ssrd'], target=str(temporary))
                temporary.replace(grib)
            finally:
                temporary.unlink(missing_ok=True)
        # ECMWF solar is energy accumulated since initialization, not an hourly average.
        solar_steps = {}
        wind_steps = set()
        with grib.open('rb') as stream:
            while (message := eccodes.codes_grib_new_from_file(stream)) is not None:
                try:
                    name = eccodes.codes_get(message, 'shortName')
                    if name in ('ssrd', '100u', '100v'):
                        if str(eccodes.codes_get(message, 'dataDate')) != day.strftime('%Y%m%d') or eccodes.codes_get(message, 'dataTime') != 0:
                            raise ValueError(f'Unexpected ECMWF initialization in {grib}')
                        step = eccodes.codes_get(message, 'endStep')
                        units = eccodes.codes_get(message, 'units')
                        step_type = eccodes.codes_get(message, 'stepType')
                        if name == 'ssrd':
                            if units != 'J m**-2':
                                raise ValueError(f'Unexpected ECMWF solar units: {units}')
                            solar_steps[step] = (step_type, eccodes.codes_get(message, 'startStep'))
                        elif step == 12 and step_type == 'instant' and units == 'm s**-1':
                            wind_steps.add(name)
                finally:
                    eccodes.codes_release(message)
        if any(solar_steps.get(step) != ('accum', 0) for step in (9, 12)):
            raise ValueError(f'Unexpected solar accumulation metadata in {grib}: {solar_steps}')
        if wind_steps != {'100u', '100v'}:
            raise ValueError(f'Missing instantaneous 12-hour wind components in {grib}')
        datasets = cfgrib.open_datasets(str(grib), backend_kwargs={'indexpath': ''})
        wind = next(ds for ds in datasets if 'u100' in ds and 'v100' in ds).sel(latitude=slice(61, 49.5), longitude=slice(-8.5, 2)).load()
        solar = next(ds for ds in datasets if 'ssrd' in ds).sel(latitude=slice(61, 49.5), longitude=slice(-8.5, 2)).load()
        direct = []
        for lat, lon in points:
            w = wind.sel(latitude=lat, longitude=lon, step=np.timedelta64(12, 'h'))
            s = solar.sel(latitude=lat, longitude=lon)
            direct.append((math.hypot(float(w.u100), float(w.v100)), (float(s.ssrd.sel(step=np.timedelta64(12, 'h'))) - float(s.ssrd.sel(step=np.timedelta64(9, 'h')))) / 10800))
        cache = args.data_dir / f'openmeteo-ifs025-{day}-00.json'
        cached = cache.exists()
        if cached:
            payloads = json.loads(cache.read_text())
        else:
            payloads = []
            for start in range(0, len(points), 75):
                batch = points[start:start + 75]
                params = {'latitude': ','.join(str(p[0]) for p in batch), 'longitude': ','.join(str(p[1]) for p in batch), 'elevation': ','.join('nan' for _ in batch), 'run': f'{day}T00:00', 'models': 'ecmwf_ifs025', 'hourly': 'wind_speed_100m,shortwave_radiation', 'wind_speed_unit': 'ms', 'timezone': 'GMT', 'forecast_hours': 13, 'cell_selection': 'nearest'}
                url = 'https://single-runs-api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(params)
                print(f'Downloading Open-Meteo {day}: points {start + 1}–{start + len(batch)} of {len(points)}...', flush=True)
                with urllib.request.urlopen(url, timeout=120) as response:
                    data = json.load(response)
                payloads.extend(data if isinstance(data, list) else [data])
        if len(payloads) != len(points):
            raise ValueError(f'Expected {len(points)} Open-Meteo locations, got {len(payloads)}')
        for (lat, lon), (direct_wind, direct_solar), p in zip(points, direct, payloads):
            if abs(p['latitude'] - lat) > 0.001 or abs(p['longitude'] - lon) > 0.001:
                raise ValueError(f'Open-Meteo returned a different grid point: {(lat, lon)} vs {(p["latitude"], p["longitude"])}')
            units = p['hourly_units']
            if p['utc_offset_seconds'] != 0 or units['wind_speed_100m'] != 'm/s' or units['shortwave_radiation'] != 'W/m²':
                raise ValueError('Unexpected Open-Meteo units or timezone')
            h = p['hourly']
            times = h['time']
            def value(variable, hour):
                stamp = f'{day}T{hour:02}:00'
                if times.count(stamp) != 1:
                    raise ValueError(f'Missing or duplicate forecast time {stamp}')
                result = h[variable][times.index(stamp)]
                if result is None or not math.isfinite(result):
                    raise ValueError(f'Missing {variable} at {stamp}, {(lat, lon)}')
                return float(result)
            om_wind = value('wind_speed_100m', 12)
            om_solar = sum(value('shortwave_radiation', hour) for hour in (10, 11, 12)) / 3
            if not math.isfinite(direct_wind) or not math.isfinite(direct_solar):
                raise ValueError(f'Missing ECMWF value at {(lat, lon)}')
            records.append({'run_date_utc': str(day), 'latitude': lat, 'longitude': lon, 'ecmwf_wind_ms': direct_wind, 'openmeteo_wind_ms': om_wind, 'ecmwf_solar_wm2': direct_solar, 'openmeteo_solar_wm2': om_solar})
        if not cached:
            temporary = cache.with_suffix('.part')
            try:
                temporary.write_text(json.dumps(payloads, allow_nan=False))
                temporary.replace(cache)
            finally:
                temporary.unlink(missing_ok=True)
    frame = pd.DataFrame(records)
    for variable in ('wind', 'solar'):
        unit = 'ms' if variable == 'wind' else 'wm2'
        frame[f'{variable}_difference_{unit}'] = frame[f'openmeteo_{variable}_{unit}'] - frame[f'ecmwf_{variable}_{unit}']
    output.mkdir(parents=True, exist_ok=False)
    frame.to_csv(output / 'grid-points.csv', index=False)
    metadata = {'run_dates_utc': [str(day) for day in days], 'initialization_hour_utc': 0, 'wind_valid_hour_utc': 12, 'solar_interval_utc': '09:00–12:00', 'ecmwf_product': 'IFS operational 0.25 degree', 'openmeteo_model': 'ecmwf_ifs025', 'sampling_degrees': 0.5, 'uk_land_points_per_day': len(points), 'difference': 'Open-Meteo minus ECMWF', 'note': 'Same IFS forecast model, not observations or independent models.'}
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    summary = []
    for day, daily in frame.groupby('run_date_utc', sort=True):
        for var, unit in [('wind', 'ms'), ('solar', 'wm2')]:
            delta = daily[f'{var}_difference_{unit}']
            summary.append({'run_date_utc': day, 'variable': var, 'unit': 'm/s' if var == 'wind' else 'W/m2', 'points': len(daily), 'ecmwf_mean': daily[f'ecmwf_{var}_{unit}'].mean(), 'openmeteo_mean': daily[f'openmeteo_{var}_{unit}'].mean(), 'mean_difference': delta.mean(), 'mean_absolute_provider_difference': delta.abs().mean(), 'maximum_absolute_provider_difference': delta.abs().max()})
        fig, axes = plt.subplots(2, 3, figsize=(13, 11), subplot_kw={'projection': ccrs.PlateCarree()}, constrained_layout=True)
        for row, (var, unit, label) in enumerate([('wind', 'ms', '100 m wind speed (m/s)'), ('solar', 'wm2', 'Solar radiation (W/m²)')]):
            cols = [f'ecmwf_{var}_{unit}', f'openmeteo_{var}_{unit}', f'{var}_difference_{unit}']
            maximum = max(daily[cols[0]].max(), daily[cols[1]].max(), 0.01)
            diffmax = max(daily[cols[2]].abs().max(), 0.01)
            for col, name in enumerate(cols):
                ax = axes[row, col]
                grid = daily.pivot(index='latitude', columns='longitude', values=name).reindex(index=latitudes, columns=longitudes)
                mesh = ax.pcolormesh(longitudes, latitudes, grid, shading='nearest', cmap='RdBu_r' if col == 2 else 'viridis', vmin=-diffmax if col == 2 else 0, vmax=diffmax if col == 2 else maximum, transform=ccrs.PlateCarree())
                ax.add_geometries([uk], crs=ccrs.PlateCarree(), facecolor='none', edgecolor='black', linewidth=0.55)
                ax.set_extent([-8.7, 2.2, 49.5, 61.0])
                ax.set_title(['ECMWF direct', 'Open-Meteo IFS 0.25°', 'Open-Meteo − ECMWF'][col] + '\n' + label, fontsize=10)
                fig.colorbar(mesh, ax=ax, shrink=0.72, pad=0.02)
        fig.suptitle(f'UK land: IFS run {day} 00 UTC, valid 12 UTC (+12 h)\nSolar: mean over 09–12 UTC; points sampled every 0.5°', fontsize=13)
        fig.savefig(output / f'comparison-{day}.png', dpi=150)
        plt.close(fig)
    pd.DataFrame(summary).to_csv(output / 'summary.csv', index=False)
    (output / 'README.txt').write_text('ECMWF IFS 0.25-degree forecast vs Open-Meteo ecmwf_ifs025, same run and lead time. These are two deliveries of the same forecast model, not independent models or observations. Differences are not forecast error. UK land centres sampled at 0.5 degrees; offshore and small unsampled islands are excluded. Wind is instantaneous at 12 UTC. Solar is mean 09–12 UTC; ECMWF accumulated energy is differenced and divided by 10800 seconds, Open-Meteo hourly means ending 10, 11 and 12 UTC are averaged; Open-Meteo interpolates the three-hourly data of this product. Point means are equally weighted, not area- or capacity-weighted.\n')
    print(f'Saved {len(points)} UK grid centres per day and three comparison maps to {output}', flush=True)


if __name__ == '__main__':
    main()
