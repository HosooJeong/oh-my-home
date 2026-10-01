"""One controller dispatches category modules and validates every returned fact."""
from dataclasses import dataclass, field
from threading import Event
from typing import Protocol
from uuid import uuid4

from .contracts import Candidate, CategoryResult, CriterionWeight, ModuleRequest, NeedProfile, ReferenceResult, SafetyReferenceResult, digest
from .evaluation import evaluate, weights


class CategoryModule(Protocol):
    id: str
    version: str

    def run(self, request: ModuleRequest, cancel: Event) -> CategoryResult: ...


@dataclass
class Orchestrator:
    modules: dict[str, CategoryModule]
    reference_modules: dict = field(default_factory=dict)

    def __post_init__(self):
        if any(key != module.id for key, module in self.modules.items()):
            raise ValueError("registry key and module id differ")
        if any(key != module.id for key, module in self.reference_modules.items()):
            raise ValueError("reference registry key and module id differ")

    def run(self, profile: NeedProfile, candidates: list[Candidate], cancel: Event | None = None,
            *, include_references: bool = True, on_event=None) -> dict:
        profile = NeedProfile.model_validate(profile.model_dump())
        candidates = [Candidate.model_validate(c.model_dump()) for c in candidates]
        if len({c.id for c in candidates}) != len(candidates) or not candidates:
            raise ValueError("nonempty, unique candidates required")
        cancel = cancel or Event()
        run_id = str(uuid4())
        identity = {"profile_fingerprint": profile.fingerprint(),
                    "candidates_fingerprint": digest([c.model_dump() for c in candidates])}
        events = []
        def emit(event):
            events.append(event)
            if on_event:
                on_event(dict(event))
        emit({"stage": "planned", "run_id": run_id})
        if any(q.blocking for q in profile.questions):
            return {**identity, "run_id": run_id, "status": "awaiting_input", "events": events,
                    "questions": [q.model_dump() for q in profile.questions], "report": None,
                    "modules": []}
        results, all_evidence, evidence_ids = [], [], set()
        normalized = weights(profile)
        active = [c for c in profile.criteria if normalized[c.id] > 0 or c.hard is not None]
        module_ids = list(dict.fromkeys(c.module_id for c in active))
        module_ids.sort(key=lambda id: (-any(c.hard for c in active if c.module_id == id),
                                      -sum(normalized[c.id] for c in active if c.module_id == id)))
        for module_id in module_ids:
            if cancel.is_set():
                return {**identity, "run_id": run_id, "status": "cancelled", "events": events,
                        "report": None, "modules": results, "questions": []}
            request = ModuleRequest(run_id=run_id, profile_fingerprint=profile.fingerprint(),
                                    module_id=module_id,
                                    criteria=[c for c in active if c.module_id == module_id],
                                    weights=[CriterionWeight(criterion_id=c.id, weight=normalized[c.id])
                                             for c in active if c.module_id == module_id],
                                    candidates=candidates)
            module = self.modules.get(module_id)
            emit({"stage": "module_started", "module_id": module_id})
            if module is None:
                result = CategoryResult(module_id=module_id, module_version="unimplemented",
                    request_fingerprint=request.fingerprint(), status="partial", evidence=[],
                    unsupported_criterion_ids=[c.id for c in request.criteria], questions=[], error_code="module_unavailable")
            else:
                try:
                    result = CategoryResult.model_validate(module.run(request.model_copy(deep=True), cancel).model_dump())
                    self._check_result(request, result, evidence_ids)
                except Exception:
                    # Do not leak arbitrary exception text (may contain personal data or tokens).
                    result = CategoryResult(module_id=module_id, module_version=module.version,
                        request_fingerprint=request.fingerprint(), status="failed", evidence=[],
                        unsupported_criterion_ids=[c.id for c in request.criteria], questions=[], error_code="invalid_or_failed_module")
            all_evidence.extend(result.evidence)
            evidence_ids.update(e.id for e in result.evidence)
            results.append(result.model_dump())
            emit({"stage": "module_finished", "module_id": module_id, "status": result.status})
        if cancel.is_set():
            return {**identity, "run_id": run_id, "status": "cancelled", "events": events,
                    "report": None, "modules": results, "questions": []}
        references = []
        for module_id, module in (self.reference_modules.items() if include_references else []):
            try:
                if hasattr(module, 'reference_requested') and not module.reference_requested(profile):
                    continue
                emit({"stage": "reference_started", "module_id": module_id})
                contract = SafetyReferenceResult if module_id == 'safety' else ReferenceResult
                reference = contract.model_validate(module.run_reference(
                    profile.model_copy(deep=True), [c.model_copy(deep=True) for c in candidates], cancel).model_dump())
                if (reference.module_id != module_id or reference.profile_fingerprint != identity["profile_fingerprint"]
                        or reference.candidates_fingerprint != identity["candidates_fingerprint"]):
                    raise ValueError("stale reference")
                if module_id == 'safety' and {o.candidate_id for o in reference.observations} != {c.id for c in candidates}:
                    raise ValueError('foreign reference candidates')
                references.append(reference.model_dump())
                emit({"stage": "reference_finished", "module_id": module_id, "status": reference.status})
            except Exception:
                emit({"stage": "reference_failed", "module_id": module_id})
        if cancel.is_set():
            return {**identity, "run_id": run_id, "status": "cancelled", "events": events,
                    "report": None, "modules": results, "references": references, "questions": []}
        report = evaluate(profile, candidates, all_evidence)
        questions = [q for r in results for q in r["questions"]]
        if any(q["blocking"] for q in questions):
            report["ranking"] = []
            report["ranking_status"] = "withheld"
        partial = any(r["status"] != "completed" for r in results) or any(
            d["status"] == "unknown" for a in report["assessments"] for d in a["details"])
        emit({"stage": "evaluated"})
        status = "awaiting_input" if any(q["blocking"] for q in questions) else "partial" if partial else "completed"
        return {**identity, "run_id": run_id, "status": status,
                "events": events, "report": report, "modules": results, "references": references, "questions": questions}

    @staticmethod
    def _check_result(request, result, previous_ids):
        if result.module_id != request.module_id or result.request_fingerprint != request.fingerprint():
            raise ValueError("stale or foreign module response")
        criterion_ids = {c.id for c in request.criteria}
        criteria = {c.id: c for c in request.criteria}
        candidate_ids = {c.id for c in request.candidates}
        if set(result.unsupported_criterion_ids) - criterion_ids:
            raise ValueError("unknown unsupported criterion")
        if any(set(q.criterion_ids) - criterion_ids for q in result.questions):
            raise ValueError("foreign follow-up question")
        seen, ids = set(), set()
        for e in result.evidence:
            key = (e.candidate_id, e.criterion_id)
            if e.candidate_id not in candidate_ids or e.criterion_id not in criterion_ids:
                raise ValueError("foreign evidence")
            if key in seen or e.id in ids or e.id in previous_ids:
                raise ValueError("duplicate evidence")
            if e.criterion_id in result.unsupported_criterion_ids:
                raise ValueError("unsupported criterion has evidence")
            if e.source_kind == 'user' and not (request.module_id == 'leisure'
                    and criteria[e.criterion_id].metric == 'meeting_straight_line_distance_m'
                    and criteria[e.criterion_id].source == 'user' and e.source_url is None):
                raise ValueError('invalid user supplied provenance')
            rule = criteria[e.criterion_id].utility
            if e.status == "verified" and rule and rule.direction == "boolean" and e.value not in (0, 1):
                raise ValueError("invalid boolean metric")
            seen.add(key)
            ids.add(e.id)
        if result.status == "failed" and result.evidence:
            raise ValueError("failed module cannot supply scored evidence")
