FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

# Debian slim ships without the tz database. ZoneInfo (used to evaluate
# delivery constraints in the project's timezone) reads it from
# /usr/share/zoneinfo; without this, every non-UTC ZoneInfo() call raises
# ZoneInfoNotFoundError at constraint construction.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src/ ./src/

RUN pip install uv && uv sync --group dev
