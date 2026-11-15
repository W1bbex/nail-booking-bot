# Multi-stage production Dockerfile for Nail Atelier Booking Bot & Mini App
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runner image
FROM python:3.12-slim AS runner

WORKDIR /app

# Install runtime dependencies for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root system user
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Copy application source code
COPY --chown=appuser:appgroup . /app

# Create persistent storage directories with correct permissions
RUN mkdir -p /app/data /app/logs && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["python", "bot.py"]
