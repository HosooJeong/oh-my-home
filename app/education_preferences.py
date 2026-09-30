"""Explicit education conditions preserving other and unsupported needs."""
from typing import Annotated, Literal
from pydantic import Field
from .contracts import Contract, NeedProfile, Weight
from .modules.education import SCHOOL_METRIC, ACADEMY_METRIC, LEVELS, SUBJECTS

Distance = Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]


class EducationInput(Contract):
    profile: NeedProfile | None = None
    school_level: Literal['elementary', 'middle', 'high']
    include_school: bool
    school_ideal: Distance
    school_limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)]
    school_importance: Weight
    include_academy: bool
    subject: Literal['math', 'english', 'korean', 'science', 'art', 'music']
    radius_m: Annotated[float, Field(gt=0, le=20000, allow_inf_nan=False)]
    sufficient_count: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
    academy_importance: Weight
    group_weight: Weight
    travel_mode: Literal['unknown', 'alone', 'accompanied', 'car', 'shuttle']
    qualitative_research: bool


def education_profile(data):
    if data.include_school and data.school_ideal >= data.school_limit:
        raise ValueError('invalid school thresholds')
    doc = data.profile.model_dump() if data.profile else {
        'schema_version': '1', 'revision': 0, 'request': '', 'context': [], 'groups': [], 'criteria': [], 'questions': []}
    doc['revision'] += 1
    travel = {'unknown':'미정','alone':'혼자 도보','accompanied':'보호자 동행','car':'보호자 차량','shuttle':'셔틀'}
    quote = (f'교육 조건 확인: {LEVELS[data.school_level]}, 통학 방식 {travel[data.travel_mode]}. '
        + (f'학교 직선거리 목표 {data.school_ideal:g}m, 만족도 0 {data.school_limit:g}m, 중요도 {data.school_importance:g}. '
           if data.include_school else '학교 거리 평가 제외. ')
        + (f'{SUBJECTS[data.subject]} 학원 직선반경 {data.radius_m:g}m, 선택지 {data.sufficient_count:g}개소면 충분하고 0개소는 만족도 0, 중요도 {data.academy_importance:g}. '
           if data.include_academy else '학원 개소 평가 제외. ')
        + f'교육 분야 중요도 {data.group_weight:g}. '
        + ('학원의 수업 형태·규모·일부 경험을 최신 웹자료로 보완해 줘.' if data.qualitative_research else '추가 웹 조사 요청 없음.'))
    doc['request'] = (doc['request'] + '\n' + quote).strip()
    context = {'education_level': data.school_level, 'education_subject': data.subject,
               'school_travel_mode': data.travel_mode, 'education_research': 'requested' if data.qualitative_research else 'disabled'}
    doc['context'] = [c for c in doc['context'] if c['key'] not in context]
    doc['context'].extend({'key': key, 'value': value, 'source_quote': quote} for key,value in context.items())
    for metric, enabled, label, importance, utility, parameters in [
        (SCHOOL_METRIC, data.include_school, LEVELS[data.school_level] + ' 접근성', data.school_importance,
         {'direction': 'lower', 'ideal': data.school_ideal, 'limit': data.school_limit, 'unit': 'm'}, {'school_level': data.school_level}),
        (ACADEMY_METRIC, data.include_academy, SUBJECTS[data.subject] + ' 학원 선택지', data.academy_importance,
         {'direction': 'higher', 'ideal': data.sufficient_count, 'limit': 0.0, 'unit': 'count'},
         {'school_level': data.school_level, 'subject': data.subject, 'radius_m': str(data.radius_m)})]:
        old = [c for c in doc['criteria'] if c['module_id'] == 'education' and c['metric'] == metric]
        if len(old) > 1: raise ValueError('multiple education scopes; edit separately')
        criterion = old[0] if old else None
        if criterion and criterion['group_id'] != 'education':
            raise ValueError('education belongs to a custom group; edit separately')
        if enabled:
            if not criterion:
                identity = 'edu_school' if metric == SCHOOL_METRIC else 'edu_academy'
                while any(c['id'] == identity for c in doc['criteria']): identity += '_x'
                criterion = {'id': identity, 'module_id': 'education', 'group_id': 'education'}
                doc['criteria'].append(criterion)
            criterion.update(metric=metric, label=label, need=quote, source_quote=quote, source='user',
                importance=importance, importance_source='user', utility=utility, parameters=parameters, hard=None)
        elif criterion:
            criterion.update(importance=0.0, importance_source='user', source='user', source_quote=quote, hard=None)
        if criterion:
            doc['questions'] = [q for q in doc['questions'] if q['criterion_ids'] != [criterion['id']]]
    members = [c for c in doc['criteria'] if c['group_id'] == 'education']
    if members:
        group = next((g for g in doc['groups'] if g['id'] == 'education'), None)
        if group is None:
            group = {'id': 'education', 'label': '교육·육아'}; doc['groups'].append(group)
        group.update(weight=data.group_weight if any(c['importance'] > 0 for c in members) else 0.0,
                     source='user', reason='사용자가 교육 조건과 중요도를 직접 확인했어.')
    return NeedProfile.model_validate(doc)
