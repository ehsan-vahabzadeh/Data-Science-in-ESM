# Docker setup

From the repository root, with Docker Engine and the Compose plugin running:

```bash
mkdir -p data outputs
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml run --rm pilot
```

The matcher can also run in the container with `docker compose -f docker/compose.yaml run --rm match`; see [the dataset guide](../docs/open-meteo-dataset.md) before starting the long download.

The pilot needs network access and writes its response to the host `data/` directory. It refuses to overwrite existing results. For a specific sample month:

```bash
docker compose -f docker/compose.yaml run --rm pilot python OpenMeteoPilot.py --month 2025-10
```

The image also retains the historical ERA5-only ML prototype. `docker compose -f docker/compose.yaml run --rm ml` needs an existing compatible atlite cutout at `data/uk-era5-2025-01-02-to-2026-01-02.nc`. It is not the planned Open-Meteo IFS error-correction model. See [the project guide](../PROJECT_GUIDE.md).

Data, outputs, caches and credentials are excluded from the image; mounted data and results remain on the host. No CDS or ECMWF credential is needed for the Open-Meteo pilot. See Open-Meteo's terms for your intended use.
