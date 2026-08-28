"""Learn day-ahead wind and solar forecasting with an ERA5 backtest.

This is an educational *historical* experiment.  ERA5 is a reanalysis: it is
used here as both the historical input and the truth against which predictions
are checked.  It is not tomorrow's live weather forecast.

The script trains two separate gradient-boosted tree models:

* wind model -> 100 m wind speed (m/s) at operational wind-farm grid cells;
* solar model -> direct + diffuse surface irradiance (W/m2) at operational
  solar-farm grid cells.

Only information available by 23:00 UTC on the preceding day is used: values
from 24, 48, and 168 hours ago, calendar features, location, and (for solar)
deterministic top-of-atmosphere radiation/solar position.  The last N days are
held out in time, so the reported scores are genuine out-of-sample scores.

Example:

    python UKDayAheadWeatherML.py \
        --cutout uk-era5-2025-01-02-to-2026-01-02.nc \
        --forecast-day 2026-01-01

Outputs are weather predictions, not electricity or energy.  Turbine power
curves and PV configurations belong in the next conversion stage.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Transformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


DEFAULT_CUTOUT = Path("uk-era5-2025-01-02-to-2026-01-02.nc")
DEFAULT_FARMS = Path("REPD_Publication_Q2_2026.csv")
DEFAULT_OUTPUT_DIR = Path("outputs/day-ahead-weather")

LAGS = (24, 48, 168)
MAX_LAG = max(LAGS)
WIND_TECHNOLOGIES = {"Wind Onshore", "Wind Offshore"}
SOLAR_TECHNOLOGIES = {"Solar Photovoltaics"}


@dataclass
class SiteWeather:
    """Weather arrays and coordinates for the unique grid cells of one fleet."""

    farms: pd.DataFrame
    cells: pd.DataFrame
    target: np.ndarray
    extras: dict[str, np.ndarray]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cutout",
        type=Path,
        default=DEFAULT_CUTOUT,
        help="One-year atlite ERA5 NetCDF cutout.",
    )
    parser.add_argument(
        "--farms",
        type=Path,
        default=DEFAULT_FARMS,
        help="Renewable Energy Planning Database CSV.",
    )
    parser.add_argument(
        "--forecast-day",
        help=(
            "Historical day to predict (YYYY-MM-DD). By default, use the last "
            "complete day in the cutout."
        ),
    )
    parser.add_argument(
        "--test-days",
        type=int,
        default=30,
        help="Number of final days held out for honest evaluation (default: 30).",
    )
    parser.add_argument(
        "--max-training-rows",
        type=int,
        default=500_000,
        help="Maximum randomly sampled time/cell rows per model (default: 500000).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for CSV, JSON, and map outputs.",
    )
    return parser.parse_args()


def open_cutout(path: Path) -> xr.Dataset:
    if not path.exists():
        raise SystemExit(
            f"Cutout not found: {path}\n"
            "Run UKWeather.py after configuring CDS access to download the "
            "one-year cutout, then run this script again."
        )

    dataset = xr.open_dataset(path)
    required = {
        "wnd100m",
        "influx_direct",
        "influx_diffuse",
        "influx_toa",
        "solar_altitude",
    }
    missing = sorted(required.difference(dataset.data_vars))
    if missing:
        dataset.close()
        raise SystemExit(f"The cutout is missing required variables: {missing}")

    times = pd.DatetimeIndex(dataset.time.values)
    if not times.is_monotonic_increasing or times.has_duplicates:
        dataset.close()
        raise SystemExit("The cutout time coordinate must be sorted and unique.")
    if len(times) < 2 or not np.all(np.diff(times.values) == np.timedelta64(1, "h")):
        dataset.close()
        raise SystemExit("The model needs a continuous hourly cutout with no gaps.")

    return dataset


def clean_text(series: pd.Series) -> pd.Series:
    """Remove whitespace that sometimes appears in the REPD CSV fields."""
    return series.astype("string").str.strip()


def load_and_locate_farms(path: Path, dataset: xr.Dataset) -> pd.DataFrame:
    """Load operational farms and map their BNG coordinates to ERA5 cells."""
    if not path.exists():
        raise SystemExit(f"Farm CSV not found: {path}")

    farms = pd.read_csv(path, encoding="cp1252", low_memory=False)
    required = {
        "Ref ID",
        "Site Name",
        "Technology Type",
        "Development Status (short)",
        "Installed Capacity (MWelec)",
        "Country",
        "X-coordinate",
        "Y-coordinate",
    }
    missing = sorted(required.difference(farms.columns))
    if missing:
        raise SystemExit(f"The farm CSV is missing columns: {missing}")

    for column in ["Technology Type", "Development Status (short)", "Country"]:
        farms[column] = clean_text(farms[column])

    wanted_technologies = WIND_TECHNOLOGIES | SOLAR_TECHNOLOGIES
    farms = farms.loc[
        farms["Development Status (short)"].eq("Operational")
        & farms["Technology Type"].isin(wanted_technologies)
    ].copy()

    for column in [
        "Installed Capacity (MWelec)",
        "X-coordinate",
        "Y-coordinate",
    ]:
        farms[column] = pd.to_numeric(
            clean_text(farms[column]), errors="coerce"
        )

    before_coordinates = len(farms)
    farms = farms.dropna(subset=["X-coordinate", "Y-coordinate"])
    dropped_coordinates = before_coordinates - len(farms)

    # REPD publishes OSGB36 / British National Grid eastings and northings.
    # The same CRS is used for its Northern Ireland rows in this publication.
    transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    longitude, latitude = transformer.transform(
        farms["X-coordinate"].to_numpy(), farms["Y-coordinate"].to_numpy()
    )
    farms["longitude"] = longitude
    farms["latitude"] = latitude

    x_values = dataset.x.values.astype(float)
    y_values = dataset.y.values.astype(float)
    inside = farms["longitude"].between(x_values.min(), x_values.max()) & farms[
        "latitude"
    ].between(y_values.min(), y_values.max())
    dropped_outside = int((~inside).sum())
    farms = farms.loc[inside].copy()

    farms["grid_x_index"] = np.abs(
        farms["longitude"].to_numpy()[:, None] - x_values[None, :]
    ).argmin(axis=1)
    farms["grid_y_index"] = np.abs(
        farms["latitude"].to_numpy()[:, None] - y_values[None, :]
    ).argmin(axis=1)
    farms["grid_longitude"] = x_values[farms["grid_x_index"].to_numpy()]
    farms["grid_latitude"] = y_values[farms["grid_y_index"].to_numpy()]
    farms["grid_cell_id"] = (
        farms["grid_y_index"].astype(str)
        + ":"
        + farms["grid_x_index"].astype(str)
    )
    farms["fleet"] = np.where(
        farms["Technology Type"].isin(WIND_TECHNOLOGIES), "wind", "solar"
    )

    farms = farms.rename(
        columns={
            "Ref ID": "ref_id",
            "Site Name": "site_name",
            "Technology Type": "technology_type",
            "Country": "country",
            "Installed Capacity (MWelec)": "installed_capacity_mw",
        }
    )
    farms = farms.reset_index(drop=True)

    print(
        f"Loaded {len(farms):,} operational farms "
        f"({(farms.fleet == 'wind').sum():,} wind, "
        f"{(farms.fleet == 'solar').sum():,} solar)."
    )
    print(
        f"Dropped {dropped_coordinates} rows without coordinates and "
        f"{dropped_outside} outside the cutout."
    )
    return farms


def extract_site_weather(
    dataset: xr.Dataset, farms: pd.DataFrame, fleet: str
) -> SiteWeather:
    """Extract time series once per unique grid cell, not once per farm."""
    fleet_farms = farms.loc[farms["fleet"].eq(fleet)].copy()
    cells = (
        fleet_farms[
            [
                "grid_cell_id",
                "grid_x_index",
                "grid_y_index",
                "grid_longitude",
                "grid_latitude",
            ]
        ]
        .drop_duplicates("grid_cell_id")
        .sort_values(["grid_y_index", "grid_x_index"])
        .reset_index(drop=True)
    )
    cells["cell_position"] = np.arange(len(cells))
    cell_position = cells.set_index("grid_cell_id")["cell_position"]
    fleet_farms["cell_position"] = (
        fleet_farms["grid_cell_id"].map(cell_position).astype(int)
    )

    vector_x = xr.DataArray(cells["grid_x_index"].to_numpy(), dims="cell")
    vector_y = xr.DataArray(cells["grid_y_index"].to_numpy(), dims="cell")

    def extract(variable: str) -> np.ndarray:
        return (
            dataset[variable]
            .isel(x=vector_x, y=vector_y)
            .transpose("time", "cell")
            .values.astype(np.float32)
        )

    if fleet == "wind":
        target = extract("wnd100m")
        extras = {}
        if "wnd_azimuth" in dataset:
            extras["wind_direction"] = extract("wnd_azimuth")
        if "roughness" in dataset:
            extras["roughness"] = extract("roughness")
    else:
        target = extract("influx_direct") + extract("influx_diffuse")
        extras = {
            "influx_toa": extract("influx_toa"),
            "solar_altitude": extract("solar_altitude"),
        }

    print(
        f"{fleet.capitalize()}: {len(fleet_farms):,} farms use "
        f"{len(cells):,} unique ERA5 cells."
    )
    return SiteWeather(fleet_farms, cells, target, extras)


def choose_periods(
    times: pd.DatetimeIndex, forecast_day_text: str | None, test_days: int
) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    if test_days < 1:
        raise SystemExit("--test-days must be at least 1.")

    # The extra midnight is required because atlite labels solar radiation by
    # the end of its one-hour accumulation interval.
    last_day = times[-1].normalize() - pd.Timedelta(days=1)
    forecast_day = (
        pd.Timestamp(forecast_day_text).normalize()
        if forecast_day_text
        else last_day
    )
    if forecast_day > last_day:
        raise SystemExit(
            f"Forecast day {forecast_day.date()} needs data through the next "
            f"midnight; the last possible day is {last_day.date()}."
        )

    test_start = forecast_day - pd.Timedelta(days=test_days - 1)
    train_stop = int(times.searchsorted(test_start, side="left"))
    minimum_training_hours = 60 * 24
    if train_stop - MAX_LAG < minimum_training_hours:
        raise SystemExit(
            "There is not enough history before the held-out period. The "
            "script requires at least 60 training days plus seven lag days; "
            "a full year is recommended."
        )
    return test_start, forecast_day, train_stop


def row_indices(
    first_time: int,
    last_time: int,
    number_of_cells: int,
    maximum_rows: int | None,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return time/cell pairs, uniformly sampling when the table is large."""
    number_of_times = last_time - first_time
    possible_rows = number_of_times * number_of_cells
    if possible_rows <= 0:
        raise ValueError("No rows are available for this period.")

    if maximum_rows is not None and possible_rows > maximum_rows:
        generator = np.random.default_rng(random_seed)
        flat = generator.choice(possible_rows, size=maximum_rows, replace=False)
    else:
        flat = np.arange(possible_rows)

    time_index = first_time + flat // number_of_cells
    cell_index = flat % number_of_cells
    return time_index.astype(int), cell_index.astype(int)


