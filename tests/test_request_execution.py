import json,time,unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from app.contracts import ContextFact,NeedProfile,output_schema
from app.codex_runner import RunnerError
from app.intake import IntakeDraft
from app.modules.housing import HousingModule,HousingIndex,HousingQuery
from app.modules.education import EducationIndex
from app.education_preferences import education_profile
from app.reviews import research_reviews,ReviewResponse,StoreReviews,ReviewInput
from app.web import AppState,CompareInput,PreferenceInput
from test_living import index,profile,candidates
from test_housing import document
from test_education import settings,facility,education


def fact(p,key,value,quote=None):
    p.context.append(ContextFact(key=key,value=value,source_quote=quote or value))


def query_profile(**values):
    p=profile()
    quote='가상동 아파트 월세 신규계약 전용 40㎡ 이상 60㎡ 미만 참고 조회'
    for key,value in dict(housing_tenure='monthly',housing_legal_area='가상동',housing_area_min_m2='40',
                          housing_area_max_m2='60',housing_contract='new',**{}).items():
        fact(p,key,values.pop(key,value),quote)
    for key,value in values.items():fact(p,key,value,quote)
    return p


def research_profile():
    p=education_profile(settings(profile=profile(),include_school=False,subject='english'))
    living='마트의 알레르기 상품 표시와 휠체어 출입 정보를 찾아줘.'
    school='초등 영어 파닉스 8명 이하 반과 주 3회 수업을 조사해 줘.'
    for module,flag,text,target in [('living','qualitative_research_requested',living,'grocery'),('education','education_research',school,'academy')]:
        fact(p,flag,'requested',text);fact(p,module+'_research_question',text,text);fact(p,module+'_research_target',target,text)
    return p


def state():
    return AppState(index(),lambda:SimpleNamespace(last_metadata={'fixture':True}),education_index=education(
        facility('academy:english',subjects=['english'],subject_levels={'english':['elementary']}),facility('academy:math')))


def wait_job(app,session):
    job=session['review_job'];deadline=time.monotonic()+3
    while job['status']=='running' and time.monotonic()<deadline:time.sleep(.005)
    if job['status']=='running':raise AssertionError('job did not finish')
    return app.public_job(job)


class HousingScopeTests(unittest.TestCase):
    def test_profile_filters_are_applied_and_reference_never_changes_scores(self):
        m=HousingModule(HousingIndex(document()));p=query_profile()
        r=m.run_reference(p,candidates(),Event())
        self.assertEqual((r.query['legal_area'],r.query['tenure'],r.query['contract'],r.sample_count),('가상동','monthly','new',2))
        self.assertEqual((r.query['area_min_m2'],r.query['area_max_m2']),(40,60))
        app=state();app.housing=m;app.orchestrator.reference_modules['housing']=m
        _,session=app.session();a=app.compare(session,CompareInput(profile=profile(),candidates=candidates()))
        b=app.compare(session,CompareInput(profile=p,candidates=candidates()))
        for key in ('assessments','ranking','ranking_status'):self.assertEqual(a['report'][key],b['report'][key])
        self.assertEqual(b['references'][0]['sample_count'],2)

    def test_unknown_area_type_conversion_invalid_value_or_budget_is_not_widened(self):
        for fields in ({'housing_legal_area':'없는동'},{'housing_type':'빌라'},{'housing_area':'30평'},
                       {'housing_tenure':'guess'},{'housing_area_min_m2':'nan'},{'housing_budget':'3억원 이하'}):
            with self.subTest(fields=fields):
                r=HousingModule(HousingIndex(document())).run_reference(query_profile(**fields),candidates(),Event())
                self.assertEqual(r.status,'unsupported');self.assertEqual(r.sample_count,0)
                self.assertTrue(r.unhandled_filters);self.assertFalse(r.distributions)

    def test_inclusive_upper_bound_is_supported_and_omitted_inclusion_is_rejected(self):
        m=HousingModule(HousingIndex(document()))
        self.assertEqual(m.reference(HousingQuery(area_max_m2=50.0)).sample_count,0)
        self.assertEqual(m.reference(HousingQuery(area_max_m2=50.0,area_max_inclusive=True)).sample_count,5)
        p=query_profile(housing_area_max_m2='50')
        for f in p.context:f.source_quote='가상동 아파트 월세 신규 전용 40㎡ 이상 50㎡ 이하'
        self.assertEqual(m.run_reference(p,candidates(),Event()).status,'unsupported')
        fact(p,'housing_area_max_inclusive','true','전용 40㎡ 이상 50㎡ 이하')
        self.assertEqual(m.run_reference(p,candidates(),Event()).sample_count,2)

    def test_conflicting_queries_and_no_data_are_explicit(self):
        p=query_profile();fact(p,'housing_contract','renewal','갱신 계약')
        self.assertEqual(HousingModule(HousingIndex(document())).run_reference(p,[],Event()).status,'unsupported')
        self.assertEqual(HousingModule(HousingIndex()).run_reference(profile(),[],Event()).status,'unavailable')

    def test_area_unit_detection_does_not_mistake_a_legal_area_name(self):
        doc=document()
        for row in doc['records']:row['legal_area']='평거동'
        p=query_profile(housing_legal_area='평거동')
        for f in p.context:f.source_quote=f.source_quote.replace('가상동','평거동')
        r=HousingModule(HousingIndex(doc)).run_reference(p,[],Event())
        self.assertNotEqual(r.status,'unsupported');self.assertEqual(r.sample_count,2)


