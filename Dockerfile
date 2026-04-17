FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY neurosync/ neurosync/

RUN pip install --no-cache-dir .

ENV NEUROSYNC_DATA_DIR=/data
VOLUME /data

ENTRYPOINT ["python", "-m", "neurosync.mcp_server"]
