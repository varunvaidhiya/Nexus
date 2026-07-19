# Nexus as an MCP server

Nexus exposes its memory over the [Model Context Protocol](https://modelcontextprotocol.io)
at `POST /mcp` (Streamable HTTP transport), so MCP-capable clients pull live
context instead of pasting briefs. This is the cleanest long-term handoff
path (spec §8).

## Tools

| Tool | What it returns |
| --- | --- |
| `search_memory` | Hybrid keyword + semantic search over every captured message |
| `get_profile` | The rolling profile (active projects, preferences, open loops) |
| `get_open_tasks` | Open tasks with status, priority, and due dates |
| `get_conversation` | One conversation's title, summary, and messages |
| `log_handoff` | Records that work moved to another tool |

## Auth

Same device-token gate as `/ingest`: create a token in **Settings → Devices**
and send it as a bearer header. The main `NEXUS_AUTH_TOKEN` also works, but
prefer a device token per client — it can be revoked on its own and never
unlocks the rest of the API.

## Claude Code

```bash
claude mcp add --transport http nexus http://localhost:8000/mcp \
  --header "Authorization: Bearer nxd_..."
```

Then in a session: "search my memory for the flaky login test discussion".

## Cursor

Add to `~/.cursor/mcp.json` (or the project's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer nxd_..." }
    }
  }
}
```

## Notes

- The endpoint is stateless: no session IDs, plain JSON responses (the
  transport spec permits this in place of SSE streams), protocol versions
  2024-11-05 through 2025-06-18.
- Only the tools capability is advertised — no resources/prompts yet.
- If Nexus runs on another machine, put it behind TLS before pointing
  clients at it; device tokens travel in headers.
