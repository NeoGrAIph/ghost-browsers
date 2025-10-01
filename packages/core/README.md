# camou-core

Shared contract models and developer utilities for the Ghost Browsers stack.
The package is consumed by the Runner, Gateway, VNC Gateway, and operator UI
services to guarantee a consistent representation of runner metadata, session
state, and lifecycle events.

## Contents
- **Pydantic models**: immutable schemas covering runner metadata, session
  lifecycle, and session events with strong validation rules (see
  [`core/models.py`](core/models.py)).
- **Event bridge abstractions**: an abstract interface for broadcasting session
  events and a local in-memory implementation for tests and development (see
  [`core/websocket_bridge.py`](core/websocket_bridge.py)).

## Key invariants
- `Session.last_seen_at >= Session.created_at`, `Session.ended_at` may only
  increase.
- VNC tokens expire in ≤ 300 seconds and must be supplied together with a TTL.
- Runner availability is capped by `total_slots` and OFFLINE runners cannot be
  reported as healthy.
- Proxy definitions require at least one URL; VNC descriptors require a HTTP or
  WebSocket endpoint.

The wider architectural context and token lifetime guarantees are described in
[`docs/architecture.md`](../docs/architecture.md) and
[`docs/configuration.md`](../docs/configuration.md).

## Installation
```bash
cd packages/core
poetry install --no-root
```

## Usage
```python
from datetime import datetime, timezone
from uuid import uuid4

from core import (
    InMemorySessionEventBridge,
    Runner,
    Session,
    SessionEvent,
    SessionStatus,
)

runner = Runner(id="runner-1", base_url="http://runner:8080", total_slots=4)
bridge = InMemorySessionEventBridge()
session = Session(
    id=uuid4(),
    runner_id=runner.id,
    status=SessionStatus.INIT,
    created_at=datetime.now(tz=timezone.utc),
    last_seen_at=datetime.now(tz=timezone.utc),
    headless=False,
    idle_ttl_seconds=300,
)

async def consume() -> None:
    async for event in await bridge.subscribe(replay_latest=True):
        ...

async def produce() -> None:
    await bridge.publish(
        SessionEvent(session=session, occurred_at=datetime.now(tz=timezone.utc))
    )
```

## Testing
```bash
poetry run ruff check .
poetry run pytest -q
```

See [`AGENT_NOTES.md`](AGENT_NOTES.md) for additional constraints, decisions,
and known gaps.
