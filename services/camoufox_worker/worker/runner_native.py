"""Native Camoufox execution helpers for worker jobs."""

from __future__ import annotations

import os
from typing import Any, Dict

from camoufox.sync_api import Camoufox

from .jobs import Job


def run_job(job: Job) -> Dict[str, Any]:
    """Execute a job inside the current container using Camoufox directly.

    Parameters
    ----------
    job: Job
        Экземпляр задачи, описывающий URL, прокси и таймаут.

    Returns
    -------
    dict[str, Any]
        Словарь с результатами выполнения, включая флаг `ok` и заголовок страницы.

    Raises
    ------
    camoufox.errors.CamoufoxError
        Если Camoufox не смог стартовать или выполнить переход по URL.

    Notes
    -----
    Прокси-настройки пока не применяются; модуль выступает заглушкой для будущей интеграции
    с изолированными контекстами и сетевыми профилями.

    Examples
    --------
    >>> run_job(Job(url="https://example.com"))
    {'ok': True, 'title': 'Example Domain'}
    """

    headless = os.getenv("CAMOUFOX_HEADLESS", "virtual")
    with Camoufox(headless=headless, geoip=True) as browser:
        page = browser.new_page()
        # TODO: применить прокси к браузеру/контексту, если указано в job
        page.goto(str(job.url))
        title = page.title()
    return {"ok": True, "title": title}
