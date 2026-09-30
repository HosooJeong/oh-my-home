"""Versioned boundaries shared by intake, category modules and aggregation."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

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


class MetricParameters(TypedDict, total=False):
    school_level: Annotated[str, Field(max_length=200)] | None
    school_id: Annotated[str, Field(max_length=200)] | None
    subject: Annotated[str, Field(max_length=200)] | None
    radius_m: Annotated[str, Field(max_length=200)] | None


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
    parameters: MetricParameters = Field(default_factory=dict)

    @field_validator('parameters')
    @classmethod
    def supplied_parameters(cls, value):
        return {key: item for key, item in value.items() if item is not None}

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


class ReferenceDistribution(Contract):
    label: Text
    unit: Text
    count: Annotated[int, Field(ge=0)]
    minimum: Number | None
    q25: Number | None
    median: Number | None
    q75: Number | None
    maximum: Number | None

    @model_validator(mode="after")
    def ordered(self):
        values = [self.minimum, self.q25, self.median, self.q75, self.maximum]
        if any(v is None for v in values):
            if any(v is not None for v in values):
                raise ValueError("partial distribution")
        elif values != sorted(values) or self.count < 5:
            raise ValueError("invalid or undersized distribution")
        return self


class ReferenceResult(Contract):
    """Informational category output: never score evidence or a hard-condition verdict."""
    module_id: Identifier
    module_version: Text
    profile_fingerprint: str | None
    candidates_fingerprint: str | None
    status: Literal["available", "insufficient", "empty", "unavailable"]
    query_fingerprint: str
    scope: Text
    sample_count: Annotated[int, Field(ge=0)]
    distributions: list[ReferenceDistribution]
    contract_counts: dict[str, Annotated[int, Field(ge=0)]]
    source_url: SourceURL
    period_start: str | None
    period_end: str | None
    retrieved_at: str | None
    snapshot_fingerprint: str | None
    limitations: list[Text]

    @model_validator(mode="after")
    def consistent(self):
        if any(d.count != self.sample_count for d in self.distributions) or sum(self.contract_counts.values()) != self.sample_count:
            raise ValueError("reference sample counts differ")
        if self.status == "available" and (self.sample_count < 5 or not self.distributions
                or any(d.median is None for d in self.distributions)):
            raise ValueError("reference summary is unavailable")
        if self.status == "insufficient" and (not 0 < self.sample_count < 5
                or any(d.median is not None for d in self.distributions)):
            raise ValueError("undersized reference must withhold summaries")
        if self.status in ("empty", "unavailable") and (self.sample_count or self.distributions):
            raise ValueError("empty reference has measurements")
        if self.status != "unavailable" and not all((self.period_start, self.period_end, self.retrieved_at, self.snapshot_fingerprint)):
            raise ValueError("reference provenance missing")
        return self


class CctvObservation(Contract):
    candidate_id: Identifier
    status: Literal['available', 'stale', 'unavailable', 'outside_scope']
    registered_rows_within_radius: Annotated[int, Field(ge=0)] | None
    registered_coordinate_points_within_radius: Annotated[int, Field(ge=0)] | None
    nearest_distance_m: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    nearest_source_records: list[Text]
    purposes_within_radius: list[Text]
    area_code: str | None
    area_name: str | None

    @model_validator(mode='after')
    def measured(self):
        rows, points = self.registered_rows_within_radius, self.registered_coordinate_points_within_radius
        if self.status in ('available', 'stale'):
            if rows is None or points is None or points > rows or self.nearest_distance_m is None or not self.nearest_source_records:
                raise ValueError('invalid CCTV observation')
        elif any(v is not None for v in (rows, points, self.nearest_distance_m)) or self.nearest_source_records:
            raise ValueError('unavailable CCTV observation has measurements')
        return self


class SafetyReferenceResult(Contract):
    """Registered CCTV snapshot, separated from crime/risk/safety score evidence."""
    module_id: Literal['safety']
    module_version: Text
    profile_fingerprint: str
    candidates_fingerprint: str
    status: Literal['available', 'partial', 'unavailable']
    radius_m: Annotated[float, Field(gt=0, le=5000, allow_inf_nan=False)]
    source_url: SourceURL
    publication_date: str | None
    retrieved_at: str | None
    snapshot_fingerprint: str | None
    excluded_coordinate_rows: Annotated[int, Field(ge=0)] | None
    observations: list[CctvObservation]
    limitations: list[Text]
    score_eligible: Literal[False] = False

    @model_validator(mode='after')
    def traceable(self):
        if len({o.candidate_id for o in self.observations}) != len(self.observations):
            raise ValueError('duplicate reference candidate')
        if any(o.status in ('available', 'stale') for o in self.observations) and not all(
                (self.publication_date, self.retrieved_at, self.snapshot_fingerprint)):
            raise ValueError('reference provenance missing')
        if self.status == 'available' and (not self.observations or any(o.status != 'available' for o in self.observations)):
            raise ValueError('incomplete safety reference')
        if self.status == 'unavailable' and any(o.status in ('available', 'stale') for o in self.observations):
            raise ValueError('unavailable reference has data')
        return self


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
