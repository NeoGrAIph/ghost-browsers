# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

ENV PATH="/home/pwuser/.local/bin:${PATH}"

# non-root пользователь уже есть в образе
USER pwuser
WORKDIR /home/pwuser/app

ARG POETRY_VERSION=1.8.3
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "poetry==${POETRY_VERSION}"
RUN poetry config virtualenvs.create false

COPY --chown=pwuser:pwuser services/camoufox_worker/pyproject.toml ./pyproject.toml
COPY --chown=pwuser:pwuser services/camoufox_worker/poetry.lock ./poetry.lock
RUN poetry install --no-root --only main --no-interaction

COPY --chown=pwuser:pwuser services/camoufox_worker/worker ./worker
COPY --chown=pwuser:pwuser services/camoufox_worker/bin ./bin
RUN chmod +x bin/worker-launch.sh

# Headless через виртуальный дисплей (Xvfb уже в Playwright-образе)
ENV CAMOUFOX_HEADLESS=virtual

# Дополнительный аргумент позволяет переопределить версию Camoufox при сборке
ARG CAMOUFOX_PY_VERSION=
RUN if [ -n "${CAMOUFOX_PY_VERSION}" ]; then \
      python -m pip install --no-cache-dir --force-reinstall "camoufox[geoip]==${CAMOUFOX_PY_VERSION}"; \
    fi

# Скачиваем артефакты Camoufox в кеш pwuser (исключает повторные докачки)
RUN python -m camoufox fetch

ENTRYPOINT ["./bin/worker-launch.sh"]
