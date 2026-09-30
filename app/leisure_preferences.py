"""User confirmed M6 filters and weights, preserving other and unsupported conditions."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .contracts import Contract, NeedProfile, Weight
from .modules.leisure import PARK_METRIC, LIBRARY_METRIC, MEETING_METRIC, HOBBY_METRIC, ACTIVITIES

Distance = Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]


class LeisureInput(Contract):
    profile: NeedProfile | None = None
    include_park: bool
    park_type: Literal['any','children','neighborhood']
    include_library: bool
    library_type: Literal['any','public','small']
    ideal: Distance
    limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)]
    park_importance: Weight
    library_importance: Weight
    include_meeting: bool
    meeting_label: Annotated[str, Field(max_length=100)]
    meeting_latitude: Annotated[float, Field(ge=-90,le=90,allow_inf_nan=False)] | None
    meeting_longitude: Annotated[float, Field(ge=-180,le=180,allow_inf_nan=False)] | None
    meeting_importance: Weight
    include_hobby: bool
    activity: Literal['gym','pilates','table_tennis','swimming','tennis','yoga','other']
    activity_name: Annotated[str, Field(max_length=100)] = ''
    activity_form: Annotated[str, Field(max_length=100)]
    hobby_importance: Weight
    group_weight: Weight

    @model_validator(mode='after')
    def consistent(self):
        if self.ideal>=self.limit: raise ValueError('invalid leisure thresholds')
        if self.include_meeting and (not self.meeting_label.strip() or self.meeting_latitude is None or self.meeting_longitude is None):
            raise ValueError('explicit meeting point required')
        if self.include_hobby and self.activity=='other' and not self.activity_name.strip(): raise ValueError('custom activity name required')
        return self


def leisure_profile(data):
    doc = data.profile.model_dump() if data.profile else {'schema_version':'1','revision':0,'request':'','context':[], 'groups':[], 'criteria':[], 'questions':[]}
    doc['revision']+=1
    park={'any':'전체 도시공원','children':'어린이공원','neighborhood':'근린공원'}[data.park_type] if data.include_park else '평가 제외'
    library={'any':'공공·작은도서관','public':'공공도서관','small':'작은도서관'}[data.library_type] if data.include_library else '평가 제외'
    meeting=(f'{data.meeting_label} (위도 {data.meeting_latitude:g}, 경도 {data.meeting_longitude:g})' if data.include_meeting else '평가 제외')
    hobby=(data.activity_name if data.activity=='other' else ACTIVITIES[data.activity]) if data.include_hobby else '평가 제외'
    quote = (f'여가 조건 확인: 공원 {park}, 도서관 {library}, 만남 지점 {meeting}, '
        f'취미 {hobby} ({data.activity_form or "형태 미지정"}). '
        f'직선거리 목표 {data.ideal:g}m, 만족도 0 {data.limit:g}m. '
        f'공원/도서관/만남/취미 중요도 {data.park_importance:g}/{data.library_importance:g}/{data.meeting_importance:g}/{data.hobby_importance:g}, '
        f'여가 분야 중요도 {data.group_weight:g}. '
        +('사설 취미시설 후보와 이용 형태를 웹으로 보완해 줘.' if data.include_hobby else '취미시설 웹 조사 요청 없음.'))
    doc['request']=(doc['request']+'\n'+quote).strip()
    context={'leisure_research':'requested' if data.include_hobby and data.hobby_importance>0 else 'disabled'}
    doc['context']=[c for c in doc['context'] if c['key'] not in context]
    doc['context'].extend({'key':k,'value':v,'source_quote':quote} for k,v in context.items())
    distance={'direction':'lower','ideal':data.ideal,'limit':data.limit,'unit':'m'}
    specs=[(PARK_METRIC,data.include_park,'공원 접근성',data.park_importance,distance,{'park_type':data.park_type}),
           (LIBRARY_METRIC,data.include_library,'도서관 접근성',data.library_importance,distance,{'library_type':data.library_type}),
           (MEETING_METRIC,data.include_meeting,'지정 만남 지점 접근성',data.meeting_importance,distance,
            {'meeting_label':data.meeting_label,'meeting_latitude':str(data.meeting_latitude),'meeting_longitude':str(data.meeting_longitude)}),
           (HOBBY_METRIC,data.include_hobby,(data.activity_name if data.activity=='other' else ACTIVITIES[data.activity])+' 이용 적합성',data.hobby_importance,None,
            {'activity':data.activity,'activity_form':data.activity_form,'activity_name':data.activity_name if data.activity=='other' else ''})]
    for number,(metric,enabled,label,importance,utility,parameters) in enumerate(specs):
        old=[c for c in doc['criteria'] if c['module_id']=='leisure' and c['metric']==metric]
        if len(old)>1 or old and (old[0]['group_id']!='leisure' or old[0]['hard'] is not None):
            raise ValueError('multiple, custom, or mandatory leisure scopes; edit separately')
        criterion=old[0] if old else None
        if enabled:
            if not criterion:
                identity='leisure_'+str(number)
                while any(c['id']==identity for c in doc['criteria']): identity+='_x'
                criterion={'id':identity,'module_id':'leisure','group_id':'leisure'}; doc['criteria'].append(criterion)
            criterion.update(metric=metric,label=label,need=quote,source_quote=quote,source='user',importance=importance,
                importance_source='user',utility=utility,parameters=parameters,hard=None)
        elif criterion: criterion.update(importance=0.0,importance_source='user',source='user',source_quote=quote,hard=None)
        if criterion:
            doc['questions']=[q for q in doc['questions'] if q['criterion_ids'] != [criterion['id']]]
    members=[c for c in doc['criteria'] if c['group_id']=='leisure']
    if members:
        group=next((g for g in doc['groups'] if g['id']=='leisure'),None)
        if group is None: group={'id':'leisure','label':'여가·관계'}; doc['groups'].append(group)
        group.update(weight=data.group_weight if any(c['importance']>0 for c in members) else 0.0,source='user',reason='사용자가 여가 조건과 중요도를 직접 확인했어.')
    return NeedProfile.model_validate(doc)
