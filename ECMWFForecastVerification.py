"""Compare selected-time ECMWF IFS forecasts with an ERA5T reference.

The default worked case is 20 August 2026 at 00:00 and 12:00 UTC.  Wind is
instantaneous at each selected time.  ECMWF solar radiation is accumulated, so
solar is compared as the three-hour mean interval starting at each selected
time (00:00-03:00 and 12:00-15:00 by default).

Relative error is defined with ERA5T in the denominator:

    relative error [%] = 100 * (IFS - ERA5T) / ERA5T

Cells with near-zero ERA5T values are masked because relative error there is
undefined or unstable.  ERA5T is an observation-informed gridded reanalysis,
not a direct instrument measurement in every grid cell.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_VALID_DAY = "2026-08-20"
DEFAULT_HOURS = [0, 12]
DEFAULT_FORECAST_DIRECTORY = Path("ecmwf-data")
DEFAULT_OUTPUT_DIRECTORY = Path("outputs/ecmwf-verification")
UK_EXTENT = [-8.75, 2.25, 49.5, 61.25]
RELATIVE_ERROR_THRESHOLDS = {
    "wind": 0.5,   # m/s
    "solar": 10.0,  # W/m2
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--valid-day",
        default=DEFAULT_VALID_DAY,
        help="UTC day being forecast, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        nargs="+",
        default=DEFAULT_HOURS,
        help="UTC hours to compare; open IFS hours must be multiples of 3.",
    )
    parser.add_argument(
        "--run-date",
        help="Forecast run date. Default: the day before --valid-day.",
    )
    parser.add_argument(
        "--run-hour",
        type=int,
        choices=[0, 6, 12, 18],
        default=12,
        help="Forecast initialization hour in UTC (default: 12).",
    )
    parser.add_argument(
        "--source",
        choices=["aws", "ecmwf", "azure", "google"],
        default="aws",
        help="ECMWF Open Data mirror (default: aws).",
    )
    parser.add_argument(
        "--reference-cutout",
        type=Path,
        help=(
            "atlite ERA5 NetCDF file. Default: infer a one-day filename from "
            "--valid-day."
        ),
    )
    parser.add_argument(
        "--download-era5",
        action="store_true",
        help="If the reference is missing, try to retrieve it through atlite/CDS.",
    )
    parser.add_argument(
        "--forecast-dir",
        type=Path,
        default=DEFAULT_FORECAST_DIRECTORY,
        help="Directory used to cache raw GRIB2 forecast files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="Directory for maps, metrics, and comparison NetCDF.",
    )
    return parser.parse_args()


def as_day(value: str, option_name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except ValueError as error:
        raise SystemExit(f"{option_name} must use YYYY-MM-DD format.") from error
    if timestamp != timestamp.normalize():
        raise SystemExit(f"{option_name} must be a date without a time.")
    return timestamp


def forecast_initialization(
    arguments: argparse.Namespace,
) -> tuple[pd.Timestamp, pd.Timestamp, list[int]]:
    valid_day = as_day(arguments.valid_day, "--valid-day")
    run_day = (
        as_day(arguments.run_date, "--run-date")
        if arguments.run_date
        else valid_day - pd.Timedelta(days=1)
    )
    initialization = run_day + pd.Timedelta(hours=arguments.run_hour)
    if initialization >= valid_day:
        raise SystemExit(
            "The forecast initialization must precede the start of the valid day."
        )

    hours = sorted(set(arguments.hours))
    if not hours or any(hour < 0 or hour > 21 or hour % 3 for hour in hours):
        raise SystemExit(
            "--hours must contain unique UTC hours from 0 through 21 in "
            "three-hour increments."
        )
    return valid_day, initialization, hours


def forecast_steps(
    valid_day: pd.Timestamp,
    initialization: pd.Timestamp,
    hours: list[int],
) -> tuple[list[int], dict[int, tuple[int, int]]]:
    """Translate valid UTC hours into lead times from model initialization."""
    day_start_step = int((valid_day - initialization) / pd.Timedelta(hours=1))
    wind_steps = [day_start_step + hour for hour in hours]
    solar_intervals = {
        hour: (day_start_step + hour, day_start_step + hour + 3)
        for hour in hours
    }
    all_steps = wind_steps + [step for pair in solar_intervals.values() for step in pair]
    if min(all_steps) < 0 or any(step % 3 for step in all_steps):
        raise SystemExit(
            "The selected run and valid times do not fall on IFS three-hour steps."
        )
    if max(all_steps) > 144:
        raise SystemExit(
            "This example expects the three-hourly portion of IFS "
            "(lead time no greater than 144 hours)."
        )
    return wind_steps, solar_intervals


def download_forecast(
    valid_day: pd.Timestamp,
    initialization: pd.Timestamp,
    hours: list[int],
    source: str,
    forecast_directory: Path,
) -> tuple[Path, Path, list[int], dict[int, tuple[int, int]]]:
    """Retrieve only the selected wind and solar GRIB messages."""
    try:
        from ecmwf.opendata import Client
    except ImportError as error:
        raise SystemExit(
            "Install ECMWF's client first:\n"
            "python -m pip install ecmwf-opendata"
        ) from error

    wind_steps, solar_intervals = forecast_steps(
        valid_day, initialization, hours
    )
    solar_steps = sorted(
        {step for pair in solar_intervals.values() for step in pair}
    )
    stamp = initialization.strftime("%Y%m%d-%Hz")
    day_stamp = valid_day.strftime("%Y%m%d")
    hour_stamp = "-".join(f"{hour:02d}" for hour in hours)
    forecast_directory.mkdir(parents=True, exist_ok=True)
    wind_path = forecast_directory / (
        f"ifs-{stamp}-for-{day_stamp}-at-{hour_stamp}-wind.grib2"
    )
    solar_path = forecast_directory / (
        f"ifs-{stamp}-for-{day_stamp}-from-{hour_stamp}-solar.grib2"
    )

    client = Client(
        source=source,
        model="ifs",
        resol="0p25",
        infer_stream_keyword=False,
    )
    common_request = {
        "date": initialization.strftime("%Y-%m-%d"),
        "time": initialization.hour,
        "stream": "oper",
        "type": "fc",
    }

    if not wind_path.exists():
        print(f"Downloading IFS 100 m wind at lead hours {wind_steps} ...")
        client.retrieve(
            **common_request,
            step=wind_steps,
            param=["100u", "100v"],
            target=str(wind_path),
        )
    else:
        print(f"Using cached wind forecast: {wind_path}")

    if not solar_path.exists():
        print(f"Downloading IFS accumulated solar at lead hours {solar_steps} ...")
        client.retrieve(
            **common_request,
            step=solar_steps,
            param="ssrd",
            target=str(solar_path),
        )
    else:
        print(f"Using cached solar forecast: {solar_path}")

    return wind_path, solar_path, wind_steps, solar_intervals


def open_grib(path: Path) -> xr.Dataset:
    """Open GRIB without leaving a persistent cfgrib index beside the data."""
    return xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},
    )


def select_uk(field: xr.DataArray) -> xr.DataArray:
    """Subset descending ECMWF latitude to the ascending atlite UK grid."""
    field = field.sel(
        longitude=slice(UK_EXTENT[0], UK_EXTENT[1]),
        latitude=slice(UK_EXTENT[3], UK_EXTENT[2]),
    )
    return field.rename(latitude="y", longitude="x").sortby("y")


def clean_spatial_field(field: xr.DataArray) -> xr.DataArray:
    """Keep only y/x coordinates before combining selected times."""
    return select_uk(field).reset_coords(drop=True).load()


def calculate_forecast_fields(
    wind_path: Path,
    solar_path: Path,
    valid_day: pd.Timestamp,
    hours: list[int],
    wind_steps: list[int],
    solar_intervals: dict[int, tuple[int, int]],
) -> dict[str, xr.DataArray]:
    """Convert IFS components and accumulations at the selected times."""
    valid_times = pd.DatetimeIndex(
        [valid_day + pd.Timedelta(hours=hour) for hour in hours],
        name="valid_time",
    )

    wind_fields: list[xr.DataArray] = []
    with open_grib(wind_path) as wind_dataset:
        for step in wind_steps:
            selected = wind_dataset.sel(step=pd.Timedelta(hours=step))
            speed = np.hypot(selected["u100"], selected["v100"])
            wind_fields.append(clean_spatial_field(speed))
    forecast_wind = xr.concat(wind_fields, dim=valid_times)

    solar_fields: list[xr.DataArray] = []
    with open_grib(solar_path) as solar_dataset:
        for hour in hours:
            start_step, end_step = solar_intervals[hour]
            start_energy = solar_dataset["ssrd"].sel(
                step=pd.Timedelta(hours=start_step)
            )
            end_energy = solar_dataset["ssrd"].sel(
                step=pd.Timedelta(hours=end_step)
            )
            # ssrd is accumulated J/m2. Difference over 3 h, then divide by
            # seconds to obtain the mean W/m2 for the interval.
            flux = ((end_energy - start_energy) / (3 * 60 * 60)).clip(min=0)
            solar_fields.append(clean_spatial_field(flux))
    forecast_solar = xr.concat(solar_fields, dim=valid_times)

    forecast_wind.name = "forecast_wind_speed_100m"
    forecast_wind.attrs.update(
        long_name="IFS instantaneous 100 m wind speed",
        units="m s-1",
        formula="sqrt(100u**2 + 100v**2)",
    )
    forecast_solar.name = "forecast_surface_solar_radiation"
    forecast_solar.attrs.update(
        long_name="IFS three-hour mean downward surface short-wave radiation",
        units="W m-2",
        interval="Three hours starting at valid_time",
        conversion="(ssrd at interval end - ssrd at interval start) / 10800 seconds",
    )
    return {"wind": forecast_wind, "solar": forecast_solar}


def default_reference_path(valid_day: pd.Timestamp) -> Path:
    next_day = valid_day + pd.Timedelta(days=1)
    return Path(
        f"uk-era5-{valid_day.strftime('%Y-%m-%d')}-to-"
        f"{next_day.strftime('%Y-%m-%d')}.nc"
    )


def check_cds_credentials() -> None:
    credentials = Path.home() / ".cdsapirc"
    if not credentials.exists():
        raise SystemExit(
            "CDS credentials were not found. Configure ~/.cdsapirc first."
        )
    contents = credentials.read_text(encoding="utf-8")
    placeholders = ("YOUR_API_KEY", "PERSONAL-ACCESS-TOKEN", "<PERSONAL")
    if "key:" not in contents or any(value in contents for value in placeholders):
        raise SystemExit("~/.cdsapirc does not contain a real CDS access token.")


def download_era5_reference(path: Path, valid_day: pd.Timestamp) -> None:
    """Prepare the matching ERA5T day once it is published by CDS."""
    import atlite
    from requests.exceptions import HTTPError

    check_cds_credentials()
    next_day = valid_day + pd.Timedelta(days=1)
    cutout = atlite.Cutout(
        path=path,
        module="era5",
        x=slice(UK_EXTENT[0], UK_EXTENT[1]),
        y=slice(UK_EXTENT[2], UK_EXTENT[3]),
        time=slice(valid_day, next_day),
    )
    try:
        cutout.prepare(
            features=["wind", "influx"],
            monthly_requests=True,
            compression=None,
        )
    except HTTPError as error:
        raise SystemExit(
            "CDS rejected the ERA5T request. Check credentials/licence terms, "
            "or the date may still be inside ERA5T's five-day delay.\n"
            f"CDS response: {error}"
        ) from error


def calculate_reference_fields(
    reference_path: Path,
    valid_day: pd.Timestamp,
    hours: list[int],
) -> dict[str, xr.DataArray]:
    """Calculate ERA5T fields with matching times and solar intervals."""
    valid_times = pd.DatetimeIndex(
        [valid_day + pd.Timedelta(hours=hour) for hour in hours],
        name="valid_time",
    )
    wind_fields: list[xr.DataArray] = []
    solar_fields: list[xr.DataArray] = []

    with xr.open_dataset(reference_path) as reference:
        required = {"wnd100m", "influx_direct", "influx_diffuse"}
        missing = sorted(required.difference(reference.data_vars))
        if missing:
            raise ValueError(f"ERA5 reference is missing variables: {missing}")

        for timestamp in valid_times:
            try:
                wind = reference["wnd100m"].sel(time=timestamp)
            except KeyError as error:
                raise ValueError(
                    f"ERA5 does not contain wind at {timestamp}."
                ) from error
            wind_fields.append(wind.reset_coords(drop=True).load())

            interval = reference.sel(
                time=slice(
                    timestamp + pd.Timedelta(hours=1),
                    timestamp + pd.Timedelta(hours=3),
                )
            )
            if interval.sizes["time"] != 3:
                raise ValueError(
                    f"ERA5 needs three solar intervals after {timestamp}; "
                    f"found {interval.sizes['time']}."
                )
            solar = (
                interval["influx_direct"] + interval["influx_diffuse"]
            ).mean("time")
            solar_fields.append(solar.reset_coords(drop=True).load())

    reference_wind = xr.concat(wind_fields, dim=valid_times)
    reference_solar = xr.concat(solar_fields, dim=valid_times)
    reference_wind.name = "reference_wind_speed_100m"
    reference_wind.attrs.update(
        long_name="ERA5T instantaneous 100 m wind speed",
        units="m s-1",
    )
    reference_solar.name = "reference_surface_solar_radiation"
    reference_solar.attrs.update(
        long_name="ERA5T three-hour mean downward surface short-wave radiation",
        units="W m-2",
        interval="Three hours starting at valid_time",
    )
    return {"wind": reference_wind, "solar": reference_solar}


def align_and_calculate_errors(
    forecast: dict[str, xr.DataArray],
    reference: dict[str, xr.DataArray],
) -> tuple[xr.Dataset, list[dict[str, float | str]]]:
    """Calculate signed absolute and ERA5T-relative percentage errors."""
    fields: dict[str, xr.DataArray] = {}
    metrics: list[dict[str, float | str]] = []
    display_names = {
        "wind": "100 m wind speed",
        "solar": "surface solar radiation",
    }

    for key in ["wind", "solar"]:
        forecast_field, reference_field = xr.align(
            forecast[key], reference[key], join="exact"
        )
        absolute_error = forecast_field - reference_field
        absolute_error.name = f"{key}_forecast_error"
        absolute_error.attrs.update(
            long_name=f"IFS minus ERA5T {display_names[key]}",
            units=forecast_field.attrs["units"],
            sign_convention="positive means IFS is higher than ERA5T",
        )

        threshold = RELATIVE_ERROR_THRESHOLDS[key]
        relative_error = xr.where(
            np.abs(reference_field) >= threshold,
            100.0 * absolute_error / reference_field,
            np.nan,
        )
        relative_error.name = f"{key}_relative_error_percent"
        relative_error.attrs.update(
            long_name=f"ERA5T-relative error in {display_names[key]}",
            units="%",
            formula="100 * (IFS - ERA5T) / ERA5T",
            masked_where=f"abs(ERA5T) < {threshold} {reference_field.attrs['units']}",
        )

        fields[forecast_field.name] = forecast_field
        fields[reference_field.name] = reference_field
        fields[absolute_error.name] = absolute_error
        fields[relative_error.name] = relative_error

        for timestamp in pd.DatetimeIndex(forecast_field.valid_time.values):
            model_at_time = forecast_field.sel(valid_time=timestamp)
            reference_at_time = reference_field.sel(valid_time=timestamp)
            error_at_time = absolute_error.sel(valid_time=timestamp)
            relative_at_time = relative_error.sel(valid_time=timestamp)
            reference_sum = float(reference_at_time.sum())
            relative_bias = (
                100.0 * float(error_at_time.sum()) / reference_sum
                if abs(reference_sum) > 0
                else float("nan")
            )
            finite_relative = np.isfinite(relative_at_time)
            coverage = 100.0 * float(finite_relative.mean())
            mape = (
                float(np.abs(relative_at_time).where(finite_relative).mean())
                if bool(finite_relative.any())
                else float("nan")
            )
            metrics.append(
                {
                    "valid_time_utc": str(timestamp),
                    "variable": display_names[key],
                    "unit": forecast_field.attrs["units"],
                    "forecast_spatial_mean": float(model_at_time.mean()),
                    "era5t_spatial_mean": float(reference_at_time.mean()),
                    "bias": float(error_at_time.mean()),
                    "mae": float(np.abs(error_at_time).mean()),
                    "rmse": float(np.sqrt((error_at_time**2).mean())),
                    "relative_bias_percent": relative_bias,
                    "mean_absolute_percentage_error": mape,
                    "relative_error_valid_cells_percent": coverage,
                }
            )

    return xr.Dataset(fields), metrics


def relative_error_limit(field: xr.DataArray) -> float:
    finite = np.abs(field.values[np.isfinite(field.values)])
    if finite.size == 0:
        return 1.0
    return max(1.0, float(np.nanquantile(finite, 0.98)))


def plot_one_time(
    comparison: xr.Dataset,
    timestamp: pd.Timestamp,
    initialization: pd.Timestamp,
    output_path: Path,
) -> None:
    """Plot forecast, ERA5T, and ERA5T-relative error for one selected time."""
    projection = ccrs.PlateCarree()
    fig, axes = plt.subplots(
        2,
        3,
        figsize=(15, 13),
        subplot_kw={"projection": projection},
        constrained_layout=True,
    )
    rows = [
        (
            "wind",
            comparison["forecast_wind_speed_100m"].sel(valid_time=timestamp),
            comparison["reference_wind_speed_100m"].sel(valid_time=timestamp),
            comparison["wind_relative_error_percent"].sel(valid_time=timestamp),
            "viridis",
            "m s$^{-1}$",
            "instantaneous",
        ),
        (
            "solar",
            comparison["forecast_surface_solar_radiation"].sel(valid_time=timestamp),
            comparison["reference_surface_solar_radiation"].sel(valid_time=timestamp),
            comparison["solar_relative_error_percent"].sel(valid_time=timestamp),
            "YlOrRd",
            "W m$^{-2}$",
            f"mean {timestamp:%H}:00–{(timestamp + pd.Timedelta(hours=3)):%H}:00 UTC",
        ),
    ]
    row_titles = {"wind": "100 m wind speed", "solar": "surface solar radiation"}
    relative_cmap = plt.get_cmap("RdBu_r").copy()
    relative_cmap.set_bad("#d9d9d9")

    for row_index, (key, model, actual, relative, cmap, unit, timing) in enumerate(rows):
        common_min = float(min(model.min(), actual.min()))
        common_max = float(max(model.max(), actual.max()))
        if common_max <= common_min:
            common_max = common_min + 1.0
        limit = relative_error_limit(relative)
        relative_norm = mcolors.TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)

        for column_index, field in enumerate([model, actual, relative]):
            axis = axes[row_index, column_index]
            if column_index < 2:
                image = field.plot.pcolormesh(
                    ax=axis,
                    x="x",
                    y="y",
                    cmap=cmap,
                    vmin=common_min,
                    vmax=common_max,
                    transform=projection,
                    add_colorbar=False,
                )
                colour_bar_unit = unit
                heading = "IFS forecast" if column_index == 0 else "ERA5T reference"
            else:
                image = field.plot.pcolormesh(
                    ax=axis,
                    x="x",
                    y="y",
                    cmap=relative_cmap,
                    norm=relative_norm,
                    transform=projection,
                    add_colorbar=False,
                )
                colour_bar_unit = "%"
                heading = "Relative error: 100 × (IFS − ERA5T) / ERA5T"

            colour_bar = fig.colorbar(
                image,
                ax=axis,
                orientation="horizontal",
                pad=0.035,
                extend="both" if column_index == 2 else "neither",
            )
            colour_bar.set_label(colour_bar_unit)
            axis.set_extent(UK_EXTENT, crs=projection)
            axis.coastlines(resolution="50m", linewidth=0.7)
            axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.4)
            axis.set_title(f"{row_titles[key]} ({timing})\n{heading}")

    fig.suptitle(
        f"ECMWF IFS versus ERA5T — {timestamp} UTC\n"
        f"Forecast initialized {initialization} UTC; gray = undefined relative error",
        fontsize=15,
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_outputs(
    comparison: xr.Dataset,
    metrics: list[dict[str, float | str]],
    valid_day: pd.Timestamp,
    initialization: pd.Timestamp,
    output_directory: Path,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    comparison.attrs.update(
        valid_day=str(valid_day.date()),
        forecast_initialization_utc=str(initialization),
        forecast_source="ECMWF IFS Open Data, 0.25 degree deterministic forecast",
        reference_source="ERA5T via Copernicus CDS and atlite",
        reference_caveat="ERA5T is reanalysis, not direct measurement at every cell",
        error_definition="100 * (IFS - ERA5T) / ERA5T",
    )
    netcdf_path = output_directory / "ecmwf_selected_times_vs_era5t.nc"
    comparison.to_netcdf(netcdf_path)

    metrics_path = output_directory / "selected_times_verification_metrics.csv"
    pd.DataFrame(metrics).to_csv(metrics_path, index=False)

    metadata_path = output_directory / "selected_times_run_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "valid_day": str(valid_day.date()),
                "forecast_initialization_utc": str(initialization),
                "selected_times_utc": [
                    str(value)
                    for value in pd.DatetimeIndex(comparison.valid_time.values)
                ],
                "wind_timing": "instantaneous at valid_time",
                "solar_timing": "three-hour mean interval starting at valid_time",
                "relative_error": "100 * (IFS - ERA5T) / ERA5T",
                "relative_error_thresholds": RELATIVE_ERROR_THRESHOLDS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for timestamp in pd.DatetimeIndex(comparison.valid_time.values):
        map_path = output_directory / (
            f"ecmwf_{timestamp:%Y%m%d_%H%M}_relative_error_maps.png"
        )
        plot_one_time(comparison, timestamp, initialization, map_path)
        print(f"Saved selected-time map: {map_path.resolve()}")

    print(f"Saved comparison fields: {netcdf_path.resolve()}")
    print(f"Saved verification metrics: {metrics_path.resolve()}")


def printable(value: float) -> str:
    return "undefined" if not np.isfinite(value) else f"{value:.3f}"


def print_metrics(metrics: list[dict[str, float | str]]) -> None:
    print("\nSpatial verification over the UK bounding-box grid:")
    for metric in metrics:
        print(f"\n  {metric['valid_time_utc']} — {metric['variable']}")
        print(f"    Forecast mean: {metric['forecast_spatial_mean']:.3f} {metric['unit']}")
        print(f"    ERA5T mean:    {metric['era5t_spatial_mean']:.3f} {metric['unit']}")
        print(f"    Bias:          {metric['bias']:.3f} {metric['unit']}")
        print(f"    MAE:           {metric['mae']:.3f} {metric['unit']}")
        print(f"    RMSE:          {metric['rmse']:.3f} {metric['unit']}")
        print(
            "    Relative bias: "
            f"{printable(float(metric['relative_bias_percent']))}%"
        )
        print(
            "    MAPE:          "
            f"{printable(float(metric['mean_absolute_percentage_error']))}%"
        )


def main() -> None:
    arguments = parse_arguments()
    valid_day, initialization, hours = forecast_initialization(arguments)
    print(
        f"Valid day:     {valid_day.date()} UTC\n"
        f"Selected UTC:  {', '.join(f'{hour:02d}:00' for hour in hours)}\n"
        f"IFS run:       {initialization} UTC"
    )

    wind_path, solar_path, wind_steps, solar_intervals = download_forecast(
        valid_day,
        initialization,
        hours,
        arguments.source,
        arguments.forecast_dir,
    )
    forecast = calculate_forecast_fields(
        wind_path,
        solar_path,
        valid_day,
        hours,
        wind_steps,
        solar_intervals,
    )

    reference_path = arguments.reference_cutout or default_reference_path(valid_day)
    if not reference_path.exists() and arguments.download_era5:
        download_era5_reference(reference_path, valid_day)
    if not reference_path.exists():
        print(
            f"\nForecast download is complete, but the ERA5T reference is missing:\n"
            f"  {reference_path}\n"
            "ERA5T normally appears about five days after the valid day. Once "
            "available, rerun with --download-era5 or provide "
            "--reference-cutout."
        )
        return

    reference = calculate_reference_fields(reference_path, valid_day, hours)
    comparison, metrics = align_and_calculate_errors(forecast, reference)
    print_metrics(metrics)
    write_outputs(
        comparison,
        metrics,
        valid_day,
        initialization,
        arguments.output_dir,
    )


if __name__ == "__main__":
    main()
