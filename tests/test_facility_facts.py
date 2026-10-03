import json
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from app.facility_facts import FacilityFact,FacilityFacts,FactsResponse,research_facility_facts,public_url,DiscoveryResponse,DiscoveredFacility,discover_facility_facts,registered_course_facts
from app.facility_leads import medical_types
from app.research_policy import SourcePage,today
from app.research_plan import build_research_plan,evidence_status
from app.contracts import Criterion,ContextFact
from app.education_preferences import education_profile
from app.response_validation import ResponseReview
from research_fixture import supported_review
from test_education import settings,education,facility
from test_living import index,candidates,profile


def fact(**changes):
    return FacilityFact(**(dict(field='subject',value='수학',source_url='https://academy.example.org/courses',
        title='학원 수업 안내',source_role='operator',published_date=None,matched_name='가상학원',
        identity_note='상호와 가상로 1 일치',quote='초등 수학 수업',interpretation='초등 수학 수업을 안내하고 있어요.')|changes))


class Runner:
    def __init__(self,facts=None,search_count=1,verifier=None):
        self.facts=[fact()] if facts is None else facts;self.last_metadata={'web_search_count':search_count}
        self.calls=[];self.verifier=verifier
    def run(self,prompt,response_type,**kw):
        self.calls.append((prompt,kw))
        if response_type is ResponseReview:
            if self.verifier:return self.verifier(prompt,response_type)
            return supported_review(prompt,response_type)
        return FactsResponse(items=[FacilityFacts(facility_id='academy:a',facts=self.facts)])


