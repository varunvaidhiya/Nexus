"""Nexus as an MCP server (spec §5.3): POST /mcp, Streamable HTTP transport.

Hand-rolled minimal JSON-RPC handler rather than an SDK — same philosophy as
the provider gateway's raw SSE. Supports initialize / tools/list / tools/call
/ ping with plain-JSON responses (the transport spec allows a single JSON
response instead of an SSE stream), stateless (no session IDs). Auth is the
same device-token gate as /ingest, applied at mount time.

Tools: search_memory, get_profile, get_open_tasks, get_conversation,
log_handoff.
"""

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import __version__
from nexus_api.context.search import hybrid_search
from nexus_api.db.models import Conversation, Message, ProfileSnapshot, Task, TaskStatus
from nexus_api.db.session import get_session
from nexus_api.services.handoff import TARGETS, log_handoff

logger = structlog.get_logger()

router = APIRouter(tags=["mcp"])

SessionDep = Annotated[Session, Depends(get_session)]

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_memory",
        "description": (
            "Search the user's cross-tool AI memory (every captured conversation, "
            "hybrid keyword + semantic). Returns matching message snippets with "
            "their conversation ids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_profile",
        "description": "The user's rolling profile: active projects, preferences, open loops.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_open_tasks",
        "description": "The user's open tasks (todo/doing/blocked) with priority and due dates.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_conversation",
        "description": "Full detail of one conversation: title, summary, and messages.",
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}},
            "required": ["conversation_id"],
        },
    },
    {
        "name": "log_handoff",
        "description": (
            "Record that work was handed off to another tool, so Nexus can track "
            f"the thread. Targets: {', '.join(sorted(TARGETS))}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "task_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["target"],
        },
    },
]


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_text(request_id: Any, text: str, *, is_error: bool = False) -> dict[str, Any]:
    return _result(request_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


@router.post("/mcp")
async def mcp_endpoint(message: dict[str, Any] | list[Any], session: SessionDep) -> Response:
    """Single JSON-RPC message (2025-06-18) or a batch (2025-03-26)."""
    import json

    if isinstance(message, list):
        replies = [await _dispatch(m, session) for m in message if isinstance(m, dict)]
        replies = [r for r in replies if r is not None]
        if not replies:
            return Response(status_code=202)
        return Response(content=json.dumps(replies), media_type="application/json")

    reply = await _dispatch(message, session)
    if reply is None:  # notification
        return Response(status_code=202)
    return Response(content=json.dumps(reply), media_type="application/json")


@router.get("/mcp")
def mcp_get() -> Response:
    # No server-initiated stream; clients fall back to plain request/response.
    return Response(status_code=405, headers={"Allow": "POST"})


async def _dispatch(message: dict[str, Any], session: Session) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return _error(request_id, -32600, "invalid request: missing method")
    if method.startswith("notifications/"):
        return None
    params = message.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nexus", "version": __version__},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            return await _call_tool(request_id, name, arguments, session)
        except Exception as exc:
            logger.exception("mcp tool failed", tool=name)
            return _tool_text(request_id, f"{type(exc).__name__}: {exc}", is_error=True)
    return _error(request_id, -32601, f"method not found: {method}")


async def _call_tool(
    request_id: Any, name: Any, arguments: dict[str, Any], session: Session
) -> dict[str, Any]:
    import json

    if name == "search_memory":
        query = str(arguments.get("query") or "")
        if not query:
            return _tool_text(request_id, "query is required", is_error=True)
        limit = arguments.get("limit")
        hits = await hybrid_search(
            session, query, limit=min(int(limit), 25) if isinstance(limit, int) else 10
        )
        payload = [
            {
                "conversation_id": str(hit.conversation_id),
                "conversation_title": hit.conversation_title,
                "role": hit.role,
                "snippet": hit.snippet,
                "created_at": hit.created_at.isoformat(),
                "matched": hit.matched,
            }
            for hit in hits
        ]
        return _tool_text(request_id, json.dumps(payload))

    if name == "get_profile":
        snapshot = session.scalars(
            select(ProfileSnapshot).order_by(ProfileSnapshot.generated_at.desc())
        ).first()
        if snapshot is None:
            return _tool_text(request_id, "No profile has been generated yet.")
        return _tool_text(request_id, snapshot.content)

    if name == "get_open_tasks":
        tasks = session.scalars(
            select(Task)
            .where(Task.status != TaskStatus.done)
            .order_by(Task.priority.desc(), Task.created_at)
        ).all()
        tasks_payload: list[dict[str, Any]] = [
            {
                "id": str(task.id),
                "title": task.title,
                "status": task.status.value,
                "priority": task.priority,
                "due_at": task.due_at.isoformat() if task.due_at else None,
                "why_it_matters": task.why_it_matters,
            }
            for task in tasks
        ]
        return _tool_text(request_id, json.dumps(tasks_payload))

    if name == "get_conversation":
        conversation_id = _parse_uuid(arguments.get("conversation_id"))
        conversation = session.get(Conversation, conversation_id) if conversation_id else None
        if conversation is None:
            return _tool_text(request_id, "unknown conversation", is_error=True)
        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
            .limit(200)
        ).all()
        detail_payload: dict[str, Any] = {
            "title": conversation.title,
            "project": conversation.project,
            "summary": conversation.summary,
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content[:2000],
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }
        return _tool_text(request_id, json.dumps(detail_payload))

    if name == "log_handoff":
        target = str(arguments.get("target") or "")
        if target not in TARGETS:
            return _tool_text(
                request_id,
                f"unknown target (expected one of: {', '.join(sorted(TARGETS))})",
                is_error=True,
            )
        handoff = log_handoff(
            session,
            target=target,
            task_id=_parse_uuid(arguments.get("task_id")),
            conversation_id=_parse_uuid(arguments.get("conversation_id")),
            note=str(arguments["note"])[:2000] if arguments.get("note") else None,
        )
        return _tool_text(request_id, json.dumps({"handoff_id": str(handoff.id)}))

    return _tool_text(request_id, f"unknown tool: {name}", is_error=True)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
