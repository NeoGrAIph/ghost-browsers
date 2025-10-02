# AGENT_NOTES — camoufox wrapper

## Overview
Compatibility layer that re-exports the official [`camoufox`](https://pypi.org/project/camoufox/) SDK while keeping the legacy import surface used across the repository. The shim lives at the repository root (`camoufox/`) so `python -m camoufox ...` stays functional in development environments.

## Interfaces
- **Python package**: `camoufox` re-exports the upstream synchronous API (`camoufox.sync_api.Camoufox`, `NewBrowser`), helper utilities (`launch_options`, `DefaultAddons`) and adds thin wrappers `get_path`/`get_version` that avoid triggering implicit downloads during tests.
- **CLI**: `python -m camoufox {path,version,fetch,...}` delegates to the upstream Click commands without modification.

## Data & Models
No persistent data beyond what the upstream SDK stores under its installation directory (`~/.cache/camoufox` by default). Tests create disposable installation directories with synthetic `version.json` files to keep the SDK satisfied.

## Decisions
- Replaced the bespoke stub with a loader that imports the official SDK through `importlib.metadata`/`importlib.util`. This keeps our package importable even though the distribution name (`camoufox`) collides with the upstream one.
- Added compatibility helpers (`get_path`, `get_version`) that call into `camoufox.pkgman` but default to `download_if_missing=False` to prevent unintended network calls during unit tests.
- Packaged the shim as `ghost-camoufox-wrapper` so Poetry environments can depend on it without shadowing the upstream distribution name.

## Constraints & Invariants
- The upstream SDK **must** be installed (pinned to `camoufox==0.4.11[geoip]`). Without it `_bootstrap_sdk()` raises `ImportError`.
- `get_path()` raises `FileNotFoundError` when binaries are absent; callers are expected to run `python -m camoufox fetch` ahead of time.
- The package search path (`__path__`) is extended with the upstream installation directory to keep submodule imports working (`camoufox.errors`, `camoufox.pkgman`, etc.).

## Known Gaps / TODO
- [ ] Consider exposing async helpers (`AsyncCamoufox`, etc.) explicitly once runner code consumes them.
- [ ] Evaluate whether we need to surface additional SDK utilities (addons management, locale helpers) as the services mature.

## How to Test
- `cd packages/camoufox`
- `poetry install --no-root`
- `poetry run python -m camoufox path`
- `poetry run python -m camoufox version`

## Changelog (for agents)
- 2025-10-09 · gpt-5-codex · Создан локальный stub-пакет Camoufox для unit-тестов без приватного бинарника.
- 2025-10-12 · gpt-5-codex · Исправлена конфигурация Poetry, чтобы editable-установка подтягивала модуль `camoufox` из корня репозитория.
- 2025-10-25 · ChatGPT · Заменён stub на обёртку поверх официального SDK, добавлены совместимые CLI/API прокси и автотестовые фикстуры.
