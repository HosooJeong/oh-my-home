"""Keep public research questions, selection limits and execution state separate from scores."""
import re
from .contracts import digest

FLAGS={'living':'qualitative_research_requested','education':'education_research','safety':'safety_research',
       'leisure':'leisure_research','transport':'transport_research','housing':'housing_research','extension':'extension_research','health':'health_research','dining':'dining_research'}
DISTANCES={'grocery_straight_line_distance_m':'grocery','house_to_grocery_straight_line_distance_m':'grocery',
           'convenience_straight_line_distance_m':'convenience',
           'pharmacy_straight_line_distance_m':'pharmacy','clinic_straight_line_distance_m':'clinic',
           'everyday_meal_straight_line_distance_m':'everyday_meal','restaurant_straight_line_distance_m':'restaurant'}
PRIVATE=re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]+|0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}|(?:로|길)\s*\d+(?:번길)?(?!\d|\s*(?:m|분|회|명|개|곳|원))|(?:위도|경도)\s*[:=]?\s*[-+]?\d')


def questions(profile,module):
    facts=[f for f in profile.context if f.key==module+'_research_question']
    if facts:return [(f.value,f.source_quote,None) for f in facts]
    if any(f.key==FLAGS[module] and f.value=='disabled' for f in profile.context):return []
    if not any(f.key==FLAGS[module] and f.value=='requested' for f in profile.context):
        # Subject/grade and clinical department are functional needs, not an opt-in to generic reviews.
        automatic=[c for c in profile.criteria if c.module_id==module and (c.importance>0 or c.hard)
                   and (module=='education' and c.metric=='academy_count_within_radius' or
                        module=='health' and c.metric!='pharmacy_straight_line_distance_m')]
        return [(public_fact_question(c,module),c.source_quote,[c.id]) for c in automatic] if module in ('education','health') else []
    # Legacy user editors already preserve concise functional needs. Never send the whole request or family context.
    criteria=[c for c in profile.criteria if c.module_id==module and (c.importance>0 or c.hard)]
    return [(c.need,c.source_quote,[c.id]) for c in criteria] or [('',next(f.source_quote for f in profile.context if f.key==FLAGS[module]),[])]


def public_fact_question(criterion,module):
    # Legacy profiles have no public question. Never forward family/diagnosis prose.
    if module=='education':
        from .modules.education import SUBJECTS,LEVELS
        scope=' '.join(filter(None,[LEVELS.get(criterion.parameters.get('school_level')),
                                   SUBJECTS.get(criterion.parameters.get('subject'))]))
        return scope+' 학원의 실제 과목·대상 학년을 확인해 주세요.'
    departments=['소아청소년과','소아과','내과','이비인후과','정형외과','피부과','안과','산부인과',
                 '치과','정신건강의학과','신경과','재활의학과','가정의학과']
    names=' · '.join(word for word in departments if word in criterion.need)
    return '의료기관의 실제 진료과'+(' ('+names+')' if names else '')+'를 확인해 주세요.'


def question_record(module,question,quote,criteria):
    record={'id':'research_'+digest([module,question,quote,[c.id for c in criteria]])[:16],'module':module,'question':question,
        'criterion_ids':[c.id for c in criteria],'status':'queued','reason':None,
        'facility_ids':[],'unsearched_facility_ids':[],'evidence_status':None}
    if not question:record.update(status='not_executed',reason='original_question_missing')
    elif PRIVATE.search(question):record.update(status='not_executed',reason='private_question_requires_public_summary')
    return record


