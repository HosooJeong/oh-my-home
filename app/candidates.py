"""Common deterministic search space, evaluated by the registered category modules."""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .boundaries import Boundary
from .contracts import Candidate, Contract, NeedProfile, digest
from .evaluation import weights
from .geo import distance_m
from .modules.living import METRICS
from .modules.transport import METRIC
from .modules.education import SCHOOL_METRIC, ACADEMY_METRIC
from .modules.leisure import PARK_METRIC, LIBRARY_METRIC, MEETING_METRIC


def execution_plan(profile):
    normalized = weights(profile)
    queryable = {'living':set(METRICS), 'transport':{METRIC},
                 'education':{SCHOOL_METRIC, ACADEMY_METRIC},
                 'leisure':{PARK_METRIC, LIBRARY_METRIC, MEETING_METRIC}}
    return [dict(criterion_id=c.id, label=c.label, module_id=c.module_id, weight=normalized[c.id],
                 role='query' if c.metric in queryable.get(c.module_id, set()) and c.utility else 'unverified',
                 hard=c.hard is not None)
            for c in profile.criteria if normalized[c.id] > 0 or c.hard]


class GenerationInput(Contract):
    profile: NeedProfile
    count: Annotated[int, Field(ge=2, le=6)] = 3
    separation_m: Annotated[float, Field(ge=0, le=5000, allow_inf_nan=False)] = 1000.0
    area_codes: Annotated[list[str], Field(max_length=30)] = []
    mode: Literal['strict', 'exploratory'] = 'strict'


def selection_reason(profile, assessment, evidence, tied):
    """Describe measured selection inputs, never infer the unmeasured needs."""
    criteria = {c.id:c for c in profile.criteria}
    basis, unknown = [], []
    for detail in assessment['details']:
        if detail['status'] == 'not_requested':
            continue
        criterion = criteria[detail['criterion_id']]
        if detail['status'] != 'known':
            unknown.append({'criterion_id':criterion.id, 'label':criterion.label,
                            'need':criterion.need, 'weight':detail['weight'],
                            'hard_status':detail['hard_status']})
            continue
        fact = evidence[detail['evidence_id']]
        basis.append({'criterion_id':criterion.id, 'label':criterion.label,
                      'metric':criterion.metric, 'value':fact['value'], 'unit':fact['unit'],
                      'weight':detail['weight'], 'contribution':detail['contribution'],
                      'hard_status':detail['hard_status'], 'evidence_id':fact['id'],
                      'source_url':fact['source_url'], 'data_date':fact['data_date']})
    basis.sort(key=lambda b:(-b['contribution'], -b['weight'], b['criterion_id']))
    def measured_label(b):
        value = f"{round(b['value']):,}m·직선거리" if b['unit']=='m' else f"{b['value']:g}개소·등록자료" if b['unit']=='count' else f"{b['value']:g} {b['unit']}"
        return f"{b['label']}({value})"
    labels = ' · '.join(measured_label(b) for b in basis[:2])
    text = f'{labels}의 확인된 기여를 기준으로 골랐어.'
    if assessment['score_range'][0] == 0:
        text = f'{labels}을 확인했지만 네 기준에 따른 기여는 0점이야.'
    if unknown:
        text += ' ' + ' · '.join(c['label'] for c in unknown[:2]) + (' 등은' if len(unknown)>2 else '은') + ' 미확인이야.'
    if tied:
        text += ' 같은 평가값의 지점은 ID 순서와 후보 간격으로 골랐어.'
    return {'text':text, 'basis':basis, 'unverified':unknown,
            'tie_breaker':'candidate_id_then_separation' if tied else None}


def has_selection_evidence(assessment):
    return any(d['status']=='known' and d['weight']>0 for d in assessment['details'])


