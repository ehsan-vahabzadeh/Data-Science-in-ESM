FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/weather

RUN groupadd --gid 1000 weather \
    && useradd --uid 1000 --gid weather --create-home weather

WORKDIR /app

USER weather
