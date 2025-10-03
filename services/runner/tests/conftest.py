"""Pytest fixtures configuring Camoufox test doubles for the runner suite.

The module also ensures that the ``app`` package resolves without requiring
contributors to export ``PYTHONPATH`` manually. This mirrors the runtime
Docker image where the service root is appended to the module search path.

Example:
    >>> import importlib
    >>> importlib.import_module("app.config")  # doctest: +SKIP
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Iterator

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


@pytest.fixture(autouse=True)
def camoufox_installation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    """Provide an isolated Camoufox installation directory for tests.

    The official Camoufox SDK attempts to download browser binaries when they
    are missing.  The runner unit tests must not perform network I/O, so this
    fixture patches the relevant installer hooks to return a disposable
    directory with synthetic metadata and an empty executable placeholder.

    Args:
        monkeypatch: Pytest helper used to override SDK functions.
        tmp_path_factory: Factory for creating unique temporary directories.

    Yields:
        Path: The fake installation directory used during the test.
    """

    pkgman = import_module("camoufox.pkgman")

    install_dir = tmp_path_factory.mktemp("camoufox-install")
    binary_path = install_dir / pkgman.LAUNCH_FILE[pkgman.OS_NAME]
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text("#!/bin/sh\nexit 0\n")
    binary_path.chmod(0o755)

    version_file = install_dir / "version.json"
    version_file.write_text("{\"version\": \"test\", \"release\": \"0.0.0\"}")

    monkeypatch.setattr(
        pkgman,
        "camoufox_path",
        lambda download_if_missing=True: install_dir,
        raising=False,
    )
    monkeypatch.setattr(pkgman, "launch_path", lambda: str(binary_path), raising=False)
    monkeypatch.setattr(pkgman, "installed_verstr", lambda: "test-0.0.0", raising=False)

    fetcher_cls = pkgman.CamoufoxFetcher

    def _noop_install(self) -> Path:  # type: ignore[override]
        return install_dir

    monkeypatch.setattr(fetcher_cls, "install", _noop_install, raising=False)
    monkeypatch.setattr(fetcher_cls, "cleanup", lambda self: True, raising=False)

    yield install_dir
