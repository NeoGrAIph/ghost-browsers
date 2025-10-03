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
from types import ModuleType
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

    install_dir = tmp_path_factory.mktemp("camoufox-install")
    binary_name = "camoufox"

    try:
        pkgman = import_module("camoufox.pkgman")
    except ModuleNotFoundError as exc:
        if exc.name != "camoufox_sdk":  # pragma: no cover - unexpected SDK failure
            raise
        pkgman = ModuleType("camoufox.pkgman")
        os_name = "linux"
        pkgman.OS_NAME = os_name
        pkgman.LAUNCH_FILE = {os_name: binary_name}

        class _StubFetcher:
            """Lightweight stand-in that avoids network-bound installation paths."""

            def __init__(self, *_: object, **__: object) -> None:
                """Accept arbitrary arguments mirroring the real constructor."""

            def install(self) -> Path:
                """Return the synthetic installation directory created for tests."""

                return install_dir

            def cleanup(self) -> bool:
                """Signal that no teardown work is required for the stub."""

                return True

        pkgman.CamoufoxFetcher = _StubFetcher
        pkgman.camoufox_path = lambda download_if_missing=True: install_dir
        pkgman.launch_path = lambda: str(install_dir / binary_name)
        pkgman.installed_verstr = lambda: "test-0.0.0"

        # Ensure ``import camoufox.pkgman`` resolves to the stub module even when the
        # parent package is absent.  Tests interact only with ``pkgman`` so the
        # minimal namespace keeps dependencies hermetic offline.
        parent = sys.modules.setdefault("camoufox", ModuleType("camoufox"))
        parent.__path__ = []  # type: ignore[attr-defined]
        parent.pkgman = pkgman
        sys.modules["camoufox.pkgman"] = pkgman
    else:
        binary_name = pkgman.LAUNCH_FILE[pkgman.OS_NAME]
        binary_path = install_dir / binary_name
        monkeypatch.setattr(
            pkgman,
            "camoufox_path",
            lambda download_if_missing=True: install_dir,
            raising=False,
        )
        monkeypatch.setattr(
            pkgman, "launch_path", lambda: str(binary_path), raising=False
        )
        monkeypatch.setattr(
            pkgman, "installed_verstr", lambda: "test-0.0.0", raising=False
        )

        fetcher_cls = pkgman.CamoufoxFetcher

        def _noop_install(self) -> Path:  # type: ignore[override]
            return install_dir

        monkeypatch.setattr(fetcher_cls, "install", _noop_install, raising=False)
        monkeypatch.setattr(fetcher_cls, "cleanup", lambda self: True, raising=False)

    binary_path = install_dir / binary_name
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text("#!/bin/sh\nexit 0\n")
    binary_path.chmod(0o755)

    version_file = install_dir / "version.json"
    version_file.write_text("{\"version\": \"test\", \"release\": \"0.0.0\"}")

    yield install_dir
