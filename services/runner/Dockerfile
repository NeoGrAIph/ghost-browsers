# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    PATH="${POETRY_HOME}/bin:${PATH}"

USER root
RUN pip install --upgrade pip && pip install "poetry==${POETRY_VERSION}"

WORKDIR /workspace
# Copy the repository segments that runner depends on directly. Path dependencies
# in pyproject.toml assume ``packages`` and the top-level ``camoufox`` package
# live next to the runner service inside the workspace.
COPY camoufox ./camoufox
COPY packages ./packages
COPY services/runner ./services/runner
RUN chown -R pwuser:pwuser /workspace

USER pwuser
WORKDIR /workspace/services/runner
RUN poetry install --without dev

ENV PATH="/workspace/services/runner/.venv/bin:${PATH}" \
    CAMOUFOX_HEADLESS=virtual

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
