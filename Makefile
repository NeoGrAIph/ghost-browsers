.PHONY: bootstrap check

bootstrap:
pnpm install
cd services/gateway && poetry install --no-root
cd services/runner && poetry install --no-root
cd services/vnc-gateway && poetry install --no-root
cd packages/core && poetry install --no-root

check:
pnpm -C apps/ui lint && pnpm -C apps/ui test
cd services/gateway && poetry run ruff check . && poetry run pytest -q
cd services/runner && poetry run ruff check . && poetry run pytest -q
cd services/vnc-gateway && poetry run ruff check . && poetry run pytest -q
cd packages/core && poetry run ruff check . && poetry run pytest -q
