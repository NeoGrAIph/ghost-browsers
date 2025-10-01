"""Validate that gateway command DTOs remain compatible with runner/core models."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

TEST_ROOT = Path(__file__).resolve()
SERVICE_ROOT = TEST_ROOT.parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
RUNNER_ROOT = REPO_ROOT / "services" / "runner"
RUNNER_APP_PATH = RUNNER_ROOT / "app"

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
if str(RUNNER_ROOT) not in sys.path:
    sys.path.append(str(RUNNER_ROOT))

runner_app_pkg = types.ModuleType("runner_app")
runner_app_pkg.__path__ = [str(RUNNER_APP_PATH)]
sys.modules.setdefault("runner_app", runner_app_pkg)

config_settings_spec = importlib.util.spec_from_file_location(
    "runner_app.config.settings", RUNNER_APP_PATH / "config" / "settings.py"
)
config_settings_module = importlib.util.module_from_spec(config_settings_spec)
sys.modules["runner_app.config.settings"] = config_settings_module
config_settings_spec.loader.exec_module(config_settings_module)

events_spec = importlib.util.spec_from_file_location(
    "runner_app.events", RUNNER_APP_PATH / "events.py"
)
events_module = importlib.util.module_from_spec(events_spec)
sys.modules["runner_app.events"] = events_module
events_spec.loader.exec_module(events_module)

config_spec = importlib.util.spec_from_file_location(
    "runner_app.config", RUNNER_APP_PATH / "config" / "__init__.py"
)
config_module = importlib.util.module_from_spec(config_spec)
sys.modules["runner_app.config"] = config_module
config_spec.loader.exec_module(config_module)

session_manager_spec = importlib.util.spec_from_file_location(
    "runner_app.session_manager", RUNNER_APP_PATH / "session_manager.py"
)
session_manager_module = importlib.util.module_from_spec(session_manager_spec)
sys.modules["runner_app.session_manager"] = session_manager_module
session_manager_spec.loader.exec_module(session_manager_module)

from app.services.runner_client import SessionCreateCommand, SessionUpdateCommand  # noqa: E402
from core import Session, SessionStatus  # noqa: E402
SessionCreatePayload = session_manager_module.SessionCreatePayload
SessionUpdatePayload = session_manager_module.SessionUpdatePayload


@pytest.fixture()
def anyio_backend() -> str:
    """Force the AnyIO plugin to use asyncio for compatibility."""

    return "asyncio"


def test_session_create_command_matches_runner_contract() -> None:
    """Ensure ``SessionCreateCommand`` renders payload accepted by the runner."""

    command = SessionCreateCommand(
        runner_id="runner-1",
        browser_name="Chrome",
        region="eu-central",
        proxy_id="proxy-9",
        headless=False,
        start_url="https://example.test",
    )

    payload = command.to_runner_payload()
    validated = SessionCreatePayload.model_validate(payload)

    assert validated.browser == command.browser_name
    assert validated.headless is command.headless
    assert validated.labels == {"region": "eu-central", "proxy_id": "proxy-9"}
    assert str(validated.start_url) == "https://example.test/"
    assert validated.idle_ttl_seconds == 300


def test_session_update_command_matches_runner_contract() -> None:
    """Ensure ``SessionUpdateCommand`` payload conforms to runner expectations."""

    command = SessionUpdateCommand(
        status=SessionStatus.READY,
        headless=True,
        labels={"tier": "gold"},
        metadata={"attempt": 1},
        reason="manual override",
    )

    payload = command.to_runner_payload()
    validated = SessionUpdatePayload.model_validate(payload)

    assert validated.status is SessionStatus.READY
    assert validated.headless is True
    assert validated.labels == {"tier": "gold"}
    assert validated.metadata == {"attempt": 1}
    assert validated.reason == "manual override"
    assert "last_seen_at" not in payload


def test_session_accepts_updated_at_alias() -> None:
    """Runner responses using the ``updated_at`` alias validate against ``Session``."""

    now = datetime.now(tz=UTC)
    payload = {
        "id": str(uuid4()),
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "idle_ttl_seconds": 300,
        "headless": False,
    }

    session = Session.model_validate(payload)

    assert session.last_seen_at == now
    assert session.updated_at == now
