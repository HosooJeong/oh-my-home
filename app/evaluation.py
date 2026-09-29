"""Deterministic personal utility; missing facts never become an actual zero."""
from .contracts import Candidate, Evidence, NeedProfile, UtilityRule


def utility(value: float, rule: UtilityRule) -> float:
    if rule.direction == "boolean":
        if value not in (0, 1):
            raise ValueError("boolean metric must be 0 or 1")
        return float(value == rule.ideal)
    if rule.direction == "target":
        score = 1 - abs(value - rule.ideal) / rule.limit
    else:
        score = (value - rule.limit) / (rule.ideal - rule.limit)
    return max(0.0, min(1.0, score))


def weights(profile: NeedProfile) -> dict[str, float]:
    group_total = sum(g.weight for g in profile.groups)
    result = {}
    for group in profile.groups:
        criteria = [c for c in profile.criteria if c.group_id == group.id]
        total = sum(c.importance for c in criteria)
        for c in criteria:
            result[c.id] = group.weight / group_total * c.importance / total if total else 0.0
    return result


def evaluate(profile: NeedProfile, candidates: list[Candidate], evidence: list[Evidence]) -> dict:
    criteria = {c.id: c for c in profile.criteria}
    candidate_ids = {c.id for c in candidates}
    if not candidates or len(candidate_ids) != len(candidates):
        raise ValueError("nonempty, unique candidates required")
    indexed = {}
    ids = set()
    for e in evidence:
        key = (e.candidate_id, e.criterion_id)
        if e.candidate_id not in candidate_ids or e.criterion_id not in criteria:
            raise ValueError("unknown evidence target")
        if key in indexed or e.id in ids:
            raise ValueError("duplicate evidence; resolve conflicts before evaluation")
        indexed[key] = e
        ids.add(e.id)
    normalized = weights(profile)
    provisional = any(g.source == "proposed" and g.weight > 0 for g in profile.groups) or any(
        normalized[c.id] > 0 and (c.source == "proposed" or c.importance_source == "proposed") for c in profile.criteria
    )
    assessments = []
    for candidate in candidates:
        coverage = contribution = 0.0
        hard_failed, hard_unknown, details = [], [], []
        for criterion in profile.criteria:
            e = indexed.get((candidate.id, criterion.id))
            known = (e is not None and e.status == "verified" and criterion.utility is not None
                     and e.unit == criterion.utility.unit)
            fit = utility(e.value, criterion.utility) if known else None
            w = normalized[criterion.id]
            hard_status = "not_required"
            if criterion.hard:
                if not known:
                    hard_status = "unknown"
                    hard_unknown.append(criterion.id)
                else:
                    rule = criterion.hard
                    passed = {"lte": e.value <= rule.value, "gte": e.value >= rule.value,
                              "eq": e.value == rule.value}[rule.operator]
                    hard_status = "pass" if passed else "fail"
                    if not passed:
                        hard_failed.append(criterion.id)
            if known:
                coverage += w
                contribution += 100 * w * fit
            details.append({"criterion_id": criterion.id, "weight": w, "utility": fit,
                            "contribution": 100 * w * fit if known else None,
                            "evidence_id": e.id if e else None, "hard_status": hard_status,
                            "status": "not_requested" if w == 0 and not criterion.hard else "known" if known else "unknown"})
        coverage = min(1.0, max(0.0, coverage))
        complete = abs(coverage - 1) < 1e-9
        assessments.append({
            "candidate_id": candidate.id, "coverage": round(coverage, 8),
            "score": round(contribution, 6) if complete else None,
            "score_range": [round(contribution, 6), round(contribution + 100 * (1-coverage), 6)],
            "eligibility": "ineligible" if hard_failed else "unverified" if hard_unknown else "eligible",
            "hard_failed": hard_failed, "hard_unknown": hard_unknown, "details": details,
        })
    # No total ranking when unknown preferences could reverse the result.
    rankable = not provisional and not any(q.blocking for q in profile.questions) and all(
        a["score"] is not None and a["eligibility"] != "unverified" for a in assessments)
    ranking = sorted((a for a in assessments if a["eligibility"] == "eligible"),
                     key=lambda a: (-a["score"], a["candidate_id"])) if rankable else []
    return {"profile_fingerprint": profile.fingerprint(), "provisional": provisional,
            "assessments": assessments, "ranking": [a["candidate_id"] for a in ranking],
            "ranking_status": "available" if rankable else "withheld"}
