"""Download one year of UK ERA5 weather data and plot one day's means.

The data period runs from 2025-01-02 00:00 to 2026-01-02 00:00 UTC.  The
extra end point lets us calculate the solar mean for 2026-01-01 correctly:
ERA5 radiation at a timestamp describes the preceding hour.

Before running this script, configure ~/.cdsapirc and accept the ERA5 licence:
https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import atlite
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr
from requests.exceptions import HTTPError


# A one-year interval containing the day that we want to map.  ERA5 times are
# UTC.  The final 00:00 timestamp is needed for the final hour of solar data.
DATA_START = "2026-01-01 00:00"
DATA_END = "2026-01-03 00:00"
MAP_DAY = "2026-01-01"

# A longitude/latitude box around the UK, with a small sea buffer.  ERA5 and
# atlite use x for longitude and y for latitude.
UK_BOUNDS = {
    "x": slice(-8.75, 2.25),
    "y": slice(49.5, 61.25),
}

CUTOUT_PATH = Path("uk-era5-2026-01-01-to-2026-01-03.nc")
OUTPUT_PATH = Path(f"uk-weather-daily-mean-{MAP_DAY}.png")

# ERA5 has coordinates but does not attach city names to grid cells.  These
# points are included to make the longitude/latitude grid more intuitive.
CITIES = {
    "London": (-0.1276, 51.5072),
    "Cardiff": (-3.1791, 51.4816),
    "Edinburgh": (-3.1883, 55.9533),
    "Belfast": (-5.9301, 54.5973),
}

def check_cds_credentials() -> None:
    """Stop early when ~/.cdsapirc is absent or still contains a placeholder."""
    credentials_path = Path.home() / ".cdsapirc"

    if not credentials_path.exists():
        raise SystemExit(
            "CDS credentials were not found. Create ~/.cdsapirc using the two "
            "lines shown at https://cds.climate.copernicus.eu/en/how-to-api"
        )

    contents = credentials_path.read_text(encoding="utf-8")
    placeholders = ("YOUR_API_KEY", "PERSONAL-ACCESS-TOKEN", "<PERSONAL")
    if "key:" not in contents or any(item in contents for item in placeholders):
        raise SystemExit(
            "~/.cdsapirc still has no real CDS personal access token. Replace "
            "the placeholder using https://cds.climate.copernicus.eu/en/how-to-api"
        )


def prepare_cutout() -> atlite.Cutout:
    """Create or reopen the UK cutout and download the requested ERA5 fields."""
    check_cds_credentials()

    cutout = atlite.Cutout(
        path=CUTOUT_PATH,
        module="era5",
        x=UK_BOUNDS["x"],
        y=UK_BOUNDS["y"],
        time=slice(DATA_START, DATA_END),
    )

    try:
        # atlite downloads only features that are missing from an existing
        # cutout.  Monthly requests are easier for CDS to process than one
        # very large annual request.
        cutout.prepare(
            features=["wind", "influx", "temperature"],
            monthly_requests=True,
            compression=None,
        )
    except HTTPError as error:
        raise SystemExit(
            "The CDS request was rejected. Check your ~/.cdsapirc token and "
            "accept the ERA5 licence on the dataset download page.\n"
            f"CDS response: {error}"
        ) from error

    return cutout


def calculate_daily_means(cutout: atlite.Cutout) -> dict[str, xr.DataArray]:
    """Calculate daily mean wind, solar irradiance, and air temperature."""
    day = pd.Timestamp(MAP_DAY)

    # Wind and temperature are instantaneous hourly fields.  Partial-string
    # selection gives the 24 timestamps from 00:00 through 23:00 on MAP_DAY.
    instantaneous_hours = cutout.data.sel(time=MAP_DAY)
    wind = instantaneous_hours["wnd100m"].mean("time")
    temperature = instantaneous_hours["temperature"].mean("time") - 273.15
    temperature.attrs.update(units="degC", long_name="2 metre air temperature")

    # atlite has already converted ERA5 solar energy from J/m2 to hourly mean
    # power in W/m2.  Direct + diffuse is total downward surface irradiance.
    # A timestamp refers to the preceding hour, hence 01:00 ... next-day 00:00.
    solar_hours = cutout.data.sel(
        time=slice(day + pd.Timedelta(hours=1), day + pd.Timedelta(days=1))
    )
    solar = (
        solar_hours["influx_direct"] + solar_hours["influx_diffuse"]
    ).mean("time")
    solar.attrs.update(
        units="W m$^{-2}$", long_name="surface solar irradiance"
    )

    if (
        instantaneous_hours.sizes["time"] != 24
        or solar_hours.sizes["time"] != 24
    ):
        raise ValueError(
            f"{MAP_DAY} is not covered by 24 complete hourly values in the cutout."
        )

    return {
        "100 m wind speed": wind,
        "surface solar irradiance": solar,
        "2 m air temperature": temperature,
    }


def print_dataset_summary(
    cutout: atlite.Cutout, fields: dict[str, xr.DataArray]
) -> None:
    """Show what the NetCDF file contains and sample its nearest city cells."""
    print("\nPrepared xarray dataset:\n")
    print(cutout.data)
    print("\nCoordinates:")
    print("  x = longitude in degrees east")
    print("  y = latitude in degrees north")
    print("  time = hourly UTC timestamp")

    print(f"\nNearest ERA5 grid-cell daily means for {MAP_DAY}:")
    for city, (longitude, latitude) in CITIES.items():
        wind_cell = fields["100 m wind speed"].sel(
            x=longitude, y=latitude, method="nearest"
        )
        solar_cell = fields["surface solar irradiance"].sel(
            x=longitude, y=latitude, method="nearest"
        )
        temperature_cell = fields["2 m air temperature"].sel(
            x=longitude, y=latitude, method="nearest"
        )
        print(
            f"  {city:9s} -> grid ({float(wind_cell.x):6.2f}, "
            f"{float(wind_cell.y):5.2f}): "
            f"wind {float(wind_cell):5.2f} m/s, "
            f"solar {float(solar_cell):6.1f} W/m2, "
            f"temperature {float(temperature_cell):5.1f} degC"
        )


def plot_daily_maps(fields: dict[str, xr.DataArray]) -> None:
    """Plot three daily-mean fields on longitude/latitude UK maps."""
    styles = {
        "100 m wind speed": ("viridis", "m s$^{-1}$"),
        "surface solar irradiance": ("YlOrRd", "W m$^{-2}$"),
        "2 m air temperature": ("coolwarm", "degC"),
    }

    projection = ccrs.PlateCarree()
    fig, axes = plt.subplots(
        nrows=1,
        ncols=3,
        figsize=(16, 7),
        subplot_kw={"projection": projection},
        constrained_layout=True,
    )

    for ax, (name, field) in zip(axes, fields.items()):
        cmap, unit = styles[name]
        image = field.plot.pcolormesh(
            ax=ax,
            x="x",
            y="y",
            transform=projection,
            cmap=cmap,
            add_colorbar=False,
        )
        colorbar = fig.colorbar(image, ax=ax, orientation="horizontal", pad=0.05)
        colorbar.set_label(unit)

        ax.set_extent(
            [
                UK_BOUNDS["x"].start,
                UK_BOUNDS["x"].stop,
                UK_BOUNDS["y"].start,
                UK_BOUNDS["y"].stop,
            ],
            crs=projection,
        )
        ax.coastlines(resolution="10m", linewidth=0.8)
        ax.add_feature(cfeature.BORDERS.with_scale("10m"), linewidth=0.5)
        ax.set_title(name.capitalize())

        gridlines = ax.gridlines(
            draw_labels=True,
            linewidth=0.35,
            color="gray",
            alpha=0.6,
            linestyle="--",
        )
        gridlines.top_labels = False
        gridlines.right_labels = False

        for city, (longitude, latitude) in CITIES.items():
            ax.plot(
                longitude,
                latitude,
                marker="o",
                markersize=3,
                color="black",
                transform=projection,
            )
            ax.text(
                longitude + 0.12,
                latitude + 0.08,
                city,
                fontsize=7,
                color="black",
                transform=projection,
            )

    fig.suptitle(f"UK ERA5 daily means — {MAP_DAY} (UTC)", fontsize=16)
    fig.savefig(OUTPUT_PATH, dpi=200, bbox_inches="tight")
    print(f"\nSaved map to {OUTPUT_PATH.resolve()}")
    plt.close(fig)


def main() -> None:
    cutout = prepare_cutout()
    fields = calculate_daily_means(cutout)
    print_dataset_summary(cutout, fields)
    plot_daily_maps(fields)


if __name__ == "__main__":
    main()
