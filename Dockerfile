# Recall web app for Cloud Run. Includes Node.js so the agent can spawn the GitLab MCP server (npx).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

# Node.js 20 (required for the @zereight/mcp-gitlab MCP server via npx)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run provides $PORT (default 8080).
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}
