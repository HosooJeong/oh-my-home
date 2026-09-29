"""Explicit user edits; no model call and no mutation of the previous revision."""
from .contracts import Evidence, NeedProfile, digest
from .evaluation import evaluate


def update_preferences(profile: NeedProfile, group_weights: dict[str, float] | None = None,
                       criterion_importance: dict[str, float] | None = None,
                       confirm_weights: bool = False) -> NeedProfile:
    if group_weights is not None and not isinstance(group_weights, dict):
        raise ValueError("group_weights must be an object")
    if criterion_importance is not None and not isinstance(criterion_importance, dict):
        raise ValueError("criterion_importance must be an object")
    if type(confirm_weights) is not bool:
        raise ValueError("confirm_weights must be a boolean")
    group_weights, criterion_importance = group_weights or {}, criterion_importance or {}
    if set(group_weights) - {g.id for g in profile.groups}:
        raise ValueError("unknown preference group")
    if set(criterion_importance) - {c.id for c in profile.criteria}:
        raise ValueError("unknown criterion")
    data = profile.model_dump()
    data["revision"] += 1
    for group in data["groups"]:
        if group["id"] in group_weights:
            group["weight"] = group_weights[group["id"]]
            group["reason"] = "사용자가 중요도를 수정했어."
            group["source"] = "user"
        elif confirm_weights:
            group["source"] = "user"
    for criterion in data["criteria"]:
        if criterion["id"] in criterion_importance:
            criterion["importance"] = criterion_importance[criterion["id"]]
            criterion["importance_source"] = "user"
        elif confirm_weights:
            criterion["importance_source"] = "user"
    return NeedProfile.model_validate(data)


def reevaluate_preferences(previous: NeedProfile, revised: NeedProfile, candidates, previous_run: dict):
    """Reuse facts only when the criteria/units/thresholds themselves are unchanged."""
    def query_basis(profile):
        data = profile.model_dump()
        return {"request": data["request"], "context": data["context"], "criteria": [
            {k: v for k, v in c.items() if k not in ("importance", "importance_source")}
            for c in data["criteria"]]}
    if query_basis(previous) != query_basis(revised):
        raise ValueError("changed query conditions require module revalidation")
    if previous_run.get("profile_fingerprint") != previous.fingerprint():
        raise ValueError("cached result belongs to another profile")
    if previous_run.get("candidates_fingerprint") != digest([c.model_dump() for c in candidates]):
        raise ValueError("candidate positions changed; query again")
    if previous_run.get("status") not in ("completed", "partial"):
        raise ValueError("only evaluated runs can be reused")
    evidence = [Evidence.model_validate(e) for module in previous_run["modules"] for e in module["evidence"]]
    return evaluate(revised, candidates, evidence)
