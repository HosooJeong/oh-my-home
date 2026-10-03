from datetime import timedelta
from threading import Event
import time
import unittest
from unittest.mock import patch

from app.contracts import NeedProfile, Evidence, ContextFact, output_schema
from app.llm_settings import ModelSettings
from app.modules.leisure import LeisureIndex, LeisureModule, PARK_SOURCE, LIBRARY_SOURCE, SHOP_SOURCE
from app.leisure_preferences import LeisureInput, leisure_profile
from app.leisure_research import (FoundFacility, LeisureResearchResponse, research_leisure, public_url, fetch_page)
from app.orchestrator import Orchestrator
from app.research_policy import today, SourcePage
from app.codex_runner import RunnerError
from app.web import AppState, CompareInput, PreferenceInput
from app.intake import prepare_profile
from test_living import candidates, index, profile
from research_fixture import supported_review


def settings(**changes):
    return LeisureInput(**(dict(profile=None,include_park=True,park_type='children',include_library=False,
        library_type='any',ideal=0.0,limit=1500.0,park_importance=50.0,library_importance=20.0,
        include_meeting=False,meeting_label='',meeting_latitude=None,meeting_longitude=None,meeting_importance=20.0,
        include_hobby=False,activity='pilates',activity_form='기구 소그룹',hobby_importance=30.0,group_weight=30.0)|changes))


def facility(identity='park:a',kind='park',**changes):
    return dict(id=identity,kind=kind,name='가상공원' if kind=='park' else '가상도서관',address='경상남도 진주시 가상로 1',
        lat=35.18,lon=128.1,type='어린이공원' if kind=='park' else '공공도서관',date=today().isoformat(),
        source_url=PARK_SOURCE if kind=='park' else LIBRARY_SOURCE,source_row=1,facilities={})|changes


def leisure(*rows,inventory=None):
    return LeisureIndex(dict(retrieved_at=today().isoformat(),records=list(rows),excluded={}),inventory)


def excerpt(**changes):
    return FoundFacility(**(dict(name='가상필라테스',address='경상남도 진주시 가상로 2',activity='pilates',
        source_url='https://studio.example.org/posts/1',source_role='operator',title='가상 센터 안내',
        published_date=today().isoformat(),quote='기구 필라테스 소그룹을 제공한다.',interpretation='운영자의 기구 소그룹 안내야.')|changes))


class RunnerFixture:
    last_metadata={'web_search_count':1}
    def __init__(self,*items): self.answer=LeisureResearchResponse(facilities=list(items))
    def run(self,prompt,model,**options):
        review=supported_review(prompt,model)
        if review is not None:return review
        self.prompt,self.options=prompt,options;return self.answer


SCOPE={'city':'진주시','areas':['가상동'],'activities':['pilates'],'forms':{'pilates':['기구 소그룹']},'registered_leads':[]}
PAGE_TEXT='가상필라테스 경상남도 진주시 가상로 2 기구 필라테스 소그룹을 제공한다.'


