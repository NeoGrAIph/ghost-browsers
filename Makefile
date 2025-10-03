.PHONY: bootstrap check runner-image runner-image-publish vnc-gateway-image vnc-gateway-image-publish

RUNNER_IMAGE ?= ghost-runner:local
RUNNER_DOCKERFILE ?= services/runner/Dockerfile
RUNNER_CONTEXT ?= .
RUNNER_CAMOUFOX_VERSION ?=
RUNNER_EXTRA_BUILD_ARGS ?=
RUNNER_BUILD_ARGS := $(if $(RUNNER_CAMOUFOX_VERSION),--build-arg CAMOUFOX_VERSION=$(RUNNER_CAMOUFOX_VERSION),) $(RUNNER_EXTRA_BUILD_ARGS)
RUNNER_TEST_CMD := set -euo pipefail; poetry check; poetry install --with dev --no-root --no-interaction; PYTHONPATH=. poetry run pytest -q; poetry run python -m camoufox path; poetry run python -m camoufox version
RUNNER_SIGN ?= false
RUNNER_COSIGN_ARGS ?= --yes

VNC_GATEWAY_IMAGE ?= ghost-vnc-gateway:local
VNC_GATEWAY_DOCKERFILE ?= services/vnc-gateway/Dockerfile
VNC_GATEWAY_CONTEXT ?= .
VNC_GATEWAY_EXTRA_BUILD_ARGS ?=
VNC_GATEWAY_BUILD_ARGS := $(VNC_GATEWAY_EXTRA_BUILD_ARGS)
VNC_GATEWAY_SMOKE_CMD := set -euo pipefail; \
	python -m pip install --no-cache-dir pytest ruff; \
	ruff check app tests; \
	pytest -q tests

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

runner-image:
	docker buildx build --load -f $(RUNNER_DOCKERFILE) -t $(RUNNER_IMAGE) $(RUNNER_BUILD_ARGS) $(RUNNER_CONTEXT)
	docker run --rm --entrypoint bash -w /workspace/services/runner $(RUNNER_IMAGE) -lc "$(RUNNER_TEST_CMD)"

runner-image-publish: runner-image
	docker push $(RUNNER_IMAGE)
	@if [ "$(RUNNER_SIGN)" = "true" ]; then \
	cosign sign $(RUNNER_COSIGN_ARGS) $(RUNNER_IMAGE); \
	fi

vnc-gateway-image:
	docker buildx build --load -f $(VNC_GATEWAY_DOCKERFILE) -t $(VNC_GATEWAY_IMAGE) $(VNC_GATEWAY_BUILD_ARGS) $(VNC_GATEWAY_CONTEXT)
	docker run --rm --entrypoint bash -w /opt/app $(VNC_GATEWAY_IMAGE) -lc "$(VNC_GATEWAY_SMOKE_CMD)"

vnc-gateway-image-publish: vnc-gateway-image
	docker push $(VNC_GATEWAY_IMAGE)