def build_research_plan(profile,candidates,enriched,targets,leisure_scope,education_index=None,shop_index=None):
    from .geo import distance_m
    from .modules.safety import TOPICS
    records=[];facility_tasks={};target_questions=[]
    seen=set()
    for module in FLAGS:
        active=[c for c in profile.criteria if c.module_id==module and (c.importance>0 or c.hard)]
        for text,quote,legacy_ids in questions(profile,module):
            linked=[c for c in active if c.id in legacy_ids] if legacy_ids is not None else [c for c in active if c.source_quote==quote or quote in c.source_quote or c.source_quote in quote]
            explicit_id=next((f.value for f in reversed(profile.context) if f.key==module+'_research_criterion_id' and f.source_quote==quote),None)
            if explicit_id:linked=[c for c in active if c.id==explicit_id]
            record=question_record(module,text,quote,linked)
            if explicit_id and not linked:record.update(status='not_executed',reason='condition_scope_unconfirmed')
            if record['id'] in seen:continue
            seen.add(record['id']);records.append(record)
            if record['status']!='queued':continue
            if module in ('transport','housing','extension'):
                record.update(status='not_executed',reason='research_module_unsupported');continue
            if module=='safety':
                if not targets:record.update(status='not_executed',reason='no_verified_area_or_topic')
                else:target_questions.append({'request_id':record['id'],'question':text,'criterion_ids':record['criterion_ids']})
                continue
            if module=='leisure':
                if not leisure_scope:record.update(status='not_executed',reason='no_supported_activity');continue
                selected={r['criterion_id'] for r in leisure_scope.get('requests',[])}
                if record['criterion_ids'] and not selected.intersection(record['criterion_ids']):
                    record.update(status='not_executed',reason='activity_limit_or_unsupported');continue
                continue
            key=module+'_research_target'
            target=next((f.value for f in reversed(profile.context) if f.key==key and f.source_quote==quote),None)
            considered=linked or active
            explicit_id=next((f.value for f in reversed(profile.context) if f.key==module+'_research_criterion_id' and f.source_quote==quote),None)
            if explicit_id:
                considered=[c for c in active if c.id==explicit_id]
                if not considered:
                    record.update(status='not_executed',reason='condition_scope_unconfirmed');continue
                record['criterion_ids']=[c.id for c in considered]
            if target is None:
                kinds={DISTANCES[c.metric] for c in considered if c.metric in DISTANCES}
                target=next(iter(kinds)) if len(kinds)==1 else 'shops' if module in ('living','health','dining') else 'academy'
            allowed={'living':{'grocery','convenience','shops'}, 'health':{'pharmacy','clinic','hospital','shops'},
                     'dining':{'everyday_meal','restaurant','shops'}, 'education':{'academy','school'}}[module]
            if target not in allowed:
                record.update(status='not_executed',reason='facility_type_unsupported');continue
            factual=(module in ('education','health') and target not in ('school','pharmacy')
                     and not re.search(r'후기|만족(?!도)|불만|평판|이용\s*경험',text))
            ids=set()
            relevant={c.id for c in considered if (module=='education' and
                c.metric==('academy_count_within_radius' if target=='academy' else 'school_straight_line_distance_m')) or
                (module in ('living','health','dining') and c.metric in DISTANCES and (target=='shops' or DISTANCES[c.metric]==target))}
            for result in enriched['modules']:
                for e in result['evidence']:
                    if (e['criterion_id'] in relevant and e['source_record'] and
                            (module not in ('health','dining') or e.get('status')=='verified')):
                        ids.add(e['source_record'])
            if module=='education':
                for detail in enriched.get('education_details',[]):
                    if detail['criterion_id'] in relevant:ids.update(r['id'] for r in detail['selected'])
            # A named facility request must match a verified target rather than silently using a nearest substitute.
            name=next((f.value for f in reversed(profile.context) if f.key==module+'_research_facility' and f.source_quote==quote),None)
            rows=[f for id,f in enriched['facilities'].items() if id in ids and
                  f['kind']==('shops' if module in ('living','health','dining') else target) and (name is None or f['name']==name)]
            if module=='education':
                from .modules.education import SUBJECTS
                scope={field:next((f.value for f in reversed(profile.context) if f.key=='education_research_'+field and f.source_quote==quote),None)
                       for field in ('subject','school_level','radius_m')}
                scope={key:value for key,value in scope.items() if value is not None}
                if factual and scope:
                    from .modules.education import LEVELS
                    if scope.get('subject') and scope['subject'] not in SUBJECTS or scope.get('school_level') and scope['school_level'] not in LEVELS:
                        record.update(status='not_executed',reason='condition_scope_unconfirmed');continue
                    considered=[c.model_copy(update={'parameters':{**c.parameters,**scope}}) for c in considered]
                hinted={key for key,value in SUBJECTS.items() if value in text}
                if '파닉스' in text:hinted.add('english')
                actual={c.parameters.get('subject') for c in considered if factual or c.id in relevant}
                if hinted and not scope.get('subject') and not hinted<=actual:
                    record.update(status='not_executed',reason='subject_scope_unconfirmed');continue
                if scope and not factual:
                    bases=[c for c in considered if c.id in relevant]
                    if len(bases)!=1 or education_index is None:
                        record.update(status='not_executed',reason='condition_scope_unconfirmed');continue
                    scoped=bases[0].model_copy(deep=True);scoped.parameters={**scoped.parameters,**scope}
                    try:
                        selected={r['id']:r for c in candidates for r in education_index.observe(scoped,c)['selected']}
                    except (ValueError,TypeError):
                        record.update(status='not_executed',reason='condition_scope_unconfirmed');continue
                    rows=[r for r in selected.values() if name is None or r['name']==name]
                    considered=[scoped]
            if factual:
                # Registered leads may have unknown grade/subject. Do not remove them before web verification,
                # and do not add them to the confirmed count/distance evidence.
                pool=[]
                if module=='education' and education_index is not None:
                    subject=scope.get('subject') or next((c.parameters.get('subject') for c in considered if c.parameters.get('subject')),None)
                    pool=[r for r in education_index.records.values() if r['kind']=='academy'
                          and (not subject or not r['subjects'] or subject in r['subjects'])]
                    radii=[c.parameters.get('radius_m') for c in considered if c.parameters.get('radius_m')]
                    try:
                        import math
                        radius=float(scope.get('radius_m') or (radii[0] if radii else 2000))
                        if not math.isfinite(radius) or not 0<radius<=20000:raise ValueError('invalid radius')
                    except (ValueError,TypeError):
                        record.update(status='not_executed',reason='condition_scope_unconfirmed');continue
                elif module=='health' and shop_index is not None:
                    from .facility_leads import medical_types
                    types=medical_types(text)
                    pool=[r for r in shop_index.records.values() if r['detail'] in types]
                    radius=2000
                else:
                    pool=rows;radius=2000
                from .facility_leads import nearby_leads
                rows=nearby_leads(pool,candidates,radius,name)
                record.update(research_kind='facility_fact',radius_m=radius,
                              scope_note='등록 후보의 사실 확인 범위이며 사용자 거리 기준이나 전체 시설 목록이 아니에요.')
                if module=='education':
                    labels={'math':'수학','english':'영어','korean':'국어','science':'과학','art':'미술','music':'음악',
                            'elementary':'초등','middle':'중등','high':'고등'}
                    requested=' · '.join(dict.fromkeys(labels.get(v,v) for c in considered
                        for v in (c.parameters.get('subject'),c.parameters.get('school_level')) if v))
                    text=(requested+' '+text+' — 운영자의 실제 과목·대상 학년·요청한 수업 형태를 확인해 주세요.').strip()
                else:text+=' — 운영자의 실제 진료과·요청한 이용 조건을 확인해 주세요.'
            rows.sort(key=lambda f:(min(distance_m(c.latitude,c.longitude,f['lat'],f['lon']) for c in candidates),f['id']))
            if not rows and (not factual or name is not None):
                record.update(status='not_executed',reason='no_verified_facility_for_request');continue
            record['facility_ids']=[r['id'] for r in rows]
            task_key=(module,'facility_fact' if factual else 'review')
            task=facility_tasks.setdefault(task_key,{'module':module,'research_kind':task_key[1],'facilities':{},'questions':[],'request_ids':[]})
            task['request_ids'].append(record['id'])
            task['questions'].append({'request_id':record['id'],'question':text,'criterion_ids':record['criterion_ids'],
                'facility_ids':record['facility_ids'],'target':target,
                'parameters':[dict(criterion_id=c.id,**c.parameters) for c in considered if factual or c.id in relevant]})
            task['facilities'].update({r['id']:r for r in rows})
    tasks=[]
    for module,task in facility_tasks.items():
        # Round robin gives each question a target before spending the category's 3-facility budget.
        lists=[q['facility_ids'] for q in task['questions']];chosen=[]
        if task['research_kind']=='facility_fact':
            if task['module']=='health':
                # Keep day-to-day clinics in the shared budget rather than spending it only on hospitals.
                clinics=[f for f in task['facilities'].values() if '의원' in (f.get('detail') or '')]
                hospitals=[f for f in task['facilities'].values() if '병원' in (f.get('detail') or '')]
                for candidate in candidates:
                    available=[f for f in clinics if candidate.id in f.get('candidate_ids',[])]
                    available.sort(key=lambda f:(f['candidate_distances'][candidate.id],f['id']))
                    if available and available[0]['id'] not in chosen and len(chosen)<2:chosen.append(available[0]['id'])
                clinics.sort(key=lambda f:(min(f['candidate_distances'].values()),f['id']))
                for f in clinics:
                    if len(chosen)>=2:break
                    if f['id'] not in chosen:chosen.append(f['id'])
                hospitals.sort(key=lambda f:(min(f['candidate_distances'].values()),f['id']))
                if hospitals and len(chosen)<3:chosen.append(hospitals[0]['id'])
            # Give each compared home a nearby lead before filling the shared category budget.
            for candidate in candidates:
                available=[f for f in task['facilities'].values() if candidate.id in f.get('candidate_ids',[])]
                available.sort(key=lambda f:(f['candidate_distances'][candidate.id],f['id']))
                if available and available[0]['id'] not in chosen and len(chosen)<3:chosen.append(available[0]['id'])
        for n in range(max(map(len,lists),default=0)):
            for ids in lists:
                if n<len(ids) and ids[n] not in chosen and len(chosen)<3:chosen.append(ids[n])
        for record in records:
            if record['id'] not in task['request_ids']:continue
            old=record['facility_ids'];record['facility_ids']=[id for id in old if id in chosen]
            record['unsearched_facility_ids']=[id for id in old if id not in chosen]
            if not record['facility_ids'] and (old or task['research_kind']!='facility_fact'):
                record.update(status='not_executed',reason='facility_limit')
        task['facilities']=[task['facilities'][id] for id in chosen]
        task['questions']=[dict(q,facility_ids=[id for id in q['facility_ids'] if id in chosen]) for q in task['questions']
                           if any(id in chosen for id in q['facility_ids']) or
                           task['research_kind']=='facility_fact' and not q['facility_ids']]
        task['request_ids']=[q['request_id'] for q in task['questions']]
        tasks.append(task)
    if target_questions:
        tasks.append({'module':'safety','targets':[dict(t,questions=target_questions) for t in targets],
                      'request_ids':[q['request_id'] for q in target_questions]})
    if leisure_scope:
        for request in leisure_scope.get('requests',[]):
            request['questions']=[{'request_id':r['id'],'question':r['question']} for r in records
                if r['module']=='leisure' and r['status']=='queued' and (not r['criterion_ids'] or request['criterion_id'] in r['criterion_ids'])]
        ready=[r for r in records if r['module']=='leisure' and r['status']=='queued']
        if ready:tasks.append({'module':'leisure','scope':leisure_scope,'request_ids':[r['id'] for r in ready]})
    return {'requests':records,'tasks':tasks,'score_eligible':False,
            'limits':{'facilities_per_category_and_research_kind':3,'areas':3,'hobby_requests':3},
            'status_meaning':'Execution and source acceptance; not proof that an excerpt answers every question.'}


def evidence_status(module,value,request_id=None):
    items=value.get('items',[]) if module in ('living','education','health','dining','facility_reviews','safety') else value.get('discoveries',[])
    if any(request_id is None or request_id in x.get('request_ids',[]) for i in items for x in i.get('excerpts',[])):return 'found'
    if any(i.get('status') in ('unverified','discovered_date_unknown','request_unverified') or i.get('rejected_count',0) or i.get('rejection_reasons') for i in items) or value.get('rejected_count',0):return 'unverified'
    return 'not_found'
