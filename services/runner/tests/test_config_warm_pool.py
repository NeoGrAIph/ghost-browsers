"""Tests for warm pool configuration models and helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import (
    RunnerSettings,
    WarmPoolConfigError,
    load_warm_pool_config,
)


def test_load_warm_pool_config_success(tmp_path: Path) -> None:
    """``load_warm_pool_config`` should parse workstation entries from JSON."""

    payload = {
        "workstations": [
            {"id": "ws-1", "label": "Chrome Stable"},
            {"id": "ws-2", "tags": ["gpu", "en-US"]},
        ]
    }
    config_path = tmp_path / "warm_pool.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_warm_pool_config(config_path)

    assert config is not None
    assert [entry.id for entry in config.workstations] == ["ws-1", "ws-2"]
    assert config.workstations[1].tags == ["gpu", "en-US"]


def test_load_warm_pool_config_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate workstation ids should surface as a ``WarmPoolConfigError``."""

    payload = {
        "workstations": [
            {"id": "ws-1"},
            {"id": "ws-1"},
        ]
    }
    config_path = tmp_path / "duplicate.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WarmPoolConfigError) as exc_info:
        load_warm_pool_config(config_path)

    assert "must be unique" in str(exc_info.value)


def test_load_warm_pool_config_handles_io_errors(tmp_path: Path) -> None:
    """Missing files should be reported via ``WarmPoolConfigError``."""

    missing_path = tmp_path / "missing.json"

    with pytest.raises(WarmPoolConfigError) as exc_info:
        load_warm_pool_config(missing_path)

    assert "failed to read warm pool config" in str(exc_info.value)


def test_load_warm_pool_config_handles_json_errors(tmp_path: Path) -> None:
    """Invalid JSON payloads should raise ``WarmPoolConfigError``."""

    broken_path = tmp_path / "broken.json"
    broken_path.write_text("{this is not valid json}", encoding="utf-8")

    with pytest.raises(WarmPoolConfigError) as exc_info:
        load_warm_pool_config(broken_path)

    assert "not valid JSON" in str(exc_info.value)


def test_runner_settings_from_env_supports_navigation_fields() -> None:
    """``RunnerSettings.from_env`` should populate warm pool and navigation fields."""

    env = {
        "RUNNER_ID": "runner-1",
        "WARM_POOL_CONFIG_PATH": "/etc/runner/warm_pool.json",
        "BROWSER_PREFS_PATH": "/etc/runner/prefs.json",
        "PREWARM_NAVIGATION": "true",
        "START_URL": "https://example.test/welcome",
        "START_URL_WAIT_MS": "1500",
    }

    settings = RunnerSettings.from_env(env)

    assert settings.warm_pool_config_path == Path("/etc/runner/warm_pool.json")
    assert settings.browser_prefs_path == Path("/etc/runner/prefs.json")
    assert settings.prewarm_navigation is True
    assert str(settings.start_url) == "https://example.test/welcome"
    assert settings.start_url_wait_ms == 1500
