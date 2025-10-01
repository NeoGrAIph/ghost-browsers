"""Client responsible for polling runner health endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from core import Runner
from pydantic import BaseModel, ConfigDict, Field

from .runner_registry import RunnerRegistry


class RunnerHealthSlots(BaseModel):
    """Representation of the ``slots`` section returned by ``GET /health``."""

    model_config = ConfigDict(extra="ignore")

    total: int | None = Field(default=None, description="Configured slot capacity")
    available: int | None = Field(default=None, description="Currently free slots")


class RunnerHealthVnc(BaseModel):
    """Representation of the ``vnc`` section reported by runners."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = Field(default=None, description="True if VNC is enabled")


class RunnerHealthPayload(BaseModel):
    """Minimal structure parsed from the runner health response."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(description="Reported health status string")
    runner_id: str = Field(min_length=1, description="Identifier echoed by the runner")
    slots: RunnerHealthSlots | None = Field(default=None, description="Optional slot metrics")
    vnc: RunnerHealthVnc | None = Field(default=None, description="Optional VNC capability block")

    def to_updates(self, *, timestamp: datetime) -> dict[str, Any]:
        """Translate the payload into registry update keyword arguments.

        Args:
            timestamp: Moment the health payload was observed; forwarded as the
                heartbeat timestamp.

        Returns:
            dict[str, Any]: Keyword arguments compatible with
            :meth:`RunnerRegistry.record_health`.
        """

        healthy = self.status.lower() == "ok"
        updates: dict[str, Any] = {
            "healthy": healthy,
            "heartbeat_at": timestamp,
        }

        if self.slots is not None:
            updates["total_slots"] = self.slots.total
            updates["available_slots"] = self.slots.available

        if self.vnc is not None:
            updates["supports_vnc"] = self.vnc.enabled

        return updates


@dataclass(slots=True)
class RunnerHealthClient:
    """HTTP client used by the control plane to poll runner health probes."""

    timeout: float = 5.0
    transport: httpx.BaseTransport | None = None

    async def probe(self, runner: Runner, registry: RunnerRegistry) -> Runner | None:
        """Poll ``GET /health`` for the given runner and update the registry.

        Args:
            runner: Runner that should be probed.
            registry: Shared runner registry updated with the probe results.

        Returns:
            Optional[Runner]: Updated runner snapshot on success, ``None`` when
            the runner is unknown to the registry or the probe fails.
        """

        observed_at = datetime.now(tz=UTC)

        try:
            async with httpx.AsyncClient(
                base_url=str(runner.base_url),
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.get("/health")
                response.raise_for_status()
        except httpx.HTTPError:
            # Mark the runner unhealthy but avoid updating the heartbeat to keep
            # the timestamp of the last successful probe.
            await registry.record_health(
                runner.id,
                healthy=False,
                heartbeat_at=None,
            )
            return None

        payload = RunnerHealthPayload.model_validate(response.json())
        if payload.runner_id != runner.id:
            # Defensive guard: ignore mismatched identifiers to avoid corrupting
            # registry state.
            return None

        updates = payload.to_updates(timestamp=observed_at)
        return await registry.record_health(runner.id, **updates)


__all__ = [
    "RunnerHealthClient",
]