class RequestExecutionTests(unittest.TestCase):
    def test_living_and_education_both_run_with_distinct_original_questions(self):
        app=state();_,session=app.session();p=research_profile();seen=[]
        def search(runner,shops,**kw):
            seen.append((shops,kw));return {'items':[{'facility_id':s['id'],'excerpts':[],'status':'not_found'} for s in shops]}
        with patch('app.web.research_reviews',side_effect=search):
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));done=wait_job(app,session)
        self.assertEqual({s[0][0]['kind'] for s in seen},{'shops','academy'})
        self.assertEqual(len(seen),2);self.assertEqual(len(done['result']['items']),2)
        self.assertEqual({r['module'] for r in done['request_statuses']},{'living','education'})
        for r in done['request_statuses']:
            self.assertEqual(r['status'],'completed');self.assertEqual(r['evidence_status'],'not_found')
        shops=next(kw for rows,kw in seen if rows[0]['kind']=='shops')
        school=next(kw for rows,kw in seen if rows[0]['kind']=='academy')
        self.assertIn('알레르기',shops['questions'][0]['question']);self.assertIn('휠체어',shops['questions'][0]['question'])
        self.assertIn('8명',school['questions'][0]['question']);self.assertIn('주 3회',school['questions'][0]['question'])
        self.assertEqual(school['questions'][0]['parameters'][0]['subject'],'english')
        self.assertEqual(run['report'],session['comparison'][2]['report'])

    def test_a_failed_category_does_not_skip_the_other_and_scores_remain_intact(self):
        app=state();_,session=app.session();p=research_profile()
        def search(runner,shops,**kw):
            if shops[0]['kind']=='shops':raise RunnerError('timeout')
            return {'items':[{'facility_id':shops[0]['id'],'excerpts':[],'status':'not_found'}]}
        with patch('app.web.research_reviews',side_effect=search):
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));done=wait_job(app,session)
        by={r['module']:r for r in done['request_statuses']}
        self.assertEqual(by['living']['status'],'failed');self.assertEqual(by['living']['reason'],'timeout')
        self.assertEqual(by['education']['status'],'completed');self.assertTrue(done['result']['items'])
        self.assertEqual(run['report'],session['comparison'][2]['report'])

    def test_no_target_named_substitute_unsupported_type_and_unsupported_module_are_not_searched(self):
        for changes in [('living_research_facility','확인되지 않은 매장'),('living_research_target','병원')]:
            app=state();_,session=app.session();p=profile();q='필요한 시설 정보를 찾아줘.'
            fact(p,'living_research_question',q,q);fact(p,changes[0],changes[1],q)
            with patch('app.web.research_reviews') as search:
                r=app.compare(session,CompareInput(profile=p,candidates=candidates()))
            self.assertFalse(search.called);self.assertNotIn('research_job',r)
            self.assertEqual(r['research_plan']['requests'][0]['status'],'not_executed')
        app=state();_,session=app.session();p=profile();fact(p,'transport_research_question','퇴근 버스의 실제 배차를 조사해 줘.')
        r=app.compare(session,CompareInput(profile=p,candidates=candidates()))
        self.assertEqual(r['research_plan']['requests'][0]['reason'],'research_module_unsupported')

    def test_subject_specific_scope_uses_requested_subject_and_leaves_existing_score_evidence_alone(self):
        app=state();_,session=app.session();p=research_profile()
        academy=next(c for c in p.criteria if c.metric=='academy_count_within_radius');academy.parameters['subject']='math'
        quote=next(f.source_quote for f in p.context if f.key=='education_research_question')
        fact(p,'education_research_subject','english',quote);selected=[]
        with patch('app.web.research_reviews',side_effect=lambda runner,rows,**kw:selected.extend(rows) or {'items':[]}):
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));wait_job(app,session)
        self.assertIn('academy:english',[r['id'] for r in selected]);self.assertNotIn('academy:math',[r['id'] for r in selected])
        self.assertEqual(academy.parameters['subject'],'math')
        self.assertTrue(any(r['id']=='academy:math' for d in run['education_details'] for r in d['selected']))

    def test_subject_mismatch_without_query_scope_is_not_a_generic_other_subject_search(self):
        app=state();_,session=app.session();p=research_profile()
        next(c for c in p.criteria if c.metric=='academy_count_within_radius').parameters['subject']='math'
        with patch('app.web.research_reviews',return_value={'items':[]}):
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));done=wait_job(app,session)
        education_request=next(r for r in done['request_statuses'] if r['module']=='education')
        self.assertEqual(education_request['reason'],'subject_scope_unconfirmed')

    def test_public_question_only_goes_to_facilities_it_belongs_to(self):
        runner=SimpleNamespace(last_metadata={'web_search_count':1})
        def answer(prompt,response_type,**kw):
            runner.prompt=prompt;return ReviewResponse(items=[StoreReviews(facility_id='shops:a',excerpts=[])])
        runner.run=answer
        research_reviews(runner,[index().records['shops:a']],cancel=Event(),questions=[
            dict(request_id='q1',question='휠체어 출입',criterion_ids=['grocery'],parameters=[],facility_ids=['shops:a']),
            dict(request_id='q2',question='초등 파닉스 반',criterion_ids=['academy'],parameters=[],facility_ids=['academy:a'])])
        payload=json.loads(runner.prompt.split('입력 JSON:\n')[1])
        self.assertEqual([q['request_id'] for q in payload[0]['questions']],['q1'])
        self.assertNotIn('초등 파닉스 반',runner.prompt)

    def test_cancel_marks_running_and_remaining_requests_and_retains_public_results(self):
        app=state();_,session=app.session();p=research_profile();started=Event()
        def search(runner,rows,**kw):
            started.set();kw['cancel'].wait(2);raise RunnerError('cancelled')
        with patch('app.web.research_reviews',side_effect=search) as tool:
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));self.assertTrue(started.wait(1))
            session['review_job']['cancel'].set();done=wait_job(app,session)
        self.assertEqual(tool.call_count,1);self.assertEqual(done['status'],'cancelled')
        self.assertTrue(all(r['status']=='cancelled' for r in done['request_statuses']))
        self.assertIsNone(done['result']);self.assertEqual(run['report'],session['comparison'][2]['report'])

    def test_reweight_reuses_requests_without_new_search(self):
        app=state();_,session=app.session();p=research_profile()
        with patch('app.web.research_reviews',return_value={'items':[]}) as tool:
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));wait_job(app,session)
            revised=app.preferences(session,PreferenceInput(run_id=run['run_id'],group_weights={},criterion_importance={},confirm_weights=True))
        self.assertEqual(tool.call_count,2);self.assertEqual(revised['run']['research_plan'],run['research_plan'])
        self.assertTrue(all(r['status']=='completed' for r in revised['run']['research_plan']['requests']))

    def test_acceptance_status_is_limited_to_the_requested_facility(self):
        app=state();_,session=app.session();p=profile()
        for q,target in [('마트 알레르기 표기','grocery'),('편의점 휠체어 출입','convenience')]:
            fact(p,'living_research_question',q,q);fact(p,'living_research_target',target,q)
        def search(runner,rows,**kw):
            return {'items':[{'facility_id':r['id'],'excerpts':[{'quote':'fixture'}] if r['id']=='shops:a' else [],'status':'not_found'} for r in rows]}
        with patch('app.web.research_reviews',side_effect=search):
            app.compare(session,CompareInput(profile=p,candidates=candidates()));done=wait_job(app,session)
        by={r['question']:r['evidence_status'] for r in done['request_statuses']}
        self.assertEqual(by,{'마트 알레르기 표기':'found','편의점 휠체어 출입':'not_found'})

    def test_manual_review_also_forwards_original_question(self):
        app=state();_,session=app.session();p=research_profile();cs=candidates();run=app.orchestrator.run(p,cs)
        session['comparison']=(p,cs,run);session['review_key']=run['run_id'];seen=[]
        with patch('app.web.research_reviews',side_effect=lambda runner,rows,**kw:seen.append(kw) or {'items':[]}):
            app.reviews(session,ReviewInput(request_id='manual',run_id=run['run_id'],facility_ids=['shops:a']));wait_job(app,session)
        self.assertIn('알레르기',seen[0]['questions'][0]['question'])

    def test_runner_start_failure_is_preserved_in_the_comparison_plan(self):
        app=state();_,session=app.session()
        def fail():raise RunnerError('authentication_required')
        app.runner_factory=fail
        run=app.compare(session,CompareInput(profile=research_profile(),candidates=candidates()));done=wait_job(app,session)
        self.assertEqual(done['status'],'failed')
        self.assertTrue(all(r['reason']=='authentication_required' for r in run['research_plan']['requests']))

    def test_hobby_requests_beyond_the_budget_are_not_marked_executed(self):
        from app.leisure_preferences import leisure_profile
        from test_leisure import settings as leisure_settings,leisure,facility as hobby_facility
        p=leisure_profile(leisure_settings(include_hobby=True))
        base=next(c for c in p.criteria if c.metric=='hobby_suitability')
        for n in range(3):
            c=base.model_copy(deep=True);c.id='hobby_extra_'+str(n);c.need='헬스 자율 이용 조건 '+str(n);p.criteria.append(c)
        app=AppState(index(),lambda:SimpleNamespace(last_metadata={}),leisure_index=leisure(hobby_facility()))
        _,session=app.session()
        with patch('app.web.research_leisure',return_value={'discoveries':[]}):
            run=app.compare(session,CompareInput(profile=p,candidates=candidates()));done=wait_job(app,session)
        leftover=next(r for r in done['request_statuses'] if 'hobby_extra_2' in r['criterion_ids'])
        self.assertEqual(leftover['status'],'not_executed');self.assertEqual(leftover['reason'],'activity_limit_or_unsupported')

    def test_private_or_missing_original_question_is_not_sent_as_generic_research(self):
        for q in ('내 집 가상로 23에서 가까운 시설','문의 번호 010-1234-5678'):
            app=state();_,session=app.session();p=profile();fact(p,'living_research_question',q)
            with patch('app.web.research_reviews') as tool:r=app.compare(session,CompareInput(profile=p,candidates=candidates()))
            self.assertFalse(tool.called);self.assertEqual(r['research_plan']['requests'][0]['reason'],'private_question_requires_public_summary')


if __name__=='__main__':unittest.main()
