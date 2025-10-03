# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    PATH="${POETRY_HOME}/bin:${PATH}"

ARG CAMOUFOX_VERSION=0.4.11

USER root
RUN python -m pip install --upgrade pip \
    && python -m pip install "poetry==${POETRY_VERSION}"

WORKDIR /workspace

# Copy only dependency descriptors first to leverage Docker layer caching.
COPY services/runner/pyproject.toml ./services/runner/pyproject.toml
COPY services/runner/poetry.lock ./services/runner/poetry.lock
COPY packages ./packages
COPY camoufox ./camoufox
RUN chown -R pwuser:pwuser /workspace

USER pwuser
WORKDIR /workspace/services/runner

RUN --mount=type=cache,target=/home/pwuser/.cache/pypoetry \
    --mount=type=cache,target=/home/pwuser/.cache/pip \
    poetry install --without dev --no-root --no-interaction

RUN --mount=type=cache,target=/home/pwuser/.cache/pip \
    poetry run pip install --no-deps --force-reinstall "camoufox[geoip]==${CAMOUFOX_VERSION}"

RUN --mount=type=cache,target=/home/pwuser/.cache/pip \
    poetry run python -m camoufox fetch

# Copy the service sources after dependency resolution to keep cache hits.
COPY --chown=pwuser:pwuser services/runner ./

# Drop local Camoufox stubs after the production wheel is installed.
RUN rm -rf /workspace/camoufox /workspace/packages/camoufox

ENV PATH="/workspace/services/runner/.venv/bin:${PATH}" \
    CAMOUFOX_HEADLESS=virtual \
    PYTHONPATH="/workspace/services/runner"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
