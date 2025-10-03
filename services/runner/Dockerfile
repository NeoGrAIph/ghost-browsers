# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

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
ARG DEBIAN_FRONTEND=noninteractive

USER root
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cabextract \
        curl \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        fonts-noto-mono \
        jq \
        locales \
        nano \
        novnc \
        procps \
        tzdata \
        unzip \
        websockify \
        wget \
        x11vnc \
        xfonts-base \
        xfonts-scalable \
        xvfb \
    && rm -rf /var/lib/apt/lists/*
RUN ln -snf /usr/share/zoneinfo/Etc/UTC /etc/localtime \
    && echo Etc/UTC > /etc/timezone \
    && locale-gen en_US.UTF-8 ru_RU.UTF-8 fi_FI.UTF-8
ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    TZ=Etc/UTC

COPY services/runner/docker/scripts/install-windows-fonts.sh /tmp/install-windows-fonts.sh
RUN chmod +x /tmp/install-windows-fonts.sh \
    && /tmp/install-windows-fonts.sh \
    && rm /tmp/install-windows-fonts.sh
COPY services/runner/docker/assets/fontconfig/99-windows-fonts.conf /etc/fonts/conf.d/99-windows-fonts.conf
RUN fc-cache -f

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

RUN poetry install --without dev --no-root --no-interaction

RUN poetry run pip install --no-deps --force-reinstall "camoufox[geoip]==${CAMOUFOX_VERSION}"

RUN poetry run python -m camoufox fetch

# Copy the service sources after dependency resolution to keep cache hits.
COPY --chown=pwuser:pwuser services/runner ./

# Drop local Camoufox stubs after the production wheel is installed.
RUN rm -rf /workspace/camoufox /workspace/packages/camoufox

ENV PATH="/workspace/services/runner/.venv/bin:${PATH}" \
    CAMOUFOX_HEADLESS=virtual \
    PYTHONPATH="/workspace/services/runner"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
