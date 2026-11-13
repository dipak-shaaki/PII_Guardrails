# syntax=docker/dockerfile:1

# --- Base image -------------------------------------------------------------
# Must match requires-python in pyproject.toml (>=3.14).
FROM python:3.14-slim

# uv gives fast, lockfile-reproducible installs. We copy just the binary.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# --- Dependencies and spaCy model -------------------------------------------
# Copy only the files that define dependencies, then install them. This layer
# is cached and reused until pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-build --no-install-project --group spacy-model

# --- Project code -----------------------------------------------------------
# Run from source; no build step, so no build backend or setup scripts run.
COPY src ./src
ENV PYTHONPATH=/app/src

# --- Run as a non-root user -------------------------------------------------
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SPACY_MODEL=en_core_web_lg

EXPOSE 8000
# One worker on purpose: each worker loads its own spaCy model (RAM).
# PORT is set by some hosts (e.g. Render); defaults to 8000. `exec` forwards SIGTERM.
CMD ["sh", "-c", "exec uvicorn pii_shield.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
