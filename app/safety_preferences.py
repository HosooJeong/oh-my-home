"""Explicit safety needs and priorities; no fabricated thresholds or risk proxies."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .contracts import Contract, NeedProfile, Weight
from .modules.safety import TOPICS, METRICS

Topic = Literal['night', 'traffic', 'flood', 'noise', 'air']


class SafetyInput(Contract):
    profile: NeedProfile | None = None
    topics: Annotated[list[Topic], Field(max_length=5)]
    group_weight: Weight
    criterion_importance: Weight
    radius_m: Annotated[float, Field(gt=0, le=5000, allow_inf_nan=False)]
    qualitative_research: bool

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.topics)) != len(self.topics): raise ValueError('duplicate topic')
        if self.qualitative_research and not self.topics: raise ValueError('research needs a topic')
        return self


def safety_profile(data):
    doc = data.profile.model_dump() if data.profile else dict(schema_version='1', revision=0,
        request='', context=[], groups=[], criteria=[], questions=[])
    doc['revision'] += 1
    quote = ('안전·환경 조건 확인: ' + (' / '.join(TOPICS[k] for k in data.topics) or '문제별 평가 제외')
        + f'. 분야 중요도 {data.group_weight:g}, 선택 조건별 중요도 {data.criterion_importance:g}. '
        + f'CCTV 등록 참고 직선반경 {data.radius_m:g}m. '
        + ('최신 공식 웹자료로 선택한 문제를 보완 조사해 줘.' if data.qualitative_research else '추가 웹 조사 요청 없음.'))
    doc['request'] = (doc['request'] + '\n' + quote).strip()
    context = dict(safety_reference='requested', safety_radius_m=str(data.radius_m),
        safety_topics=','.join(data.topics), safety_research='requested' if data.qualitative_research else 'disabled')
    doc['context'] = [c for c in doc['context'] if c['key'] not in context]
    doc['context'].extend(dict(key=k, value=v, source_quote=quote) for k,v in context.items() if v)
    # Keep arbitrary or model-created unsupported conditions; only manage the five explicit form metrics.
    for key, metric in METRICS.items():
        old = [c for c in doc['criteria'] if c['module_id'] == 'safety' and c['metric'] == metric]
        if len(old) > 1 or (old and (old[0]['group_id'] != 'safety' or old[0]['hard'] is not None)):
            raise ValueError('custom safety scope; edit separately')
        c = old[0] if old else None
        if key in data.topics:
            if c is None:
                identity = 'safety_' + key
                while any(c['id'] == identity for c in doc['criteria']): identity += '_x'
                c = dict(id=identity, module_id='safety', group_id='safety'); doc['criteria'].append(c)
            c.update(label=TOPICS[key], metric=metric, need=TOPICS[key] + '의 지역 근거를 확인해야 해.',
                source_quote=quote, source='user', importance=data.criterion_importance, importance_source='user',
                parameters={}, utility=None, hard=None)
        elif c:
            c.update(importance=0.0, importance_source='user', source='user', source_quote=quote, hard=None)
    members = [c for c in doc['criteria'] if c['group_id'] == 'safety']
    if members:
        group = next((g for g in doc['groups'] if g['id'] == 'safety'), None)
        if group is None:
            group = dict(id='safety', label='안전·환경'); doc['groups'].append(group)
        group.update(weight=data.group_weight if any(c['importance'] > 0 for c in members) else 0.0,
                     source='user', reason='사용자가 안전·환경 조건과 중요도를 확인했어.')
    return NeedProfile.model_validate(doc)
