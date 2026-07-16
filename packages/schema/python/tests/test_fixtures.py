"""Validate the shared fixtures against BOTH the JSON Schema and the Pydantic
models, so drift between the two bindings fails loudly."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from nexus_schema import IngestBatch, MessageRole, SourceKind

PACKAGE_ROOT = Path(__file__).parent.parent.parent
SCHEMA = json.loads((PACKAGE_ROOT / "ingest.v1.schema.json").read_text())
FIXTURES = sorted((PACKAGE_ROOT / "fixtures").glob("*.json"))

VALIDATOR = Draft202012Validator(SCHEMA)


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_matches_json_schema(fixture: Path) -> None:
    errors = list(VALIDATOR.iter_errors(_load(fixture)))
    assert not errors, "\n".join(e.message for e in errors)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_parses_with_pydantic(fixture: Path) -> None:
    batch = IngestBatch.model_validate(_load(fixture))
    assert batch.schema_version == "nexus.ingest.v1"


def test_fixtures_exist() -> None:
    assert FIXTURES, "no fixtures found — the parametrized tests above ran on nothing"


def test_enums_match_json_schema() -> None:
    defs = SCHEMA["$defs"]
    assert {k.value for k in SourceKind} == set(defs["Source"]["properties"]["kind"]["enum"])
    assert {r.value for r in MessageRole} == set(defs["Message"]["properties"]["role"]["enum"])


def test_pydantic_rejects_what_schema_rejects() -> None:
    batch = _load(FIXTURES[0])

    for mutate in (
        lambda b: b.update(schema_version="nexus.ingest.v2"),
        lambda b: b["source"].update(kind="carrier_pigeon"),
        lambda b: b["conversations"][0].pop("external_id"),
        lambda b: b["conversations"][0]["messages"][0].update(role="narrator"),
        lambda b: b.update(surprise="extra field"),
    ):
        broken = json.loads(json.dumps(batch))
        mutate(broken)
        assert not VALIDATOR.is_valid(broken), "JSON Schema accepted a bad batch"
        with pytest.raises(ValidationError):
            IngestBatch.model_validate(broken)
