"""Versioned boundaries shared by intake, category modules and aggregation."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Number = FiniteFloat
Weight = Annotated[FiniteFloat, Field(ge=0, le=100)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
SourceURL = Annotated[str, Field(pattern=r"^https?://[^\s]+$")]
CATEGORIES = ("housing", "transport", "education", "living", "safety", "leisure")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class PreferenceGroup(Contract):
    id: Identifier
    label: Text
    weight: Weight
    source: Literal["user", "proposed"]
    reason: Text


class UtilityRule(Contract):
    """Linear satisfaction curve, NOT a hard feasibility constraint."""
    direction: Literal["lower", "higher", "target", "boolean"]
    ideal: Number
    limit: Number
    unit: Text

    @model_validator(mode="after")
    def ordered(self):
        if self.direction == "lower" and self.ideal >= self.limit:
            raise ValueError("lower requires ideal < limit")
        if self.direction == "higher" and self.ideal <= self.limit:
            raise ValueError("higher requires ideal > limit")
        if self.direction == "target" and self.limit <= 0:
            raise ValueError("target limit must be a positive tolerance")
        if self.direction == "boolean" and (self.ideal not in (0, 1) or self.limit != 0):
            raise ValueError("boolean requires ideal 0/1 and limit 0")
        return self


class HardRule(Contract):
    operator: Literal["lte", "gte", "eq"]
    value: Number


class Criterion(Contract):
    id: Identifier
    group_id: Identifier
    module_id: Identifier
    label: Text
    need: Text
    source_quote: Text
    source: Literal["user", "proposed"]
    importance: Weight
    importance_source: Literal["user", "proposed"]
    metric: Identifier
    utility: UtilityRule | None
    hard: HardRule | None

    @model_validator(mode="after")
    def explicit_hard(self):
        if self.hard is not None and self.source != "user":
            raise ValueError("hard constraints require an explicit user need")
        if self.hard is not None and self.utility is None:
            raise ValueError("hard constraint needs a metric unit")
        return self


class Question(Contract):
    id: Identifier
    text: Text
    reason: Text
    criterion_ids: list[Identifier]
    blocking: bool


class ContextFact(Contract):
    key: Identifier
    value: Text
    source_quote: Text


class NeedProfile(Contract):
    schema_version: Literal["1"]
    revision: Annotated[int, Field(ge=1)]
    request: Text
    context: list[ContextFact]
    groups: Annotated[list[PreferenceGroup], Field(min_length=1, max_length=20)]
    criteria: Annotated[list[Criterion], Field(min_length=1, max_length=50)]
    questions: Annotated[list[Question], Field(max_length=10)]

    @model_validator(mode="after")
    def references(self):
        def unique(values, name):
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate {name}")
        unique([g.id for g in self.groups], "group")
        unique([c.id for c in self.criteria], "criterion")
        unique([q.id for q in self.questions], "question")
        groups = {g.id for g in self.groups}
        criteria = {c.id for c in self.criteria}
        if any(c.group_id not in groups for c in self.criteria):
            raise ValueError("criterion references an unknown group")
        if any(set(q.criterion_ids) - criteria for q in self.questions):
            raise ValueError("question references an unknown criterion")
        if sum(g.weight for g in self.groups) <= 0:
            raise ValueError("at least one group must have positive weight")
        for g in self.groups:
            assigned = [c for c in self.criteria if c.group_id == g.id]
            if not assigned or (g.weight > 0 and sum(c.importance for c in assigned) <= 0):
                raise ValueError("each active group needs a weighted criterion")
        return self

    def fingerprint(self) -> str:
        return digest(self.model_dump())


class InterviewTurn(Contract):
    question_id: Identifier
    answer: Text


class Candidate(Contract):
    id: Identifier
    label: Text
    latitude: Annotated[FiniteFloat, Field(ge=-90, le=90)]
    longitude: Annotated[FiniteFloat, Field(ge=-180, le=180)]
    origin: Literal["user", "generated", "fixture"]


class CriterionWeight(Contract):
    criterion_id: Identifier
    weight: Annotated[FiniteFloat, Field(ge=0, le=1)]


class ModuleRequest(Contract):
    run_id: str
    profile_fingerprint: str
    module_id: Identifier
    criteria: list[Criterion]
    weights: list[CriterionWeight]
    candidates: list[Candidate]

    def fingerprint(self) -> str:
        return digest(self.model_dump())


class Evidence(Contract):
    id: Identifier
    candidate_id: Identifier
    criterion_id: Identifier
    value: Number | None
    unit: Text
    status: Literal["verified", "missing", "conflicting"]
    source_url: SourceURL | None
    source_record: Text | None
    data_date: Text | None
    retrieved_at: Text | None
    method: Text
    note: Text

    @model_validator(mode="after")
    def traceable(self):
        if self.status == "verified" and (
            self.value is None or not self.source_url or not self.source_record
            or not self.data_date or not self.retrieved_at
        ):
            raise ValueError("verified evidence requires value and provenance")
        return self


class CategoryResult(Contract):
    module_id: Identifier
    module_version: Text
    request_fingerprint: str
    status: Literal["completed", "partial", "failed"]
    evidence: list[Evidence]
    unsupported_criterion_ids: list[Identifier]
    questions: list[Question]
    error_code: str | None


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def output_schema(model: type[Contract]) -> dict:
    """All properties required, nullable instead of optional, no unknown fields."""
    schema = model.model_json_schema()
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    return schema
