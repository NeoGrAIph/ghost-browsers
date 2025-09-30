from __future__ import annotations

import json
import sys
from pathlib import Path

import tomllib

from shared.version import __version__

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "VERSION"
PYPROJECT_PATHS = {
    "control": ROOT / "control-plane" / "pyproject.toml",
    "worker": ROOT / "worker" / "pyproject.toml",
    "runner": ROOT / "runner" / "pyproject.toml",
}
PACKAGE_JSON = ROOT / "ui" / "package.json"


def _ensure_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def test_version_constant_matches_file() -> None:
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == __version__


def test_pyproject_versions_reference_version_file() -> None:
    for path in PYPROJECT_PATHS.values():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        assert "version" in project.get("dynamic", []), path
        dynamic = data.get("tool", {}).get("setuptools", {}).get("dynamic", {})
        assert dynamic.get("version", {}).get("file") in {"../VERSION", "VERSION"}, path


def test_ui_package_version_matches_version_constant() -> None:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert data["version"] == __version__


def test_fastapi_apps_advertise_shared_version() -> None:
    _ensure_path(ROOT / "control-plane")
    _ensure_path(ROOT / "worker")
    _ensure_path(ROOT / "runner")

    from camofleet_control.main import create_app as create_control_app
    from camofleet_worker.main import create_app as create_worker_app
    from camoufox_runner.main import create_app as create_runner_app

    assert create_control_app().version == __version__
    assert create_worker_app().version == __version__
    assert create_runner_app().version == __version__