def make_features(
    weather: SiteWeather,
    times: pd.DatetimeIndex,
    time_index: np.ndarray,
    cell_index: np.ndarray,
    fleet: str,
) -> tuple[np.ndarray, list[str]]:
    """Construct predictors using only historical or deterministic values."""
    target_times = times[time_index]
    if fleet == "solar":
        # Radiation values describe the hour ending at the timestamp, so use
        # the interval midpoint for hour/day calendar features.
        target_times = target_times - pd.Timedelta(minutes=30)

    hour_angle = 2.0 * np.pi * target_times.hour.to_numpy() / 24.0
    year_angle = 2.0 * np.pi * (
        target_times.dayofyear.to_numpy() - 1
    ) / 365.2425

    columns = [
        weather.target[time_index - lag, cell_index] for lag in LAGS
    ]
    names = [f"target_lag_{lag}h" for lag in LAGS]
    columns.extend(
        [
            np.sin(hour_angle),
            np.cos(hour_angle),
            np.sin(year_angle),
            np.cos(year_angle),
            weather.cells["grid_longitude"].to_numpy()[cell_index],
            weather.cells["grid_latitude"].to_numpy()[cell_index],
        ]
    )
    names.extend(
        ["hour_sin", "hour_cos", "year_sin", "year_cos", "longitude", "latitude"]
    )

    if fleet == "wind":
        if "wind_direction" in weather.extras:
            direction = weather.extras["wind_direction"][time_index - 24, cell_index]
            columns.extend([np.sin(direction), np.cos(direction)])
            names.extend(["wind_direction_sin_lag_24h", "wind_direction_cos_lag_24h"])
        if "roughness" in weather.extras:
            roughness = weather.extras["roughness"][time_index - 24, cell_index]
            columns.append(np.log1p(np.maximum(roughness, 0.0)))
            names.append("log_roughness_lag_24h")
    else:
        columns.extend(
            [
                weather.extras["influx_toa"][time_index, cell_index],
                weather.extras["solar_altitude"][time_index, cell_index],
            ]
        )
        names.extend(["influx_toa", "solar_altitude"])

    return np.column_stack(columns).astype(np.float32), names


