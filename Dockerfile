# ============================================================
# GameHub Production Dockerfile — Multi-Stage Build
# ============================================================
# Stage 1: Builder — install dependencies into an isolated venv
# Stage 2: Runtime — copy only the built venv + app source
# ============================================================

# --------------- STAGE 1: BUILDER ---------------
FROM python:3.12-slim AS builder

# Prevent .pyc files and force unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install build-time system dependencies required by asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Create a virtual environment inside the builder stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install pinned production dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# --------------- STAGE 2: RUNTIME ---------------
FROM python:3.12-slim AS runtime

# Prevent .pyc files and force unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the minimal runtime library needed by asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root security user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source code
COPY main.py config.py ./
COPY api/ ./api/
COPY bot/ ./bot/
COPY database/ ./database/
COPY services/ ./services/
COPY proxy/ ./proxy/

# Ensure the appuser owns the application directory
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the internal API gateway port
EXPOSE 8080

# Production entrypoint — Uvicorn with 2 workers
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
