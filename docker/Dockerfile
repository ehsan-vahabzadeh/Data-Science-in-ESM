FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    HOME=/home/weather \
    XDG_CACHE_HOME=/app/data/.cache \
    MPLCONFIGDIR=/app/data/.cache/matplotlib \
    CARTOPY_DATA_DIR=/app/data/.cache/cartopy

RUN apt-get update \
    && apt-get install --no-install-recommends -y libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 weather \
    && useradd --uid 1000 --gid weather --create-home weather

WORKDIR /app

COPY docker/requirements.txt docker/requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_CACHE_DIR=/root/.cache/pip python -m pip install -r requirements.lock -r requirements.txt \
    && python -m pip check \
    && python -m cfgrib selfcheck

COPY --chown=weather:weather UKWeather.py UKDayAheadWeatherML.py ECMWFForecastVerification.py REPD_Publication_Q2_2026.csv ./

USER weather