def fit_and_evaluate(
    weather: SiteWeather,
    times: pd.DatetimeIndex,
    fleet: str,
    train_stop: int,
    test_time_index: np.ndarray,
    max_training_rows: int,
) -> tuple[HistGradientBoostingRegressor, np.ndarray, np.ndarray, dict[str, float]]:
    """Fit one fleet model and compare it with previous-day persistence."""
    train_time, train_cell = row_indices(
        MAX_LAG,
        train_stop,
        len(weather.cells),
        max_training_rows,
        random_seed=42,
    )
    train_x, feature_names = make_features(
        weather, times, train_time, train_cell, fleet
    )
    train_y = weather.target[train_time, train_cell]
    finite_train = np.isfinite(train_y) & np.isfinite(train_x).all(axis=1)
    train_x = train_x[finite_train]
    train_y = train_y[finite_train]

    model = HistGradientBoostingRegressor(
        learning_rate=0.07,
        max_iter=220,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        random_state=42,
    )
    print(
        f"Training {fleet} model on {len(train_y):,} rows and "
        f"{len(feature_names)} features ..."
    )
    model.fit(train_x, train_y)

    test_time, test_cell = row_indices(
        int(test_time_index[0]),
        int(test_time_index[-1]) + 1,
        len(weather.cells),
        maximum_rows=None,
        random_seed=42,
    )
    test_x, _ = make_features(weather, times, test_time, test_cell, fleet)
    actual = weather.target[test_time, test_cell]
    persistence = weather.target[test_time - 24, test_cell]
    finite_test = (
        np.isfinite(actual)
        & np.isfinite(persistence)
        & np.isfinite(test_x).all(axis=1)
    )

    prediction = np.full(actual.shape, np.nan, dtype=np.float32)
    prediction[finite_test] = model.predict(test_x[finite_test])
    prediction = np.maximum(prediction, 0.0)
    persistence = np.maximum(persistence, 0.0)

    scored_actual = actual[finite_test]
    scored_prediction = prediction[finite_test]
    scored_persistence = persistence[finite_test]
    if fleet == "solar":
        daylight = (
            weather.extras["influx_toa"][test_time, test_cell][finite_test] > 20.0
        )
        scored_actual = scored_actual[daylight]
        scored_prediction = scored_prediction[daylight]
        scored_persistence = scored_persistence[daylight]

    model_mae = float(mean_absolute_error(scored_actual, scored_prediction))
    persistence_mae = float(
        mean_absolute_error(scored_actual, scored_persistence)
    )
    metrics = {
        "training_rows": int(len(train_y)),
        "test_rows": int(len(scored_actual)),
        "mae": model_mae,
        "rmse": float(np.sqrt(mean_squared_error(scored_actual, scored_prediction))),
        "r2": float(r2_score(scored_actual, scored_prediction)),
        "persistence_mae": persistence_mae,
        "mae_skill_vs_persistence": (
            float(1.0 - model_mae / persistence_mae)
            if persistence_mae > 0
            else float("nan")
        ),
    }
    if fleet == "solar":
        metrics["scoring_note"] = "Solar metrics use daylight rows (TOA > 20 W/m2)."
    return model, prediction, persistence, metrics


