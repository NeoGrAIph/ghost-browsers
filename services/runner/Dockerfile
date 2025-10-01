# syntax=docker/dockerfile:1.6
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

# Важно: Playwright-образ уже содержит системные зависимости и Xvfb.
# Переключаемся на встроенного non-root пользователя pwuser (он есть в образе).
USER pwuser
WORKDIR /home/pwuser/app

# Устанавливаем Camoufox (при необходимости зафиксируйте версию)
# Примечание: пакет playwright как зависимость Camoufox устанавливать отдельно обычно не требуется,
# но если ваш проект его использует напрямую, добавьте `pip install playwright==<версия>`.
RUN pip install --no-cache-dir -U "camoufox[geoip]"

# Скачиваем сам браузер и данные Camoufox В КЕШ pwuser (исключит повторные докачки)
RUN python -m camoufox fetch

# Headless через виртуальный дисплей (Xvfb уже в образе)
ENV CAMOUFOX_HEADLESS=virtual

# Опционально: быстрый smoke-тест (удалите/замените на запуск сервиса)
CMD ["python", "-m", "camoufox", "version"]
