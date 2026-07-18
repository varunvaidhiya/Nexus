"""Idempotent ingestion of canonical batches (the nexus.ingest.v1 contract).

Dedupe rules (spec §5.1):
- source: one row per (kind, name)
- conversation: (source_id, external_id)
- message: external_id when the source system has one, otherwise a
  (role, sha256(content)) fingerprint — re-sending anything never duplicates.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from nexus_schema import IngestBatch, IngestConversation
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import Conversation, Message, MessageRole, Source, SourceKind


@dataclass
class IngestReport:
    conversations: int = 0
    new_conversations: int = 0
    new_messages: int = 0
    skipped_messages: int = 0


def _fingerprint(role: str, content: str) -> str:
    return hashlib.sha256(f"{role}\x00{content}".encode()).hexdigest()


def _get_or_create_source(session: Session, batch: IngestBatch) -> Source:
    kind = SourceKind(batch.source.kind.value)
    name = batch.source.name or batch.source.kind.value
    source = session.scalars(select(Source).where(Source.kind == kind, Source.name == name)).first()
    if source is None:
        source = Source(name=name, kind=kind, ingest_tier=batch.source.ingest_tier.value)
        session.add(source)
        session.flush()
    source.last_synced_at = datetime.now(UTC)
    return source


def ingest_batch(session: Session, batch: IngestBatch) -> IngestReport:
    report = IngestReport()
    source = _get_or_create_source(session, batch)
    for incoming in batch.conversations:
        _ingest_conversation(session, source, incoming, report)
    session.commit()
    return report


def _ingest_conversation(
    session: Session, source: Source, incoming: IngestConversation, report: IngestReport
) -> None:
    report.conversations += 1
    conversation = session.scalars(
        select(Conversation).where(
            Conversation.source_id == source.id,
            Conversation.external_id == incoming.external_id,
        )
    ).first()
    if conversation is None:
        conversation = Conversation(
            source_id=source.id,
            external_id=incoming.external_id,
            title=incoming.title,
            model=incoming.model,
            tool=incoming.tool,
            project=incoming.project,
            started_at=incoming.started_at,
            tags=list(incoming.tags),
        )
        session.add(conversation)
        session.flush()
        report.new_conversations += 1
    else:
        # Fill blanks without clobbering established metadata.
        conversation.title = conversation.title or incoming.title
        conversation.model = incoming.model or conversation.model
        conversation.project = conversation.project or incoming.project

    existing = session.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()
    seen_external = {m.external_id for m in existing if m.external_id}
    seen_fingerprints = {_fingerprint(m.role.value, m.content) for m in existing}

    added = False
    for message in incoming.messages:
        if not message.content:
            continue
        if message.external_id and message.external_id in seen_external:
            report.skipped_messages += 1
            continue
        fingerprint = _fingerprint(message.role.value, message.content)
        if not message.external_id and fingerprint in seen_fingerprints:
            report.skipped_messages += 1
            continue
        session.add(
            Message(
                conversation_id=conversation.id,
                external_id=message.external_id,
                role=MessageRole(message.role.value),
                content=message.content,
                token_count=message.token_count,
                created_at=message.created_at or datetime.now(UTC),
            )
        )
        if message.external_id:
            seen_external.add(message.external_id)
        seen_fingerprints.add(fingerprint)
        report.new_messages += 1
        added = True

    if added:
        # Nudge updated_at so the summarize/embed jobs pick this up.
        conversation.updated_at = incoming.updated_at or datetime.now(UTC)
    session.flush()
