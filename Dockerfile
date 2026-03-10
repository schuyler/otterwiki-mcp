FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY otterwiki_mcp/ ./otterwiki_mcp/

RUN pip install --no-cache-dir .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8090

CMD ["python", "-m", "otterwiki_mcp.server"]
