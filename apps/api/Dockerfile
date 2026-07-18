# Build context is the repo root (the image needs packages/schema too):
#   docker build -f apps/api/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# The canonical ingest contract, then the API itself.
COPY packages/schema/python /opt/nexus-schema
RUN pip install --no-cache-dir /opt/nexus-schema

COPY apps/api/pyproject.toml apps/api/README.md ./
COPY apps/api/src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "nexus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
