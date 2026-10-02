"""Check what each request is used for; limited proxies never cover broader needs."""
import re
from hashlib import sha256
from typing import Annotated, Literal
from pydantic import Field
from .contracts import Contract, Identifier, NeedProfile, NeedField
from .codex_runner import RunnerError
from .source_bindings import bind_fields

Aspect = Literal['straight_distance','facility_count','facility_fit','walking_route',
                 'travel_time','transfer','school_assignment','environment','housing','other']


class IntakeNeed(Contract):
    source_id: Identifier
    group_id: Identifier | None
    aspect: Aspect
    handling: Literal['compare','research','reference','background','excluded','clarify']
    criterion_ids: Annotated[list[Identifier], Field(max_length=10)]
    context_keys: Annotated[list[Identifier], Field(max_length=10)]
    resolution_source_id: Identifier | None
    field: NeedField = 'need'


METRIC_ASPECTS = {
    **{m:'straight_distance' for m in ('grocery_straight_line_distance_m',
        'house_to_grocery_straight_line_distance_m','convenience_straight_line_distance_m',
        'bus_stop_straight_line_distance_m','school_straight_line_distance_m',
        'park_straight_line_distance_m','library_straight_line_distance_m','meeting_straight_line_distance_m')},
    'academy_count_within_radius':'facility_count',
}
GROUPS={'living':'생활·건강','transport':'교통·동선','education':'교육·육아',
        'safety':'안전·환경','leisure':'여가·관계','housing':'집·비용'}
DEFAULT_GROUP={'facility_fit':'living','walking_route':'transport','travel_time':'transport',
               'transfer':'transport','school_assignment':'education','environment':'safety','housing':'housing'}
LABELS={'facility_fit':'시설의 실제 이용 조건','walking_route':'실제 보행 경로',
        'travel_time':'목적지까지 이동시간','transfer':'환승 조건','school_assignment':'학교 배정',
        'environment':'주변 환경','housing':'실제 주거 조건','other':'원문 요구 확인',
        'straight_distance':'직선거리 조건','facility_count':'시설 선택지 조건'}
PREFERENCE=re.compile(r'원해|원하|싶|필요|중요|좋겠|필수|반드시|이내|이하|넘지|해야|되어야|돼야')
MANDATORY=re.compile(r'필수(?:조건|야|다|입니다|[.!?\s]*(?:$|[,，;]))|반드시|무조건|꼭\s*필요|(?:가능|있|없|충족|넘지\s*않)[^.!?]{0,12}해야')
EXCLUSION=re.compile(r'제외|필요\s*없|원하지\s*않|상관\s*없|(?:중요도|비중)\s*0(?:\D|$)')
# These are bounded checks for the review's concrete failure cases, not a general language classifier.
CRITICAL_FACETS={
    'facility_fit':re.compile(r'큰\s*마트|대형\s*마트|대량|품목|알레르기|신선|소수\s*정예|소그룹|반\s*크기|휠체어|기구|자유\s*이용|레슨'),
    'walking_route':re.compile(r'도보\s*(?:시간|경로|거리|\d)|걸어서\s*\d'),
    'travel_time':re.compile(r'(?:통근|출퇴근|직장까지|목적지까지)[^.!?\n]{0,40}(?:\d+\s*분|시간)'),
    'transfer':re.compile(r'환승'),
    'school_assignment':re.compile(r'학교\s*배정|배정\s*학교|학구'),
    'environment':re.compile(r'횡단|통학로\s*안전|야간\s*(?:보행|안전)|침수|소음'),
}


def required_sources(sources):
    """Ignore only exact app-authored navigation/priority scaffolding."""
    scaffold=(
        '진주 주거 생활권을 내 조건으로 검토해 줘.',
        '집 한 곳의 주변 생활 조건을 분석하고 싶어.',
        '여러 집의 주변 생활 조건을 비교하고 싶어.',
        '진주 안에서 생활권부터 탐색하고 싶어.',
        '아래 카테고리만 선택했어. 중요도는 내가 배치해서 정한 값이며 임의 변경하지 마.',
        '집·비용은 실거래 참고만 필요하고 가격 점수/실제 매물 추천은 제외해 줘.',
    )
    def is_scaffold(text):
        return text in scaffold or text in (
            '아래 카테고리만 선택했어.', '중요도는 내가 배치해서 정한 값이며 임의 변경하지 마.') or bool(re.fullmatch(
            r'(생활·건강|교통·동선|교육·육아|안전·환경|여가·관계|집·비용): (중요도 [\d.]+, 상대 비중 [\d.]+%|점수 비중 0, 실거래 참고)\.',text))
    return [key for key,text in sources.items() if not is_scaffold(text)]


