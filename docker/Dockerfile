# V1 local Compose image for Streamable HTTP / SSE Hosts (SPEC §15.1).
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "enterprise_data_mcp.hosts.streamable_http"]
