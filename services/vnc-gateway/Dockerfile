# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=0 \
    PATH="${POETRY_HOME}/bin:${PATH}"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential python3-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install "poetry==${POETRY_VERSION}"

WORKDIR /opt/app

# Copy dependency descriptors first to leverage Docker layer caching.
COPY services/vnc-gateway/pyproject.toml ./pyproject.toml

RUN poetry install --without dev --no-root --no-interaction

# Application sources and tests are copied afterwards to avoid busting the dependency cache.
COPY services/vnc-gateway/app ./app
COPY services/vnc-gateway/tests ./tests

ENV PYTHONPATH=/opt/app/app

EXPOSE 8080

CMD ["uvicorn", "camou_vnc_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
