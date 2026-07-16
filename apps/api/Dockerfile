FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so they cache independently of source changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "nexus_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