def test_indices(
    times: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    forecast_day: pd.Timestamp,
    fleet: str,
) -> np.ndarray:
    end = forecast_day + pd.Timedelta(days=1)
    if fleet == "wind":
        mask = (times >= test_start) & (times < end)
    else:
        mask = (times > test_start) & (times <= end)
    indices = np.flatnonzero(mask)
    if len(indices) == 0 or np.any(np.diff(indices) != 1):
        raise SystemExit(f"The cutout does not fully cover the {fleet} test period.")
    return indices


def write_farm_forecast(
    weather: SiteWeather,
    times: pd.DatetimeIndex,
    fleet: str,
    test_time_index: np.ndarray,
    prediction: np.ndarray,
    persistence: np.ndarray,
    forecast_day: pd.Timestamp,
    output_path: Path,
) -> pd.DataFrame:
    """Expand unique-cell predictions back to each farm for the final day."""
    day_end = forecast_day + pd.Timedelta(days=1)
    if fleet == "wind":
        final_mask = (times[test_time_index] >= forecast_day) & (
            times[test_time_index] < day_end
        )
        time_label = "valid_time_utc"
        prediction_name = "predicted_wind_speed_100m_ms"
        actual_name = "era5_actual_wind_speed_100m_ms"
        persistence_name = "persistence_wind_speed_100m_ms"
    else:
        final_mask = (times[test_time_index] > forecast_day) & (
            times[test_time_index] <= day_end
        )
        time_label = "interval_end_utc"
        prediction_name = "predicted_surface_irradiance_wm2"
        actual_name = "era5_actual_surface_irradiance_wm2"
        persistence_name = "persistence_surface_irradiance_wm2"

    day_time_index = test_time_index[final_mask]
    if len(day_time_index) != 24:
        raise SystemExit(
            f"Expected 24 {fleet} hours for {forecast_day.date()}, found "
            f"{len(day_time_index)}."
        )

    number_of_cells = len(weather.cells)
    matrix_prediction = prediction.reshape(-1, number_of_cells)[final_mask]
    matrix_persistence = persistence.reshape(-1, number_of_cells)[final_mask]
    matrix_actual = weather.target[day_time_index]

    farms = weather.farms.reset_index(drop=True)
    farm_cells = farms["cell_position"].to_numpy()
    number_of_farms = len(farms)
    repeated_times = np.repeat(times[day_time_index].to_numpy(), number_of_farms)
    repeated_farms = farms.iloc[np.tile(np.arange(number_of_farms), 24)].reset_index(
        drop=True
    )
    selected_columns = [
        "ref_id",
        "site_name",
        "technology_type",
        "country",
        "installed_capacity_mw",
        "longitude",
        "latitude",
        "grid_longitude",
        "grid_latitude",
        "grid_cell_id",
    ]
    result = repeated_farms[selected_columns].copy()
    result.insert(0, time_label, repeated_times)
    result.insert(0, "forecast_issue_utc", forecast_day - pd.Timedelta(hours=1))
    result[prediction_name] = matrix_prediction[:, farm_cells].reshape(-1)
    result[actual_name] = matrix_actual[:, farm_cells].reshape(-1)
    result[persistence_name] = matrix_persistence[:, farm_cells].reshape(-1)
    result.to_csv(output_path, index=False)
    print(f"Saved {fleet} farm forecasts to {output_path.resolve()}")
    return result


