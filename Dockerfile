FROM python:3.12-slim
LABEL io.modelcontextprotocol.server.name="io.github.haechiwood/n8n-preflight"
LABEL org.opencontainers.image.source="https://github.com/haechiwood/mcp-n8n-preflight"
LABEL org.opencontainers.image.description="MCP server: lint exported n8n workflow JSON for failure patterns, leaked secrets and template readiness"
LABEL org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd -m -u 10001 app
USER app
# Mount the folder with your exported workflow .json files at /work (read-only is fine)
WORKDIR /work
ENV N8N_PREFLIGHT_ROOT=/work
ENTRYPOINT ["mcp-n8n-preflight"]
