"""Smoke-style tests ensuring the camoufox_worker scaffolding exists."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_task_files_exist() -> None:
    """Ensure primary documentation and source files were generated."""

    for name in [
        "README-TASK.md",
        "README.md",
        "AGENTS.md",
        "AGENT_NOTES.md",
        "worker/jobs.py",
        "worker/runner_native.py",
        "worker/main.py",
    ]:
        assert (ROOT / name).exists(), f"Missing expected file: {name}"
