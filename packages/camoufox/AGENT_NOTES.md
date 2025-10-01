# AGENT_NOTES — camoufox stub

## Overview
Local-only placeholder for the proprietary Camoufox runtime. Provides a
Python module (exposed at the repository root for `python -m camoufox`
compatibility) and CLI compatible with the expectations of the runner
and gateway tests so we can execute unit and lint suites without
downloading the real browser bundle.

## Interfaces
- **Python package**: `camoufox` exposes `get_path`, `get_version`, and a
  synchronous `Camoufox` context manager under `camoufox.sync_api`.
- **CLI**: `python -m camoufox path|version` returns deterministic values
  used by diagnostics in the repository.

## Data & Models
No persistent data. All helpers return constant values suitable for
configuration validation.

## Decisions
- Provide a stub rather than mocking imports so `poetry install` can
  succeed offline and commands like `python -m camoufox path` remain
  functional for smoke tests; the module lives at the repo root while
  Poetry consumes it via a path dependency.
  Путь зависимости фиксируется на корне репозитория (`from = "../.."`),
  чтобы editable-сборки корректно подключали модуль из каталога
  `camoufox/`.

## Constraints & Invariants
- The reported path is `/usr/bin/camoufox` to match existing fixtures and
  health-check expectations.
- Version string stays at `0.0.0-stub`; bumping it requires updating
  tests that assert exact output.

## Known Gaps / TODO
- [ ] Replace the stub with bindings to the real Camoufox runtime once
  distribution becomes available to CI agents.

## How to Test
- `cd packages/camoufox`
- `poetry install --no-root`
- `python -m camoufox path`
- `python -m camoufox version`

## Changelog (for agents)
- 2025-10-09 · gpt-5-codex · Создан локальный stub-пакет Camoufox для
  успешного прохождения unit-тестов без доступа к приватному артефакту.
- 2025-10-12 · gpt-5-codex · Исправлена конфигурация Poetry, чтобы
  editable-установка подтягивала модуль `camoufox` из корня репозитория
  и не падала на `poetry install --no-root` в сервисах.
