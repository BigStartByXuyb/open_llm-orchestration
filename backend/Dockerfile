# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install dependencies into a virtual environment
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools needed for some native extensions (psycopg2-binary is
# pre-compiled, but other wheels may need gcc/libpq-dev at build time).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtual environment so the final stage can copy it cleanly.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the package manifest first to leverage Docker layer cache.
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package and all runtime dependencies.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — lean image, non-root user
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system deps: libpq for psycopg2-binary, curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source.
COPY --from=builder /app/src ./src

# ── Non-root user ──────────────────────────────────────────────────────────
# Running as non-root reduces attack surface.
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid appgroup --no-create-home appuser

USER appuser

# ── Runtime defaults ───────────────────────────────────────────────────────
# These can be overridden by docker-compose / k8s environment.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

EXPOSE 8000

# Liveness probe endpoint used by docker-compose healthcheck.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command — override in docker-compose for different worker counts.
CMD ["uvicorn", "orchestration.gateway.app:create_app", \
     "--factory", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
