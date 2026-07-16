# apps/api

FastAPI backend for Nexus — ingest normalizer, context engine (embeddings,
summaries, rolling profile), provider gateway, assistant engine, handoff
service, and MCP server.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn nexus_api.main:app --reload   # http://localhost:8000/healthz
```

Settings come from `NEXUS_`-prefixed environment variables (or a local `.env`);
see `src/nexus_api/config.py`.

## Checks

```bash
ruff check . && ruff format --check .   # lint + formatting
mypy                                    # strict type checking
pytest                                  # tests
```
