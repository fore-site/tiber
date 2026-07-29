FROM python:3.14-slim
WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src/ ./src/

RUN pip install uv && uv sync --group dev
