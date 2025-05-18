FROM python:3.13.3-alpine3.21 AS base

# to make smaller image
ENV UV_LINK_MODE=copy
# to precompile bytecode on build time
ENV UV_COMPILE_BYTECODE=1
# use system python, do not download other binary
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first for caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync --locked --no-install-project

# Then copy our codes
ADD . /app

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync --locked

FROM base AS layered

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/src

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

FROM scratch AS final

# Compress all layer to one for faster image download
COPY --from=base / /

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/src

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