class CandidatePool:
    def __init__(self, document, boundary):
        self.document, self.boundary = document, boundary
        if (document["version"] != "shop_grid_500m_v1" or document["cell_size_m"] != 500
                or document["grid_crs"] != "EPSG:5179" or not 1 <= len(document["points"]) <= 5000):
            raise ValueError("invalid analysis pool")
        self.points = {}
        for point in document["points"]:
            candidate = Candidate.model_validate(point["candidate"])
            code, cell = point["area_code"], point["cell"]
            if (candidate.id in self.points or candidate.origin != "generated"
                    or code == "38030" or code not in boundary.features
                    or len(cell) != 2 or any(type(v) is not int or v < 0 for v in cell)
                    or candidate.id != f"grid_{cell[0]}_{cell[1]}"
                    or type(point["registered_shop_count"]) is not int or point["registered_shop_count"] < 1
                    or not boundary.contains("38030", candidate.latitude, candidate.longitude)
                    or not boundary.contains(code, candidate.latitude, candidate.longitude)):
                raise ValueError("invalid or outside-boundary analysis point")
            self.points[candidate.id] = {**point, "candidate": candidate}

    @classmethod
    def load(cls, pool_path: Path, boundary_path: Path, inventory_path: Path):
        document = json.loads(pool_path.read_text(encoding="utf-8"))
        for path, key in [(boundary_path, "boundary_sha256"), (inventory_path, "inventory_sha256")]:
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != document[key]:
                    raise ValueError("analysis pool is stale; prepare it again")
        return cls(document, Boundary.load(boundary_path))

    def metadata(self):
        counts = {a["code"]: 0 for a in self.boundary.metadata()["areas"]}
        for point in self.points.values():
            counts[point["area_code"]] += 1
        return {**self.boundary.metadata(), "available": True, "point_count": len(self.points),
                "cell_size_m": 500, "version": self.document["version"],
                "inventory_generated_at": self.document["inventory_generated_at"],
                "areas": [{**a, "point_count": counts[a["code"]],
                           "view_bounds":list(self.boundary.bounds[a['code']])}
                          for a in self.boundary.metadata()["areas"]],
                "limitations": "상가가 등록된 500m 격자 중심점만 비교해. 조용한 주거지·자연환경을 고르게 대표하지 않으며 실제 주택·매물·거주 가능 여부는 미확인이야."}

    def generate(self, data, orchestrator):
        valid_codes = set(self.boundary.features) - {"38030"}
        if len(set(data.area_codes)) != len(data.area_codes) or set(data.area_codes) - valid_codes:
            raise ValueError("unknown or duplicate area")
        base = {"candidates": [], "metadata": self.metadata(), "requested_count": data.count,
                "separation_m": data.separation_m, "area_codes": data.area_codes,
                "profile_fingerprint": data.profile.fingerprint(),
                "selection_fingerprint": digest(data.model_dump())}
        if any(q.blocking for q in data.profile.questions):
            return {**base, "status": "needs_input", "reason": "먼저 비교에 필요한 인터뷰 답변을 반영해 줘."}
        w = weights(data.profile)
        active = [c for c in data.profile.criteria if w[c.id] > 0 or c.hard]
        plan = execution_plan(data.profile)
        base.update(execution_plan=plan, selection_mode=data.mode)
        unsupported = [p['label'] for p in plan if p['role'] == 'unverified']
        if unsupported and (data.mode == 'strict' or any(p['hard'] and p['role'] == 'unverified' for p in plan)):
            return {**base, "status": "unsupported", "reason": "자동 선별에 필요한 조건의 근거가 아직 없어: " + ", ".join(unsupported)}
        if any(g.weight > 0 and g.source == "proposed" for g in data.profile.groups) or any(
                w[c.id] > 0 and (c.source == "proposed" or c.importance_source == "proposed") for c in active):
            return {**base, "status": "needs_input", "reason": "제안된 조건과 중요도를 먼저 확인해 줘."}
        points = [p for p in self.points.values() if not data.area_codes or p["area_code"] in data.area_codes]
        base["searched_count"] = len(points)
        if not points:
            return {**base, "status": "empty", "reason": "선택한 범위에 준비된 분석 지점이 없어."}
        run = orchestrator.run(data.profile, [p["candidate"] for p in points], include_references=False)
        if not run["report"] or any(q["blocking"] for q in run["questions"]):
            return {**base, "status": "needs_input", "reason": "비교에 필요한 조건을 먼저 확인해 줘."}
        assessments = run["report"]["assessments"]
        eligible = [a for a in assessments if a["eligibility"] == "eligible" and has_selection_evidence(a)
                    and (a["score"] is not None or data.mode == 'exploratory')]
        no_evidence_count = sum(a['eligibility']=='eligible' and not has_selection_evidence(a) for a in assessments)
        base.update(eligible_count=len(eligible), no_selection_evidence_count=no_evidence_count,
            hard_failed_count=sum(a['eligibility']=='ineligible' for a in assessments),
            unverified_count=sum(a['eligibility']!='ineligible' and
                (a['score'] is None or a['eligibility']=='unverified') for a in assessments),
            source_run_id=run['run_id'], module_ids=[m['module_id'] for m in run['modules']],
            source_candidate_fingerprint=run['candidates_fingerprint'],
            module_requests=[{'module_id':m['module_id'], 'request_fingerprint':m['request_fingerprint'],
                              'evidence_count':len(m['evidence'])} for m in run['modules']])
        if data.mode=='exploratory' and not eligible and no_evidence_count:
            return {**base, 'status':'needs_scope', 'reason_code':'no_selection_evidence',
                    'reason':'지금 조건으로 지역을 고를 근거가 없어. 알아볼 지역을 정하고 조사할 지점을 직접 골라줘.',
                    'ranking_status':'withheld', 'selected':[], 'next_action':'choose_area_and_point',
                    'unverified_criteria':[p for p in plan if p['role']=='unverified']}
        # Keep original weights and sort the confirmed contribution; unknowns remain unknown.
        eligible.sort(key=lambda a: (-a['score_range'][0], -a['coverage'], a["candidate_id"]))
        evidence = {e['id']:e for m in run['modules'] for e in m['evidence']}
        tie_counts = {}
        for a in eligible:
            key = (a['score_range'][0], a['coverage'])
            tie_counts[key] = tie_counts.get(key,0)+1
        selected = []
        for assessment in eligible:
            point = self.points[assessment["candidate_id"]]
            c = point["candidate"]
            if all(distance_m(c.latitude, c.longitude, other["candidate"].latitude,
                              other["candidate"].longitude) >= data.separation_m for other in selected):
                selected.append({**point, "score": assessment["score"], 'score_range':assessment['score_range'],
                                 'coverage':assessment['coverage'],
                                 'selection_reason':selection_reason(data.profile,assessment,evidence,
                                     tie_counts[(assessment['score_range'][0],assessment['coverage'])]>1)})
            if len(selected) == data.count:
                break
        partial = any(p['score'] is None for p in selected)
        base.update(ranking_status='withheld' if partial else run['report']['ranking_status'],
                    unverified_criteria=[p for p in plan if p['role'] == 'unverified'])
        return {**base, "status": "completed" if len(selected) == data.count else "limited" if selected else "empty",
                "reason": "전체 근거가 확인되고 필수조건을 통과한 지점에서 적합도 순으로, 지정한 간격을 유지해 골랐어."
                    if selected and not partial else "확인된 기여가 큰 탐색 지점을 골랐어. 미확인 조건의 비중을 유지하며 전체 순위는 보류해."
                    if selected else "필수조건 탈락 또는 근거 미확인으로 선별할 지점이 없어. 조건과 자료 범위를 확인해 줘.",
                "candidates": [p["candidate"].model_dump() for p in selected],
                "selected": [{"candidate_id": p["candidate"].id, "score": p["score"],
                              "score_range": p['score_range'], "coverage":p['coverage'],
                              "selection_reason":p['selection_reason'],
                              "area_code": p["area_code"], "cell": p["cell"],
                              "registered_shop_count": p["registered_shop_count"]} for p in selected]}
