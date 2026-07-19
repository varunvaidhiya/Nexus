"""Context packages: a paste-ready brief that moves work into another tool.

Uses the same retrieval stack as chat context injection (spec §8): goal +
current state from the task/conversation, relevant history via
`build_context`, packed to the target's practical paste size.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.context.retrieval import build_context
from nexus_api.db.models import Conversation, Handoff, Message, Task


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    paste_chars: int
    framing: str


TARGETS = {
    target.key: target
    for target in (
        Target(
            "claude_code",
            "Claude Code",
            24000,
            "You are picking this work up in Claude Code, inside the relevant repository.",
        ),
        Target(
            "cursor",
            "Cursor",
            16000,
            "You are picking this work up in Cursor, inside the relevant repository.",
        ),
        Target(
            "chatgpt",
            "ChatGPT",
            12000,
            "You are picking this work up in a ChatGPT conversation.",
        ),
        Target(
            "generic",
            "another tool",
            12000,
            "You are picking this work up in a new AI session.",
        ),
    )
}

_STATE_MESSAGES = 6


async def build_brief(
    session: Session,
    target: Target,
    *,
    task: Task | None = None,
    conversation: Conversation | None = None,
    instructions: str | None = None,
) -> str:
    if conversation is None and task is not None and task.source_conversation_id:
        conversation = session.get(Conversation, task.source_conversation_id)

    sections = [
        f"# Nexus handoff — continue in {target.label}",
        f"{target.framing} This brief was generated on "
        f"{datetime.now(UTC).date().isoformat()} from the user's private cross-tool "
        "AI memory. Read it fully, then continue the work.",
    ]

    goal_lines = []
    if task is not None:
        goal_lines.append(f"**{task.title}**")
        if task.detail:
            goal_lines.append(task.detail)
        if task.why_it_matters:
            goal_lines.append(f"Why it matters: {task.why_it_matters}")
        if task.due_at:
            goal_lines.append(f"Due: {task.due_at.date().isoformat()}")
    elif conversation is not None:
        goal_lines.append(f"Continue the work from: **{conversation.title or 'untitled'}**")
    sections.append("## Goal\n" + "\n\n".join(goal_lines))

    if conversation is not None:
        state = [f"From the conversation “{conversation.title or 'untitled'}”"]
        if conversation.project:
            state.append(f"Project: {conversation.project}")
        if conversation.summary:
            state.append(conversation.summary)
        tail = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(_STATE_MESSAGES)
        ).all()
        if tail:
            transcript = "\n".join(f"> {m.role.value}: {m.content[:600]}" for m in reversed(tail))
            state.append("Last exchanges:\n" + transcript)
        sections.append("## Current state\n" + "\n\n".join(state))

    query = task.title if task is not None else (conversation.title if conversation else "") or ""
    if query:
        bundle = await build_context(
            session,
            query,
            exclude_conversation_id=conversation.id if conversation is not None else None,
        )
        if bundle is not None:
            sections.append("## Context from Nexus memory\n" + bundle.text)

    steps = instructions or (
        "Review the goal and current state above, then continue where the work "
        "left off. Ask the user before changing direction."
    )
    sections.append("## Next steps\n" + steps)

    brief = "\n\n".join(sections)
    if len(brief) > target.paste_chars:
        brief = brief[: target.paste_chars].rstrip() + "\n\n[truncated to fit paste budget]"
    return brief


def log_handoff(
    session: Session,
    *,
    target: str,
    task_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    brief: str | None = None,
    note: str | None = None,
) -> Handoff:
    handoff = Handoff(
        target=target, task_id=task_id, conversation_id=conversation_id, brief=brief, note=note
    )
    session.add(handoff)
    session.flush()
    return handoff