def plot_daily_farm_maps(
    wind_table: pd.DataFrame,
    solar_table: pd.DataFrame,
    forecast_day: pd.Timestamp,
    output_path: Path,
) -> None:
    """Plot the daily mean prediction at every operational farm."""
    wind_daily = wind_table.groupby("ref_id", as_index=False).agg(
        longitude=("longitude", "first"),
        latitude=("latitude", "first"),
        value=("predicted_wind_speed_100m_ms", "mean"),
    )
    solar_daily = solar_table.groupby("ref_id", as_index=False).agg(
        longitude=("longitude", "first"),
        latitude=("latitude", "first"),
        value=("predicted_surface_irradiance_wm2", "mean"),
    )

    projection = ccrs.PlateCarree()
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(11, 8),
        subplot_kw={"projection": projection},
        constrained_layout=True,
    )
    specifications = [
        (wind_daily, "Wind farms: predicted 100 m wind", "viridis", "m s$^{-1}$"),
        (
            solar_daily,
            "Solar farms: predicted surface irradiance",
            "YlOrRd",
            "W m$^{-2}$",
        ),
    ]
    for axis, (table, title, colour_map, unit) in zip(axes, specifications):
        axis.set_extent([-8.75, 2.25, 49.5, 61.25], crs=projection)
        # The 50 m Natural Earth layers are already cached by the original UK
        # plotting example and are sufficiently detailed at national scale.
        axis.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#eeeeee")
        axis.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#dceef8")
        axis.coastlines(resolution="50m", linewidth=0.7)
        axis.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.4)
        points = axis.scatter(
            table["longitude"],
            table["latitude"],
            c=table["value"],
            cmap=colour_map,
            s=10,
            alpha=0.8,
            linewidths=0,
            transform=projection,
        )
        colour_bar = fig.colorbar(points, ax=axis, orientation="horizontal", pad=0.03)
        colour_bar.set_label(unit)
        axis.set_title(title)

    fig.suptitle(
        f"Historical day-ahead ML backtest — {forecast_day.date()} (UTC)",
        fontsize=14,
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved prediction maps to {output_path.resolve()}")


def print_metrics(fleet: str, metrics: dict[str, float]) -> None:
    unit = "m/s" if fleet == "wind" else "W/m2"
    print(f"\n{fleet.capitalize()} held-out metrics:")
    print(f"  MAE:                    {metrics['mae']:.3f} {unit}")
    print(f"  RMSE:                   {metrics['rmse']:.3f} {unit}")
    print(f"  R2:                     {metrics['r2']:.3f}")
    print(f"  Previous-day MAE:       {metrics['persistence_mae']:.3f} {unit}")
    print(
        "  Skill vs persistence:   "
        f"{100.0 * metrics['mae_skill_vs_persistence']:.1f}% "
        "(positive is better)"
    )


def main() -> None:
    arguments = parse_arguments()
    if arguments.max_training_rows < 1:
        raise SystemExit("--max-training-rows must be at least 1.")

    dataset = open_cutout(arguments.cutout)
    try:
        times = pd.DatetimeIndex(dataset.time.values)
        test_start, forecast_day, train_stop = choose_periods(
            times, arguments.forecast_day, arguments.test_days
        )
        print(
            f"Training targets end before {test_start} UTC; evaluating "
            f"{arguments.test_days} day(s) through {forecast_day.date()}."
        )

        farms = load_and_locate_farms(arguments.farms, dataset)
        if not set(farms["fleet"]).issuperset({"wind", "solar"}):
            raise SystemExit("Both operational wind and solar farms are required.")

        arguments.output_dir.mkdir(parents=True, exist_ok=True)
        tables: dict[str, pd.DataFrame] = {}
        all_metrics: dict[str, dict[str, float]] = {}

        for fleet in ["wind", "solar"]:
            weather = extract_site_weather(dataset, farms, fleet)
            evaluation_times = test_indices(times, test_start, forecast_day, fleet)
            _, prediction, persistence, metrics = fit_and_evaluate(
                weather,
                times,
                fleet,
                train_stop,
                evaluation_times,
                arguments.max_training_rows,
            )
            all_metrics[fleet] = metrics
            print_metrics(fleet, metrics)
            tables[fleet] = write_farm_forecast(
                weather,
                times,
                fleet,
                evaluation_times,
                prediction,
                persistence,
                forecast_day,
                arguments.output_dir / f"{fleet}_farm_weather_forecast.csv",
            )

        metrics_path = arguments.output_dir / "backtest_metrics.json"
        metrics_path.write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
        print(f"Saved metrics to {metrics_path.resolve()}")
        plot_daily_farm_maps(
            tables["wind"],
            tables["solar"],
            forecast_day,
            arguments.output_dir / "farm_weather_forecast_maps.png",
        )
    finally:
        dataset.close()


if __name__ == "__main__":
    main()
