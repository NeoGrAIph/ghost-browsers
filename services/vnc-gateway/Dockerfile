# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/vnc-gateway/pyproject.toml ./pyproject.toml
COPY services/vnc-gateway/app ./app

RUN pip install --upgrade pip wheel setuptools \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/app

WORKDIR /workspace

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY services/vnc-gateway/app /workspace/app

EXPOSE 8000

CMD ["uvicorn", "camou_vnc_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
