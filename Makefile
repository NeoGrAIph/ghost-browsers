.PHONY: bootstrap check runner-image runner-image-publish gateway-image gateway-image-publish vnc-gateway-image vnc-gateway-image-publish ui-image

RUNNER_IMAGE ?= ghost-runner:local
RUNNER_DOCKERFILE ?= services/runner/Dockerfile
RUNNER_CONTEXT ?= .
RUNNER_CAMOUFOX_VERSION ?=
RUNNER_EXTRA_BUILD_ARGS ?=
RUNNER_BUILD_ARGS := $(if $(RUNNER_CAMOUFOX_VERSION),--build-arg CAMOUFOX_VERSION=$(RUNNER_CAMOUFOX_VERSION),) $(RUNNER_EXTRA_BUILD_ARGS)
RUNNER_TEST_CMD := set -euo pipefail; poetry check; poetry install --with dev --no-root --no-interaction; PYTHONPATH=. poetry run pytest -q; poetry run python -m camoufox path; poetry run python -m camoufox version
RUNNER_SIGN ?= false
RUNNER_COSIGN_ARGS ?= --yes

GATEWAY_IMAGE ?= ghost-gateway:local
GATEWAY_DOCKERFILE ?= services/gateway/Dockerfile
GATEWAY_CONTEXT ?= .
GATEWAY_EXTRA_BUILD_ARGS ?=
GATEWAY_BUILD_ARGS := $(GATEWAY_EXTRA_BUILD_ARGS)
GATEWAY_SIGN ?= false
GATEWAY_COSIGN_ARGS ?= --yes

VNC_GATEWAY_IMAGE ?= ghost-vnc-gateway:local
VNC_GATEWAY_DOCKERFILE ?= services/vnc-gateway/Dockerfile
VNC_GATEWAY_CONTEXT ?= .
VNC_GATEWAY_EXTRA_BUILD_ARGS ?=
VNC_GATEWAY_BUILD_ARGS := $(VNC_GATEWAY_EXTRA_BUILD_ARGS)
VNC_GATEWAY_SIGN ?= false
VNC_GATEWAY_COSIGN_ARGS ?= --yes
VNC_GATEWAY_SMOKE_CMD := poetry install --with dev --no-root --no-interaction && poetry run ruff check . && poetry run pytest -q

UI_IMAGE ?= ghost-ui:local
UI_DOCKERFILE ?= apps/ui/Dockerfile
UI_CONTEXT ?= .
UI_EXTRA_BUILD_ARGS ?=
UI_BUILD_ARGS := $(UI_EXTRA_BUILD_ARGS)

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

gateway-image:
	docker buildx build --load -f $(GATEWAY_DOCKERFILE) -t $(GATEWAY_IMAGE) $(GATEWAY_BUILD_ARGS) $(GATEWAY_CONTEXT)

gateway-image-publish: gateway-image
        docker push $(GATEWAY_IMAGE)
        @if [ "$(GATEWAY_SIGN)" = "true" ]; then \
        cosign sign $(GATEWAY_COSIGN_ARGS) $(GATEWAY_IMAGE); \
        fi

vnc-gateway-image:
        cd services/vnc-gateway && $(VNC_GATEWAY_SMOKE_CMD)
        docker buildx build --load -f $(VNC_GATEWAY_DOCKERFILE) -t $(VNC_GATEWAY_IMAGE) $(VNC_GATEWAY_BUILD_ARGS) $(VNC_GATEWAY_CONTEXT)

vnc-gateway-image-publish: vnc-gateway-image
        docker push $(VNC_GATEWAY_IMAGE)
        @if [ "$(VNC_GATEWAY_SIGN)" = "true" ]; then \
        cosign sign $(VNC_GATEWAY_COSIGN_ARGS) $(VNC_GATEWAY_IMAGE); \
        fi

ui-image:
        pnpm -C apps/ui lint
        pnpm -C apps/ui test
        docker buildx build --load -f $(UI_DOCKERFILE) -t $(UI_IMAGE) $(UI_BUILD_ARGS) $(UI_CONTEXT)
