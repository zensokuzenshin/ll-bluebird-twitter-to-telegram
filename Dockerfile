FROM python:3.14.7-alpine3.24 AS base

# to make smaller image
ENV UV_LINK_MODE=copy
# to precompile bytecode on build time
ENV UV_COMPILE_BYTECODE=1
# use system python, do not download other binary
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first for caching. The lint group is build-time only;
# leaving it out keeps the ruff binary (~24MB) out of the runtime image.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=from=ghcr.io/astral-sh/uv:0.12.10,source=/uv,target=/bin/uv \
    uv sync --locked --no-group lint --no-install-project

# Then copy our codes
ADD . /app

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=from=ghcr.io/astral-sh/uv:0.12.10,source=/uv,target=/bin/uv \
    uv sync --locked --no-group lint

FROM scratch AS final

# Compress all layers into one for faster image download
COPY --from=base / /

ENV PATH="/app/.venv/bin:$PATH"
# JSON logs for Loki/Vector ingestion (override with LOG_FORMAT=text)
ENV LOG_FORMAT=json
WORKDIR /app/src

CMD ["python", "server.py"]
