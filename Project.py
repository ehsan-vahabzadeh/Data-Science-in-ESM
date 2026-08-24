from requests.exceptions import HTTPError

import matplotlib
import atlite
import pypsa
import geopandas as gpd
import pandas as pd
from urllib.request import urlretrieve

matplotlib.use("Agg")

import matplotlib.pyplot as plt

fn = "https://tubcloud.tu-berlin.de/s/567ckizz2Y6RLQq/download?path=%2Fgadm&files=gadm_410-levels-ADM_1-NLD.gpkg"
regions = gpd.read_file(fn)
regions.plot()

minx, miny, maxx, maxy = regions.total_bounds
buffer = 0.25

cutout = atlite.Cutout(
    path="era5-2013-03-N-1234.nc",
    module="era5",
    x=slice(minx - buffer, maxx + buffer),
    y=slice(miny - buffer, maxy + buffer),
    time="2013-03-01",
)
try:
    cutout.prepare(compression=None)
except HTTPError as error:
    print("Skipping cutout preparation because CDS authentication is not configured:")
    print(error)
