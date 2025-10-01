"""Data models describing executable Camoufox jobs for the worker service."""

from typing import Optional

from pydantic import BaseModel, HttpUrl


class Job(BaseModel):
    """Describe a single browser automation task to be executed by the worker.

    Parameters
    ----------
    url: HttpUrl
        Полностью квалифицированный URL, который необходимо открыть в браузере.
    http_proxy: str | None
        Необязательный HTTP-прокси для текущей задачи в формате схемы URL.
    https_proxy: str | None
        Необязательный HTTPS-прокси; если не указан, можно использовать `http_proxy`.
    socks_proxy: str | None
        Необязательный SOCKS-прокси (например, `socks5://user:pass@host:port`).
    timeout_sec: int
        Предельное время выполнения задачи в секундах; по умолчанию 60.

    Returns
    -------
    Job
        Pydantic-модель с валидацией входных данных и приведением типов.

    Examples
    --------
    >>> Job(url="https://example.com", timeout_sec=120)
    Job(url=HttpUrl('https://example.com', ...), timeout_sec=120)
    """

    url: HttpUrl
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    socks_proxy: Optional[str] = None
    timeout_sec: int = 60
