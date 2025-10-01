# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

# non-root пользователь уже есть в образе
USER pwuser
WORKDIR /home/pwuser/app

# Установка Camoufox (при необходимости зафиксируйте версию через ARG)
ARG CAMOUFOX_PY_VERSION=
RUN pip install --no-cache-dir -U "camoufox[geoip]${CAMOUFOX_PY_VERSION:+==${CAMOUFOX_PY_VERSION}}"

# Скачиваем артефакты Camoufox в КЕШ pwuser (исключает повторные докачки)
RUN python -m camoufox fetch

# Headless через виртуальный дисплей (Xvfb уже в Playwright-образе)
ENV CAMOUFOX_HEADLESS=virtual

# Зависимости проекта (когда появятся):
# COPY pyproject.toml poetry.lock ./
# RUN poetry install --no-root
# COPY --chown=pwuser:pwuser worker ./worker

# Smoke по умолчанию (замените на entrypoint при реализации)
COPY --chown=pwuser:pwuser smoke.py ./smoke.py
CMD ["python", "-m", "camoufox", "version"]
