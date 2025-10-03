# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/pypoetry-cache \
    PATH="${POETRY_HOME}/bin:${PATH}"

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential python3-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /tmp/pypoetry-cache /tmp/pip-cache \
    && chmod 1777 /tmp/pypoetry-cache /tmp/pip-cache

RUN python -m pip install --upgrade pip \
    && python -m pip install "poetry==${POETRY_VERSION}"

RUN addgroup --system app \
    && adduser --system --ingroup app app

WORKDIR /workspace

# Copy dependency descriptors and shared packages first for better cache reuse.
COPY services/gateway/pyproject.toml ./services/gateway/pyproject.toml
COPY packages ./packages

RUN chown -R app:app /workspace

RUN mkdir -p /home/app/.cache/pip \
    && chown -R app:app /home/app

USER app
WORKDIR /workspace/services/gateway

RUN poetry install --without dev --no-root

# Copy application sources after dependency resolution to maximize cache hits.
COPY --chown=app:app services/gateway ./

ENV PATH="/workspace/services/gateway/.venv/bin:${PATH}"

EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--host", "0.0.0.0", "--port", "8080"]