class FacilityFactTests(unittest.TestCase):
    def test_directory_source_is_accepted_only_as_a_qualified_listing_not_an_official_fact(self):
        f=fact(source_role='directory',interpretation='외부 서비스에 초등 수학으로 표기되어 있어요. 운영자 확인은 미확인이에요.')
        value=self.research(Runner([f]));x=value['items'][0]['excerpts'][0]
        self.assertEqual(x['evidence_level'],'service_listing');self.assertFalse(x['score_eligible'])
        f.interpretation='초등 수학 수업을 실제 제공해요.'
        rejected=self.research(Runner([f]))['items'][0]
        self.assertEqual(rejected['excerpts'],[]);self.assertEqual(rejected['rejection_reasons'],{'directory_claim_unqualified':1})

    def test_directory_reference_date_cannot_replace_verified_publication_or_bypass_freshness(self):
        base=dict(source_role='directory',interpretation='외부 안내에 수학이 표기되어 있어요. 운영자 확인은 미확인이에요.')
        for published in ('2018-01-01','2099-01-01',today().isoformat()):
            with self.subTest(published=published):
                result=self.research(Runner([fact(**base,published_date=published)]))['items'][0]
                self.assertEqual(result['excerpts'],[])
        for host in ('https://blog.naver.com/operator/123','https://operator.tistory.com/12'):
            self.assertEqual(self.research(Runner([fact(**base,source_url=host)]))['items'][0]['excerpts'],[])

    def test_education_course_field_survives_empty_web_results_without_inferred_grades_or_scores(self):
        row=facility('academy:a',courses='초등수학1 / 보습')
        qs=[dict(request_id='q1',question='초등 수학 수업',facility_ids=['academy:a'],parameters=[])]
        value=research_facility_facts(Runner([]),[row],cancel=Event(),questions=qs)
        self.assertEqual([(x['field'],x['value']) for x in value['items'][0]['excerpts']],[('subject','수학'),('school_level','초등')])
        x=value['items'][0]['excerpts'][0];self.assertEqual(x['quote'],'초등수학1')
        self.assertEqual(x['source_reference_date'],row['date']);self.assertIsNone(x['published_date'])
        self.assertTrue(x['registry_source']);self.assertFalse(x['score_eligible'])
        self.assertEqual(value['facilities'][row['id']]['name'],row['name'])
        row['courses']='보습 / 보습';row['name']='초등수학 가상학원'
        self.assertEqual(registered_course_facts([row],qs),{})
        row['courses']='초등수학1';row['date']='2018-01-01'
        self.assertEqual(registered_course_facts([row],qs),{})

    def test_clinic_leads_are_not_crowded_out_by_closer_hospitals(self):
        p=profile();p.groups[0].id='health';p.criteria[0].group_id='health';p.criteria[0].module_id='health'
        p.criteria[0].metric='department_fit_unverified';p.criteria[0].need='내과와 소아청소년과 의원 이용';p.criteria[0].utility=None
        cs=candidates();rows=[]
        for n,(detail,offset) in enumerate([('일반병원',0),('종합병원',.0001),('내과/소아과 의원',.0002),('내과/소아과 의원',.0003)]):
            rows.append(dict(id='medical:'+str(n),kind='shops',name='가상의료기관'+str(n),address='진주시 가상로 1',
                detail=detail,date=today().isoformat(),lat=cs[0].latitude+offset,lon=cs[0].longitude))
        shop_index=SimpleNamespace(records={r['id']:r for r in rows})
        plan=build_research_plan(p,cs,{'modules':[],'facilities':{}},[],None,None,shop_index)
        chosen=plan['tasks'][0]['facilities']
        self.assertEqual(sum('의원' in r['detail'] for r in chosen),2);self.assertEqual(len(chosen),3)

    def research(self,runner=None,page=None):
        return research_facility_facts(runner or Runner(),[facility('academy:a')],cancel=Event(),
            questions=[dict(request_id='q1',question='초등 수학 수업',facility_ids=['academy:a'],parameters=[])],
            fetcher=lambda *args:page or SourcePage('가상학원 가상로 1 초등 수학 수업',()))

    def test_official_undated_fact_is_explicitly_unknown_update_and_independently_reviewed(self):
        runner=Runner();value=self.research(runner);x=value['items'][0]['excerpts'][0]
        self.assertEqual(x['field'],'subject');self.assertEqual(x['value'],'수학')
        self.assertIsNone(x['published_date']);self.assertFalse(x['publication_verified'])
        self.assertEqual(x['freshness_status'],'live_page_update_unknown');self.assertTrue(x['quote_verified'])
        self.assertEqual(x['request_ids'],['q1']);self.assertFalse(value['score_eligible'])
        self.assertEqual([c[1]['search'] for c in runner.calls],[True,False])
        self.assertNotIn('domains',runner.calls[0][1]);self.assertNotIn('"lat"',runner.calls[0][0])
        self.assertEqual(evidence_status('education',value,'q1'),'found')

    def test_old_future_wrong_target_unquoted_value_and_missing_search_fail_closed(self):
        for f in [fact(published_date='2018-01-01'),fact(published_date='2099-01-01'),
                  fact(matched_name='다른학원'),fact(field='department'),fact(value='영어')]:
            self.assertEqual(self.research(Runner([f]))['items'][0]['excerpts'],[])
        self.assertEqual(self.research(Runner(search_count=0))['items'][0]['excerpts'],[])

    def test_address_and_date_must_be_in_the_actual_page(self):
        for page in [SourcePage('가상학원 가상로 9 초등 수학 수업',()),
                     SourcePage('가상학원 가상로 1 초등 수학 수업',('2026-01-01',))]:
            self.assertEqual(self.research(page=page)['items'][0]['excerpts'],[])
        dated=Runner([fact(published_date=today().isoformat())])
        self.assertTrue(self.research(dated,SourcePage('가상학원 가상로 1 초등 수학 수업',(today().isoformat(),)))['items'][0]['excerpts'])

    def test_verifier_failure_rejects_even_an_exact_quote(self):
        def fail(*args):raise ValueError('malformed verifier')
        value=self.research(Runner(verifier=fail))
        self.assertEqual(value['items'][0]['excerpts'],[]);self.assertEqual(value['response_validation']['status'],'failed')

    def test_public_links_exclude_credentials_private_addresses_and_maps(self):
        for url in ['https://127.0.0.1/a','http://10.0.0.1/a','https://u:p@academy.org/a',
                    'https://academy.local/a','https://map.naver.com/a','https://place.map.kakao.com/a',
                    'https://academy.org:999/a','https://academy.org\\@evil.com/a']:
            self.assertIsNone(public_url(url))
        self.assertEqual(public_url('http://academy.example.org/courses?c=math#top'),'http://academy.example.org/courses?c=math')
        self.assertEqual(public_url('https://blog.naver.com/operator/123'),'https://blog.naver.com/operator/123')

    def test_health_and_dining_execution_status_reads_items(self):
        value={'items':[{'excerpts':[{'request_ids':['q1']}]}]}
        self.assertEqual(evidence_status('health',value,'q1'),'found')
        self.assertEqual(evidence_status('dining',value,'q1'),'found')
        self.assertEqual(evidence_status('health',value,'q2'),'not_found')

    def test_medical_leads_are_not_a_mixed_internal_pediatric_proxy_or_veterinary(self):
        types=medical_types('이비인후과가 가까우면 좋겠어요.')
        self.assertIn('이비인후과 의원',types);self.assertNotIn('내과/소아과 의원',types)
        self.assertNotIn('동물병원',medical_types('병원'))

    def test_academy_need_automatically_searches_unknown_grade_without_changing_count(self):
        p=education_profile(settings(include_school=False,qualitative_research=False))
        p.context=[f for f in p.context if f.key!='education_research']
        e=education(facility('academy:a',subject_levels={'math':[]}))
        observations=[e.observe(p.criteria[0],c) for c in candidates()]
        self.assertTrue(all(o['status']=='missing' and not o['selected'] for o in observations))
        plan=build_research_plan(p,candidates(),{'modules':[],'facilities':{}},[],None,e,index())
        self.assertEqual(plan['tasks'][0]['research_kind'],'facility_fact')
        self.assertEqual(plan['tasks'][0]['facilities'][0]['id'],'academy:a')
        self.assertIn('수학',plan['tasks'][0]['questions'][0]['question'])
        self.assertEqual(plan['requests'][0]['status'],'queued')
        self.assertTrue(all(e.observe(p.criteria[0],c)['status']=='missing' for c in candidates()))

    def test_health_department_need_uses_factual_research_without_opt_in(self):
        p=profile();p.groups[0].id='health';p.groups[0].label='건강·의료'
        p.criteria=[Criterion(id='department',group_id='health',module_id='health',label='이비인후과',
             need='이비인후과가 가까우면 좋겠어요.',source_quote='이비인후과가 가까우면 좋겠어요.',
             source='user',importance=100,importance_source='user',metric='department_fit_unverified',utility=None,hard=None)]
        s=index();s.records['shops:a']['detail']='이비인후과 의원'
        plan=build_research_plan(p,candidates(),{'modules':[],'facilities':{}},[],None,education(),s)
        self.assertEqual(plan['tasks'][0]['research_kind'],'facility_fact')
        self.assertEqual(plan['tasks'][0]['facilities'][0]['id'],'shops:a')
        self.assertIn('이비인후과',plan['tasks'][0]['questions'][0]['question'])

    def test_factual_request_can_bind_an_unscored_academy_condition(self):
        p=education_profile(settings(include_school=False));c=p.criteria[0]
        c.metric='academy_subject_grade_fit_unverified';c.utility=None
        q='초등 수학 학원의 실제 과목을 확인해 주세요.'
        p.context=[ContextFact(key=k,value=v,source_quote=c.source_quote) for k,v in
            [('education_research_question',q),('education_research_criterion_id',c.id),
             ('education_research_subject','math'),('education_research_school_level','elementary')]]
        plan=build_research_plan(p,candidates(),{'modules':[],'facilities':{}},[],None,education(facility('academy:a')),index())
        self.assertEqual(plan['requests'][0]['status'],'queued')
        self.assertEqual(plan['tasks'][0]['questions'][0]['parameters'][0]['subject'],'math')
        self.assertIsNone(c.utility)

    def test_automatic_question_does_not_forward_private_family_or_diagnosis_text(self):
        from app.research_plan import questions
        p=profile();p.criteria[0].module_id='health';p.criteria[0].metric='department_fit_unverified'
        p.criteria[0].need='김가상 아이가 민감한 진단을 받아서 이비인후과가 필요해요.'
        query=questions(p,'health')[0][0]
        self.assertIn('이비인후과',query);self.assertNotIn('김가상',query);self.assertNotIn('진단',query)

    def test_explicit_web_opt_out_stays_disabled(self):
        p=education_profile(settings(include_school=False,qualitative_research=False))
        plan=build_research_plan(p,candidates(),{'modules':[],'facilities':{}},[],None,education(facility('academy:a')),index())
        self.assertEqual(plan['tasks'],[])

    def test_automatic_research_local_qualifier_binds_without_the_word_search(self):
        from app.need_coverage import review_needs,IntakeNeed
        p=education_profile(settings(include_school=False));c=p.criteria[0]
        first='초등학생 대상 수학 학원이 가까이에 있으면 좋겠어요.'
        second='어떤 과목과 학년을 가르치는지가 중요해요.'
        c.source_quote=first;c.need=first;c.parameters={'school_level':'elementary','subject':'math'};c.utility=None;c.importance_source='proposed'
        p.context=[ContextFact(key='education_research',value='requested',source_quote=first),
                   ContextFact(key='education_research_purpose',value='과목과 학년 확인',source_quote=second)]
        needs=[IntakeNeed(source_id='s1',group_id='education',aspect='facility_count',handling='compare',
                         criterion_ids=[c.id],context_keys=[],resolution_source_id=None,field='need'),
               IntakeNeed(source_id='s2',group_id='education',aspect='facility_fit',handling='research',
                         criterion_ids=[c.id],context_keys=['education_research','education_research_purpose'],
                         resolution_source_id=None,field='context')]
        result,meta=review_needs(p,{'s1':first,'s2':second},needs,required_ids=['s1','s2'])
        self.assertEqual(meta['unresolved_source_count'],0)
        self.assertEqual(result.questions,[])
        needs[1].criterion_ids=[]
        result,meta=review_needs(p,{'s1':first,'s2':second},needs,required_ids=['s1','s2'])
        self.assertEqual(meta['unresolved_source_count'],0)
        self.assertEqual(result.questions,[])

    def test_dateless_operator_blog_is_not_a_dateless_current_service_page(self):
        value=self.research(Runner([fact(source_url='https://blog.naver.com/operator/123')]))
        self.assertEqual(value['items'][0]['excerpts'],[])
        self.assertEqual(value['items'][0]['rejection_reasons'],{'date_unknown':1})

    def test_web_discovery_verifies_a_facility_absent_from_registry_and_does_not_invent_distance(self):
        runner=Runner()
        def run(prompt,response_type,**kw):
            runner.calls.append((prompt,kw))
            if response_type is ResponseReview:return supported_review(prompt,response_type)
            return DiscoveryResponse(facilities=[DiscoveredFacility(name='가상학원',address='경상남도 진주시 가상로 1',facts=[fact()])])
        runner.run=run
        value=discover_facility_facts(runner,'education',[dict(request_id='q1',question='초등 수학')],cancel=Event(),areas=['충무공동'],
            fetcher=lambda *args:SourcePage('가상학원 진주시 가상로 1 초등 수학 수업',()))
        item=value['items'][0];self.assertTrue(item['web_discovery']);self.assertEqual(item['status'],'found')
        self.assertEqual(item['candidate_distances'],{});self.assertEqual(item['candidate_ids'],[])
        self.assertNotIn('lat',next(iter(value['facilities'].values())))
        self.assertIn('충무공동',runner.calls[0][0]);self.assertNotIn('latitude',runner.calls[0][0])
        self.assertFalse(value['score_eligible'])

    def test_other_city_discovery_is_not_accepted(self):
        runner=Runner()
        runner.run=lambda *args,**kw:DiscoveryResponse(facilities=[DiscoveredFacility(name='가상학원',address='서울특별시 가상로 1',facts=[fact()])])
        value=discover_facility_facts(runner,'education',[],cancel=Event())
        self.assertEqual(value['facilities'],{});self.assertEqual(value['rejected_count'],1)

    def test_no_registered_academy_leads_still_plan_public_web_discovery(self):
        p=education_profile(settings(include_school=False,qualitative_research=True))
        plan=build_research_plan(p,candidates(),{'modules':[],'facilities':{}},[],None,education(),index())
        self.assertEqual(plan['requests'][0]['status'],'queued')
        self.assertEqual(plan['tasks'][0]['facilities'],[])
        self.assertEqual(plan['tasks'][0]['research_kind'],'facility_fact')
        self.assertTrue(plan['tasks'][0]['questions'])

if __name__=='__main__':unittest.main()
