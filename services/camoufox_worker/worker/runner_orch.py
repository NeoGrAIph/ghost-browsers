"""HTTP client helpers for orchestrating sessions via the public gateway."""

from __future__ import annotations

from typing import Any, Dict

import httpx


def create_session(gateway_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Request session creation from the gateway and return its JSON payload.

    Parameters
    ----------
    gateway_url: str
        Базовый URL публичного gateway, например `https://gateway.example.com`.
    payload: dict[str, Any]
        Тело запроса, совместимое с `POST /sessions` в gateway.

    Returns
    -------
    dict[str, Any]
        Ответ gateway, преобразованный из JSON.

    Raises
    ------
    httpx.HTTPStatusError
        Если сервер вернул код ответа >=400.
    httpx.TransportError
        Если запрос не был выполнен из-за сетевой ошибки.

    Examples
    --------
    >>> create_session("https://gateway.example.com", {"runner_id": "local"})
    {'id': 'session-123', ...}
    """

    with httpx.Client(timeout=5) as client:
        response = client.post(f"{gateway_url}/sessions", json=payload)
        response.raise_for_status()
        return response.json()
