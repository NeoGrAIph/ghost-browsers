"""Pydantic models for describing warm workstation pools."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class WorkstationConfigEntry(BaseModel):
    """Describe a workstation entry shipped with a pre-warmed pool.

    The schema keeps the definition intentionally small and allows additional
    keys so that operators can attach environment specific metadata without
    touching code. The :class:`WarmPoolConfig` validator will later ensure that
    ``id`` values remain unique across the pool.

    Attributes:
        id: Globally unique workstation identifier.
        label: Optional human readable title that can be surfaced in logs or
            dashboards.
        tags: Arbitrary labels describing capabilities of the workstation.

    Example:
        >>> WorkstationConfigEntry(id="ws-1", label="Chrome Stable", tags=["chrome"])
        WorkstationConfigEntry(id='ws-1', label='Chrome Stable', tags=['chrome'])
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(..., min_length=1, description="Unique workstation identifier")
    label: str | None = Field(
        default=None,
        description="Optional human readable label used by operators",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary capability tags attached to the workstation",
    )


class WarmPoolConfig(BaseModel):
    """Container describing the full warm pool configuration payload.

    Attributes:
        workstations: Ordered collection of workstation descriptors available in
            the warm pool.

    Example:
        >>> WarmPoolConfig(workstations=[WorkstationConfigEntry(id="ws-1")])
        WarmPoolConfig(workstations=[WorkstationConfigEntry(id='ws-1', label=None, tags=[])])
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    workstations: list[WorkstationConfigEntry] = Field(
        default_factory=list,
        description="Collection of workstations that can be pre-warmed",
    )

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "WarmPoolConfig":
        """Ensure that workstation identifiers remain unique across the pool."""

        seen: set[str] = set()
        duplicates: set[str] = set()
        for entry in self.workstations:
            if entry.id in seen:
                duplicates.add(entry.id)
            else:
                seen.add(entry.id)
        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise ValueError(
                f"warm pool workstation ids must be unique: {duplicate_list}"
            )
        return self


class WarmPoolConfigError(RuntimeError):
    """Raised when warm pool configuration cannot be loaded or validated."""

    def __init__(self, message: str, *, path: Path | None = None) -> None:
        super().__init__(message)
        self.path = path


def load_warm_pool_config(path: Path | None) -> WarmPoolConfig | None:
    """Load and validate warm pool configuration from ``path``.

    Args:
        path: Location of the JSON file. ``None`` short-circuits loading and
            returns ``None`` to keep the feature optional.

    Returns:
        WarmPoolConfig | None: Parsed configuration structure or ``None`` when
        no path is provided.

    Raises:
        WarmPoolConfigError: If the file cannot be read, JSON parsing fails, or
            validation rejects the payload.

    Example:
        >>> from pathlib import Path
        >>> tmp = Path("warm.json")
        >>> _ = tmp.write_text('{"workstations": [{"id": "ws-1"}]}')
        >>> config = load_warm_pool_config(tmp)
        >>> config.workstations[0].id
        'ws-1'
    """

    if path is None:
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WarmPoolConfigError(
            f"failed to read warm pool config from '{path}': {exc.strerror}", path=path
        ) from exc
    except json.JSONDecodeError as exc:
        raise WarmPoolConfigError(
            f"warm pool config at '{path}' is not valid JSON: {exc.msg}", path=path
        ) from exc

    try:
        return WarmPoolConfig.model_validate(payload)
    except ValidationError as exc:
        raise WarmPoolConfigError(
            f"warm pool config at '{path}' failed validation: {exc}", path=path
        ) from exc


__all__ = [
    "WarmPoolConfig",
    "WarmPoolConfigError",
    "WorkstationConfigEntry",
    "load_warm_pool_config",
]