class LeisureTests(unittest.TestCase):
    def test_purpose_filter_and_confirmed_distance_score(self):
        p=leisure_profile(settings())
        i=leisure(facility(type='근린공원'),facility('park:b',lon=128.11))
        r=Orchestrator({'leisure':LeisureModule(i)}).run(p,candidates())
        self.assertEqual(r['report']['ranking'],['b','a'])
        self.assertEqual(r['modules'][0]['evidence'][0]['source_record'],'park:b')

    def test_stale_library_and_unlocated_park_leave_weight_unknown(self):
        for row,p in [(facility('library:a','library',date=(today()-timedelta(days=400)).isoformat()),leisure_profile(settings(include_park=False,include_library=True))),
                      (facility(lat=None,lon=None),leisure_profile(settings()))]:
            r=Orchestrator({'leisure':LeisureModule(leisure(row))}).run(p,candidates())
            self.assertEqual(r['modules'][0]['evidence'][0]['status'],'missing')
            self.assertIsNone(r['report']['assessments'][0]['score'])
            self.assertEqual(r['report']['ranking'],[])

    def test_school_libraries_empty_inventory_and_outside_not_confirmed_absence(self):
        p=leisure_profile(settings(include_park=False,include_library=True))
        for i in (leisure(),leisure(facility('library:a','library',type='학교도서관'))):
            o=i.observe(p.criteria[0],candidates()[0]);self.assertIsNone(o['value']);self.assertEqual(o['status'],'missing')
        c=candidates()[0];c.latitude=37.5
        self.assertIsNone(leisure(facility()).observe(leisure_profile(settings()).criteria[0],c)['value'])

    def test_hobby_keeps_unsupported_weight_and_registration_lead_is_not_form_proof(self):
        p=leisure_profile(settings(include_hobby=True))
        i=leisure(facility(),inventory={'records':[dict(id='shops:a',kind='shops',name='가상요가',address='경상남도 진주시 가상로 2',detail='요가/필라테스 학원',lat=35.18,lon=128.1,date=today().isoformat(),source_url=SHOP_SOURCE)]})
        r=Orchestrator({'leisure':LeisureModule(i)}).run(p,candidates())
        self.assertIn(p.criteria[1].id,r['modules'][0]['unsupported_criterion_ids'])
        self.assertGreater(r['report']['assessments'][0]['coverage'],0)
        self.assertLess(r['report']['assessments'][0]['coverage'],1)
        self.assertEqual(i.hobby_rows('pilates')[0]['name'],'가상요가')
        scope=i.hobby_scope(p,candidates());self.assertNotIn('latitude',str(scope));self.assertNotIn(p.request,str(scope))

    def test_explicit_meeting_point_has_user_provenance_and_zero_distance(self):
        p=leisure_profile(settings(include_park=False,include_meeting=True,meeting_label='가족 만남 장소',meeting_latitude=35.18,meeting_longitude=128.1))
        r=Orchestrator({'leisure':LeisureModule(leisure())}).run(p,candidates())
        e=r['modules'][0]['evidence'][0]
        self.assertEqual(e['value'],0);self.assertEqual(e['source_kind'],'user');self.assertIsNone(e['source_url'])
        self.assertEqual(r['report']['ranking'],['a','b'])
        with self.assertRaises(ValueError): settings(include_meeting=True)

    def test_intake_rejects_invented_meeting_coordinates(self):
        p=leisure_profile(settings(include_park=False,include_meeting=True,meeting_label='만남 장소',meeting_latitude=35.18,meeting_longitude=128.1))
        class Runner:
            def run(self,*args,**kwargs):return p
        # Natural-language source mentions no coordinates; the model invents them.
        request='가족과 만나는 장소까지 가까웠으면 좋겠어.'
        p.request=request;p.criteria[0].source_quote=request
        p.context=[]
        with self.assertRaises(RunnerError):prepare_profile(Runner(),request)
        p.request=request+' 위도 35.18, 경도 128.1'
        self.assertEqual(prepare_profile(Runner(),p.request).criteria[0].parameters['meeting_latitude'],'35.18')

    def test_edit_preserves_other_and_unsupported_needs_and_custom_hard_scopes(self):
        old=profile();p=leisure_profile(settings(profile=old,include_hobby=True))
        self.assertEqual(p.criteria[:2],old.criteria);self.assertEqual(p.groups[0],old.groups[0])
        q=leisure_profile(settings(profile=p,include_park=False,include_hobby=True))
        self.assertEqual(q.criteria[2].importance,0);self.assertEqual(q.criteria[3].importance,30)
        p.criteria[2].hard={'operator':'lte','value':1000.0}
        with self.assertRaises(ValueError): leisure_profile(settings(profile=p))

    def test_parameter_schema_supports_scopes_and_clears_null_fields(self):
        props=output_schema(NeedProfile)['$defs']['MetricParameters']['properties']
        self.assertTrue({'park_type','activity','meeting_latitude','school_level'}<=set(props))
        p=leisure_profile(settings());p.criteria[0].parameters={'park_type':'children','activity':None}
        self.assertEqual(p.criteria[0].parameters,{'park_type':'children'})

    def test_untrusted_source_and_coordinate_or_duplicate_record_rejected(self):
        for rows in ([facility(source_url='https://example.org')],[facility(lat=32.2)],[facility(),facility()]):
            with self.assertRaises(ValueError): leisure(*rows)

    def test_custom_hobby_is_searched_and_outside_city_does_not_query(self):
        p=leisure_profile(settings(include_hobby=True,activity='other',activity_name='클라이밍',activity_form='초보 강습'))
        scope=leisure().hobby_scope(p,candidates())
        self.assertEqual(scope['activity_names']['other'],'클라이밍')
        c=candidates()[0];c.latitude=37.5
        self.assertIsNone(leisure().hobby_scope(p,[c]))
        with self.assertRaises(ValueError):settings(include_hobby=True,activity='other')

    def test_forged_user_provenance_cannot_bypass_public_source_contract(self):
        from app.modules.living import LivingModule
        class Forged(LivingModule):
            def run(self,request,cancel):
                result=super().run(request,cancel)
                result.evidence[0].source_kind='user'
                result.evidence[0].source_url=None
                return result
        r=Orchestrator({'living':Forged(index())}).run(profile(),candidates())
        self.assertEqual(r['modules'][0]['status'],'failed')

    def test_cancel_during_fetch_does_not_publish_result(self):
        event=Event()
        def fetch(u,c):
            event.set();return SourcePage(PAGE_TEXT,(today().isoformat(),))
        with self.assertRaises(RunnerError):research_leisure(RunnerFixture(excerpt()),SCOPE,cancel=event,index=leisure(),fetcher=fetch)

    def test_dated_operator_and_experience_and_dedup_are_unscored(self):
        answer=research_leisure(RunnerFixture(excerpt(),excerpt()),SCOPE,cancel=Event(),index=leisure(),
            fetcher=lambda u,c:SourcePage(PAGE_TEXT,(today().isoformat(),)))
        self.assertEqual(len(answer['discoveries']),1);self.assertFalse(answer['discoveries'][0]['score_eligible'])
        self.assertTrue(answer['discoveries'][0]['excerpts']);self.assertFalse(answer['discoveries'][0]['coordinates_confirmed'])

    def test_undated_operator_is_discovery_only_undated_experience_rejected(self):
        for role,expected in [('operator',1),('experience',0)]:
            answer=research_leisure(RunnerFixture(excerpt(published_date=None,source_role=role)),SCOPE,cancel=Event(),index=leisure(),fetcher=lambda u,c:SourcePage(PAGE_TEXT,()))
            self.assertEqual(len(answer['discoveries']),expected)
            if expected:self.assertEqual(answer['discoveries'][0]['excerpts'],[])

    def test_old_wrong_branch_wrong_activity_and_quote_rejected(self):
        examples=[(excerpt(published_date=(today()-timedelta(days=800)).isoformat()),SourcePage(PAGE_TEXT,((today()-timedelta(days=800)).isoformat(),))),
                  (excerpt(),SourcePage(PAGE_TEXT.replace('가상로 2','가상로 3'),(today().isoformat(),))),
                  (excerpt(activity='gym'),SourcePage(PAGE_TEXT,(today().isoformat(),))),
                  (excerpt(quote='없는 원문 인용'),SourcePage(PAGE_TEXT,(today().isoformat(),)))]
        for item,page in examples:
            r=research_leisure(RunnerFixture(item),SCOPE,cancel=Event(),index=leisure(),fetcher=lambda u,c:page)
            self.assertEqual(r['discoveries'],[]);self.assertEqual(r['rejected_count'],1)

    def test_search_proof_cancel_and_private_network_rejected(self):
        runner=RunnerFixture(excerpt());runner.last_metadata={'web_search_count':0}
        self.assertFalse(research_leisure(runner,SCOPE,cancel=Event(),index=leisure())['discoveries'])
        event=Event();event.set()
        with self.assertRaises(RunnerError):research_leisure(runner,SCOPE,cancel=event,index=leisure())
        for u in ['http://example.org/a','https://127.0.0.1/a','https://localhost/a','https://map.naver.com/p','https://x.kakao.com/a','https://x.local/a']:
            self.assertIsNone(public_url(u))
        with patch('app.leisure_research.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('app.leisure_research.build_opener') as opener:
            self.assertIsNone(fetch_page('https://studio.example.org/a',Event()));opener.return_value.open.assert_not_called()

    def test_conditional_main_pipeline_and_reweight_reuse(self):
        class Runner: last_metadata={'fixture':True}
        state=AppState(index(),Runner,llm_settings=ModelSettings(provider='codex'),leisure_index=leisure(facility()));_,session=state.session()
        p=leisure_profile(settings());run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
        self.assertNotIn('research_job',run)
        p=leisure_profile(settings(include_hobby=True));
        with patch('app.web.research_leisure',return_value={'discoveries':[],'score_eligible':False}) as search:
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            job=session['review_job']
            for _ in range(100):
                if job['status']!='running':break
                time.sleep(.01)
            self.assertEqual(job['status'],'completed');self.assertEqual(search.call_count,1)
            revised=state.preferences(session,PreferenceInput(run_id=run['run_id'],group_weights={'leisure':80.0},criterion_importance={},confirm_weights=True))
            self.assertEqual(search.call_count,1);self.assertEqual(revised['run']['review_key'],run['review_key'])
            self.assertEqual(revised['run']['modules'],run['modules'])

    def test_failed_other_supplement_does_not_skip_hobby(self):
        class Runner: last_metadata={}
        state=AppState(index(),Runner,llm_settings=ModelSettings(provider='codex'),leisure_index=leisure(facility()));_,session=state.session()
        p=leisure_profile(settings(include_hobby=True))
        p.context.append(ContextFact(key='safety_research',value='requested',source_quote=p.request))
        p.context.append(ContextFact(key='safety_research_question',value='침수 피해와 완료된 조치 자료를 찾아줘.',source_quote=p.request))
        # Provide a verified-area test target, separate from real geography.
        with patch.object(state.safety_index,'research_targets',return_value=[{'area_code':'a','area_name':'가상동','topics':['flood']}]),patch('app.web.research_safety',side_effect=RunnerError('timeout')),patch('app.web.research_leisure',return_value={'discoveries':[]}) as hobby:
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            job=session['review_job']
            for _ in range(100):
                if job['status']!='running':break
                time.sleep(.01)
            self.assertEqual(hobby.call_count,1);self.assertEqual(job['result']['errors'][0]['module'],'safety')
