FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src/ ./src/

RUN pip install uv && uv sync --group dev
