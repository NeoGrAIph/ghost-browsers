"""Command-line entrypoint for executing Camoufox worker jobs."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import click

from .jobs import Job, JobResult
from .runner_native import run_job
from .runner_orch import create_gateway_client, run_orchestrated_job


@click.group()
def cli() -> None:
    """Top-level Click command group for worker utilities."""


@cli.command()
@click.option("--url", required=True, help="Полностью квалифицированный URL для открытия Camoufox.")
@click.option("--timeout", default=60, show_default=True, help="Таймаут задачи в секундах.")
@click.option(
    "--mode",
    type=click.Choice(["native", "orchestrator"], case_sensitive=False),
    envvar="WORKER_MODE",
    default="native",
    show_default=True,
    help="Режим выполнения задачи (можно переопределить переменной WORKER_MODE).",
)
@click.option(
    "--gateway-url",
    envvar="GATEWAY_URL",
    default=None,
    help="Базовый URL Gateway для orchestrator-режима.",
)
@click.option(
    "--gateway-token",
    envvar="GATEWAY_TOKEN",
    default=None,
    help="Bearer-токен Gateway (env GATEWAY_TOKEN).",
)
@click.option(
    "--poll-timeout",
    type=float,
    default=90.0,
    show_default=True,
    help="Таймаут ожидания готовности сессии в orchestrator-режиме (сек).",
)
@click.option(
    "--poll-interval",
    type=float,
    default=1.0,
    show_default=True,
    help="Интервал опроса статуса сессии в orchestrator-режиме (сек).",
)
def run(
    url: str,
    timeout: int,
    mode: str,
    gateway_url: Optional[str],
    gateway_token: Optional[str],
    poll_timeout: float,
    poll_interval: float,
) -> None:
    """Parse CLI arguments and trigger a single job execution.

    Parameters
    ----------
    url: str
        Целевой URL, передаваемый модели `Job`.
    timeout: int
        Таймаут выполнения задачи в секундах.
    mode: str
        Режим выполнения (`native` или `orchestrator`). Значение по умолчанию
        можно задать переменной окружения ``WORKER_MODE``.
    gateway_url: str | None
        Базовый URL Gateway для orchestrator-режима. Читается из ``GATEWAY_URL``.
    gateway_token: str | None
        Bearer-токен для Gateway. Можно передать через ``GATEWAY_TOKEN``.
    poll_timeout: float
        Максимальное время ожидания статуса ``READY`` при оркестрации.
    poll_interval: float
        Интервал опроса Gateway при ожидании готовности сессии.

    Side Effects
    ------------
    Печатает JSON-представление результата в stdout и завершает процесс с
    кодом 0/1 в зависимости от статуса.
    """

    job = Job(url=url, timeout_sec=timeout)
    normalized_mode = mode.lower()
    if normalized_mode == "native":
        result = run_job(job)
    else:
        if not gateway_url or not gateway_token:
            click.echo(
                "Gateway URL и токен обязательны для orchestrator-режима (см. GATEWAY_URL/GATEWAY_TOKEN).",
                err=True,
            )
            sys.exit(1)
        result = asyncio.run(
            _run_orchestrator(
                job,
                gateway_url=gateway_url,
                gateway_token=gateway_token,
                poll_timeout=poll_timeout,
                poll_interval=poll_interval,
            )
        )
    click.echo(result.model_dump_json(indent=2, exclude_none=True))
    if not result.ok:
        sys.exit(1)


async def _run_orchestrator(
    job: Job,
    *,
    gateway_url: str,
    gateway_token: str,
    poll_timeout: float,
    poll_interval: float,
) -> JobResult:
    """Execute a job against the gateway orchestrator and return its result.

    Parameters
    ----------
    job:
        Подготовленная задача.
    gateway_url:
        Базовый URL публичного Gateway.
    gateway_token:
        Bearer-токен для аутентификации.
    poll_timeout:
        Максимальное время ожидания статуса ``READY``.
    poll_interval:
        Интервал опроса статуса сессии.

    Returns
    -------
    JobResult
        Результат выполнения orchestrator-потока.
    """

    async with create_gateway_client(gateway_url, gateway_token) as client:
        return await run_orchestrated_job(
            job,
            client,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
        )


def main(argv: Optional[list[str]] = None) -> int:
    """Entry helper for invoking the CLI programmatically.

    Parameters
    ----------
    argv: list[str] | None
        Необязательный список аргументов командной строки без имени программы.

    Returns
    -------
    int
        Код выхода CLI (0 при успехе, иначе ненулевой).
    """

    argv = argv if argv is not None else sys.argv[1:]
    try:
        cli.main(args=list(argv), prog_name="camoufox-worker")
    except SystemExit as exc:  # Click использует SystemExit для завершения
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
