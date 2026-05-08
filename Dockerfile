FROM python:3.11-slim

# Non-root user for security
RUN groupadd -r neurosync && useradd -r -g neurosync neurosync

WORKDIR /app

# Copy only what's needed for install (layer-caches dependencies separately)
COPY pyproject.toml README.md ./
COPY neurosync/ ./neurosync/

RUN pip install --no-cache-dir ".[api]"

# Data volume owned by non-root user
RUN mkdir -p /data && chown neurosync:neurosync /data
VOLUME /data

ENV NEUROSYNC_DATA_DIR=/data

USER neurosync
EXPOSE 8000

CMD ["neurosync", "serve-api", "--host", "0.0.0.0", "--port", "8000"]
