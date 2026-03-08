# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution.
RUN pip install --no-cache-dir uv

# Copy dependency manifests first for layer caching.
COPY pyproject.toml uv.lock ./
COPY src/ src/

# Install dependencies into a virtual environment.
RUN uv sync --no-dev --frozen

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy the pre-built virtual environment and source.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY web/ web/

# Activate the virtual environment.
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Cerefox will read configuration from environment variables.
# Required: CEREFOX_SUPABASE_URL, CEREFOX_SUPABASE_KEY
# Optional: CEREFOX_EMBEDDER, CEREFOX_MAX_CHUNK_CHARS, CEREFOX_MAX_RESPONSE_BYTES

EXPOSE 8000

# Health check — the web UI's root returns 200 when configured.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["uvicorn", "cerefox.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