def review_needs(profile, sources, needs=None, required_ids=(), previous=None, answers=()):
    """Restore collapsed comparisons as unknown; reject fabricated coverage references."""
    doc=profile.model_dump()
    criteria={c['id']:c for c in doc['criteria']}
    groups={g['id']:g for g in doc['groups']}
    contexts={c['key'] for c in doc['context']}
    compact=needs is not None
    needs=list(needs or [])
    by_source={key:[] for key in sources}
    for n in needs:
        if (n.source_id not in sources or n.resolution_source_id and n.resolution_source_id not in sources
                or set(n.criterion_ids)-criteria.keys() or set(n.context_keys)-contexts
                or n.group_id is not None and n.group_id not in groups):
            raise RunnerError('invalid_need_coverage_reference')

    needs,uncertain,field_issues=bind_fields(doc,sources,needs,previous,answers)
    # bind_fields attaches provenance to this same document; keep its fields through restoration.
    criteria={c['id']:c for c in doc['criteria']}
    for n in needs:
        if n.handling=='excluded':
            resolution=sources[n.resolution_source_id or n.source_id]
            prior_excluded=previous and n.criterion_ids and all(
                any(c.id==id and c.importance==0 and c.hard is None for c in previous.criteria) for id in n.criterion_ids)
            targeted=False
            if previous and n.resolution_source_id and n.resolution_source_id!=n.source_id:
                for answer in answers:
                    if answer.answer==resolution:
                        q=next(q for q in previous.questions if q.id==answer.question_id)
                        targeted=bool(n.criterion_ids) and set(n.criterion_ids)<=set(q.criterion_ids)
            if (not prior_excluded and (not EXCLUSION.search(resolution) or n.resolution_source_id and
                    n.resolution_source_id!=n.source_id and not targeted)
                    or any(criteria[id]['importance']>0 or criteria[id]['hard'] for id in n.criterion_ids)):
                raise RunnerError('unconfirmed_need_exclusion')
        elif n.handling in ('reference','research','background') and not n.context_keys:
            raise RunnerError('unrepresented_context_need')
        if n.handling=='research' and not any(c['key'] in n.context_keys and c['value']=='requested' and
            c['key'] in ('qualitative_research_requested','education_research','safety_research','leisure_research',
                         'transport_research','housing_research','extension_research')
            for c in doc['context']):raise RunnerError('unrepresented_research_need')
        by_source[n.source_id].append(n)

    repairs=[]
    def represented(source,aspect):
        for n in by_source[source]:
            if n.aspect!=aspect or n.handling not in ('compare','clarify'):continue
            for id in n.criterion_ids:
                c=criteria[id]
                if not (c['importance']>0 and groups[c['group_id']]['weight']>0 or c['hard']):continue
                if n.field in ('utility','importance','hard','parameters'):
                    return True
                # Older recorded drafts lack the field tag; a local weight qualifier is not a new need.
                if 'field' not in n.model_fields_set and re.search(r'비중|중요도|\d\s*%',sources[source]):
                    return True
                if c['metric'] not in METRIC_ASPECTS or METRIC_ASPECTS[c['metric']]==aspect:
                    # An unknown preference cannot stand in for a mandatory requirement.
                    if c['metric'] not in METRIC_ASPECTS and MANDATORY.search(sources[source]) and not c['hard']:continue
                    return True
        return False

    def restore(source,aspect,group_id=None):
        text=sources[source]
        if represented(source,aspect):return
        # Preserve the exact original scope, including any coupled numerical restrictions.
        id='need_'+sha256((text+'|'+aspect).encode()).hexdigest()[:12]
        if id in criteria:return
        attached=[criteria[id] for n in by_source[source] for id in n.criterion_ids]
        group_id=group_id or (attached[0]['group_id'] if attached else DEFAULT_GROUP.get(aspect,'extension'))
        if group_id not in groups:
            group={'id':group_id,'label':GROUPS.get(group_id,'추가 요구'),'weight':100.0,'source':'proposed',
                   'reason':'원문 요구를 보존했어. 반영 비중은 확인이 필요해.'}
            doc['groups'].append(group);groups[group_id]=group
        mandatory=bool(MANDATORY.search(text))
        c=dict(id=id,group_id=group_id,module_id=group_id if group_id in GROUPS else 'extension',
            label=LABELS[aspect],need=text,source_quote=text,source='user',
            importance=max((c['importance'] for c in attached),default=100.0) or 100.0,importance_source='proposed',
            metric='need_'+aspect+'_unverified',parameters={},
            utility={'direction':'boolean','ideal':1.0,'limit':0.0,'unit':'bool'} if mandatory else None,
            hard={'operator':'eq','value':1.0} if mandatory else None)
        # Boolean hard means this exact stated requirement must hold. It is not a guessed travel/quality score.
        doc['criteria'].append(c);criteria[id]=c;repairs.append({'source_id':source,'aspect':aspect,'criterion_id':id})

    for n in needs:
        if n.handling in ('compare','clarify') and not represented(n.source_id,n.aspect):
            restore(n.source_id,n.aspect,n.group_id)
    for source in required_ids:
        text=sources[source]
        if not PREFERENCE.search(text):continue
        for aspect,pattern in CRITICAL_FACETS.items():
            if not pattern.search(text):continue
            entries=[n for n in by_source[source] if n.aspect==aspect]
            if entries and all(n.handling=='excluded' for n in entries):continue
            if EXCLUSION.search(text) and not any(n.handling in ('compare','clarify') for n in entries):continue
            # "Must cite a review" is a research instruction, not a housing eligibility constraint.
            if entries and any(n.handling in ('research','reference') for n in entries):continue
            # Legacy/offline profiles also receive the concrete scope checks.
            if not compact and any(c['metric'] not in METRIC_ASPECTS and c['source_quote']==text
                    and (c['importance']>0 or c['hard']) for c in criteria.values()):continue
            restore(source,aspect,entries[0].group_id if entries else None)

    missing=[source for source in required_ids if not by_source[source]] if compact else []
    unclear=[n.source_id for n in needs if n.handling=='clarify' and not any(
        set(q['criterion_ids']) & set(n.criterion_ids) for q in doc['questions'])]
    pending=list(dict.fromkeys(missing+unclear+list(uncertain)))
    if pending:
        # Keep omitted text and ask once; never treat an unexplained omission as a completed analysis.
        for source in list(dict.fromkeys(missing+list(uncertain))):
            if not any(c['key']=='unresolved_request' and c['source_quote']==sources[source] for c in doc['context']):
                doc['context'].append(dict(key='unresolved_request',value=sources[source],source_quote=sources[source]))
        question={'id':'need_coverage_review','text':'이 요청에서 가장 중요한 점이나 원하는 이용 방식을 알려주세요. '+
                  ' / '.join(sources[s] for s in pending)[:1200],
                  'reason':'조건의 연결이나 기준을 확인해야 해요. 입력한 원문은 그대로 남아 있어요.',
                  'criterion_ids':list(dict.fromkeys([r['criterion_id'] for r in repairs if r['source_id'] in pending]+
                      [id for n in needs if n.source_id in pending for id in n.criterion_ids]+
                      [id for ids in uncertain.values() for id in sorted(ids)]+
                      [c['id'] for c in criteria.values() if any(c['source_quote']==sources[s] for s in pending)])),
                  'blocking':True}
        # A second incomplete interview response must not duplicate the stable review question ID.
        doc['questions']=[q for q in doc['questions'] if q['id']!=question['id']]
        if len(doc['questions'])>=10:raise RunnerError('unaccounted_request_needs')
        doc['questions'].insert(0,question)
    if len(doc['criteria'])>50 or len(doc['groups'])>20:raise RunnerError('too_many_unresolved_needs')
    return NeedProfile.model_validate(doc),{'coverage_mode':'source_mapping' if compact else 'legacy_scope_checks',
        'source_count':len(required_ids),'mapped_source_count':len(required_ids)-len(missing) if compact else None,
        'restored_count':len(repairs),'unresolved_source_count':len(pending),
        'field_binding_issues':field_issues,'unresolved_binding_count':len(uncertain)}
