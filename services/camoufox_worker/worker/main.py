"""Command-line entrypoint for executing Camoufox worker jobs."""

from __future__ import annotations

import sys
from typing import Optional

import click

from .jobs import Job
from .runner_native import run_job


@click.group()
def cli() -> None:
    """Top-level Click command group for worker utilities."""


@cli.command()
@click.option("--url", required=True, help="Полностью квалифицированный URL для открытия Camoufox.")
@click.option("--timeout", default=60, show_default=True, help="Таймаут задачи в секундах.")
@click.option(
    "--mode",
    type=click.Choice(["native", "orchestrator"], case_sensitive=False),
    default="native",
    show_default=True,
    help="Режим выполнения задачи.",
)
def run(url: str, timeout: int, mode: str) -> None:
    """Parse CLI arguments and trigger a single job execution.

    Parameters
    ----------
    url: str
        Целевой URL, передаваемый модели `Job`.
    timeout: int
        Таймаут выполнения задачи в секундах.
    mode: str
        Режим выполнения (`native` или `orchestrator`). Заглушка, пока поддерживается только native.

    Side Effects
    ------------
    Печатает JSON-представление результата в stdout и завершает процесс с кодом 0/1 в зависимости от статуса.
    """

    job = Job(url=url, timeout_sec=timeout)
    if mode.lower() != "native":
        click.echo("Orchestrator mode is not yet implemented.", err=True)
        sys.exit(1)
    result = run_job(job)
    click.echo(result.model_dump_json(indent=2, exclude_none=True))
    if not result.ok:
        sys.exit(1)


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
