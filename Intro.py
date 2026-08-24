import numpy as np
import matplotlib
import cartopy
import cartopy.crs as ccrs  
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import geopandas as gpd
df = pd.read_csv('https://raw.githubusercontent.com/PyPSA/powerplantmatching/master/powerplants.csv',index_col=0, parse_dates=True)
# print(df.head())
# df.loc["05-2011"].plot()
# df.resample('W').mean().plot()

geometry = gpd.points_from_xy(df['lon'], df['lat'])
gdf = gpd.GeoDataFrame(df, geometry = geometry, crs = 4326)
print(gdf.geometry.head())
fig = plt.figure(figsize=(7, 7))

ax = plt.axes(projection=ccrs.PlateCarree())

gdf.plot(
    ax=ax,
    column="Fueltype",
    markersize=gdf.Capacity / 1e2,
)

ax.coastlines()

ax.add_feature(cartopy.feature.BORDERS, color="red", linewidth=0.5)

ax.add_feature(cartopy.feature.OCEAN, color="blue")

ax.add_feature(cartopy.feature.LAND, color="yellow");

plt.savefig("powerplants_map.png", dpi=300, bbox_inches='tight')
