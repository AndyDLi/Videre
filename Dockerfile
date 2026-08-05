# Start with a lightweight Python image and copy pre-compiled uv binary
FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# Install specific dependencies under /app
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Create a non-root user to run the application
RUN useradd --system --uid 10001 videre
USER videre

ENV PATH="/app/.venv/bin:$PATH"

# Produce a simulator image executing under the simulator module
FROM base AS simulator
ENTRYPOINT ["python", "-m", "videre.simulator"]

# Produce a backend image executing under the backend module
FROM base AS backend
EXPOSE 8000
ENTRYPOINT ["python", "-m", "videre.backend"]
