"""Regression cases: editing one preference must not change another decision."""
import unittest
from threading import Event
from app.contracts import NeedProfile, ContextFact
from app.web import QuickInput, quick_profile
from app.preference_edits import PreservationError
from app.transport_preferences import transport_profile
from app.education_preferences import education_profile
from app.leisure_preferences import leisure_profile
from app.safety_preferences import safety_profile
from app.modules.transport import TransportModule
from app.modules.education import EducationModule
from app.modules.leisure import LeisureModule
from app.orchestrator import Orchestrator
from app.leisure_research import research_leisure
from app.research_policy import SourcePage
from test_living import candidates
from test_transport import edit, stops, stop
from test_education import settings as education_settings, education, facility as school
from test_leisure import settings as leisure_settings, leisure, facility
from test_safety import settings as safety_settings


class ConditionPreservationTests(unittest.TestCase):
    def test_living_shortcut_edits_keep_other_categories_and_original_constraints(self):
        p=transport_profile(edit())
        original=p.model_dump();original['criteria'][0]['hard']={'operator':'lte','value':300.0};p=NeedProfile.model_validate(original)
        q=quick_profile(QuickInput(profile=p,ideal=300.0,limit=1500.0,supermarket_weight=80.0,
            convenience_weight=20.0,mandatory_limit=False,edited_fields=['supermarket_weight']))
        self.assertEqual(q.criteria[0].utility,p.criteria[0].utility);self.assertEqual(q.criteria[0].hard,p.criteria[0].hard)
        self.assertEqual(q.criteria[-1],p.criteria[-1]);self.assertEqual(q.groups,p.groups);self.assertEqual(q.context,p.context)
        self.assertEqual(q.criteria[0].importance,80);self.assertEqual(p.model_dump(),original)
    def test_time_edit_keeps_hard_boundary_and_ineligible_candidate(self):
        p=transport_profile(edit(ideal=0.0,limit=1000.0,mandatory_limit=True))
        p.criteria[-1].hard.value=300.0
        module=TransportModule(stops([stop(lon=128.105)]))
        before=Orchestrator({'transport':module}).run(p,candidates())
        q=transport_profile(edit(p,ideal=0.0,limit=1000.0,mandatory_limit=True,time_of_day='오전 9시',edited_fields=['time_of_day']))
        self.assertEqual(q.criteria[-1].model_dump(),p.criteria[-1].model_dump())
        self.assertEqual(q.criteria[-1].hard.value,300)
        self.assertEqual(q.request[len(p.request):],'\n조건 수정: 이용 시간대 = "오전 9시"')
        self.assertEqual(Orchestrator({'transport':module}).run(q,candidates())['report']['assessments'],before['report']['assessments'])
        legacy=transport_profile(edit(p,ideal=0.0,limit=1000.0,mandatory_limit=True,time_of_day='오전 9시'))
        self.assertEqual(legacy.criteria[-1].hard.value,300)
        explicit=transport_profile(edit(p,mandatory_limit=True,hard_limit=600.0,edited_fields=['hard_limit']))
        self.assertEqual(explicit.criteria[-1].hard.value,600)

    def test_multiple_family_contexts_preserved_or_edit_rejected(self):
        p=transport_profile(edit())
        p.context.extend([ContextFact(key='travel_destination',value='배우자 직장',source_quote=p.request),ContextFact(key='travel_time',value='밤 10시',source_quote=p.request)])
        original=p.model_dump()
        q=transport_profile(edit(p,importance=90.0,edited_fields=['importance']))
        self.assertEqual(q.context,p.context)
        with self.assertRaises(PreservationError):transport_profile(edit(p,time_of_day='오전 9시',edited_fields=['time_of_day']))
        self.assertEqual(p.model_dump(),original)

    def test_education_weight_edit_retains_specific_school_and_hard(self):
        p=education_profile(education_settings(include_academy=False))
        p.criteria[0].parameters['school_id']='school:chosen'
        raw=p.model_dump();raw['criteria'][0]['hard']={'operator':'lte','value':500.0};p=NeedProfile.model_validate(raw)
        module=EducationModule(education(school('school:chosen','school',lon=128.11),school('school:near','school')))
        before=Orchestrator({'education':module}).run(p,candidates())
        q=education_profile(education_settings(profile=p,include_academy=False,group_weight=50.0,edited_fields=['group_weight']))
        self.assertEqual(q.criteria,p.criteria)
        self.assertEqual(Orchestrator({'education':module}).run(q,candidates())['report']['assessments'],before['report']['assessments'])
        q=education_profile(education_settings(profile=p,include_academy=False))
        self.assertEqual(q.criteria[0].parameters['school_id'],'school:chosen');self.assertEqual(q.criteria[0].hard,p.criteria[0].hard)

    def test_leisure_weight_edit_does_not_replace_library_curve(self):
        p=leisure_profile(leisure_settings(include_library=True,ideal=500.0,limit=1000.0,park_importance=40.0,library_importance=60.0))
        library=next(c for c in p.criteria if c.metric=='library_straight_line_distance_m')
        library.utility=library.utility.model_copy(update={'ideal':1500.0,'limit':3000.0})
        for fields in (None,['park_importance']):
            q=leisure_profile(leisure_settings(profile=p,include_library=True,ideal=500.0,limit=1000.0,park_importance=41.0,library_importance=60.0,edited_fields=fields))
            self.assertEqual(next(c for c in q.criteria if c.id==library.id).utility,library.utility)
        q=leisure_profile(leisure_settings(profile=p,include_library=True,ideal=600.0,limit=1600.0,edited_fields=['ideal','limit']))
        self.assertTrue(all(c.utility.limit==1600 for c in q.criteria if c.utility))

    def test_safety_radius_edit_preserves_detailed_need_and_question(self):
        p=safety_profile(safety_settings())
        c=next(c for c in p.criteria if c.module_id=='safety')
        c.need='밤11시 역에서 집까지 골목길 조명 확인';c.label='내 귀갓길'
        original=[c.model_dump() for c in p.criteria]
        q=safety_profile(safety_settings(profile=p,radius_m=700.0,edited_fields=['radius_m']))
        self.assertEqual([c.model_dump() for c in q.criteria],original)
        self.assertEqual(next(c.value for c in q.context if c.key=='safety_radius_m'),'700.0')

    def test_custom_hobbies_keep_name_form_and_request_identity(self):
        p=leisure_profile(leisure_settings(include_hobby=True,activity='other',activity_name='배드민턴',activity_form='초보 강습'))
        c=next(c for c in p.criteria if c.metric=='hobby_suitability')
        raw=p.model_dump();raw['criteria'].append(c.model_dump()|{'id':'climbing','parameters':{'activity':'other','activity_name':'클라이밍','activity_form':'자유 이용'}})
        p=NeedProfile.model_validate(raw);scope=leisure().hobby_scope(p,candidates())
        self.assertEqual([(r['activity_name'],r['forms']) for r in scope['requests']],[('배드민턴',['초보 강습']),('클라이밍',['자유 이용'])])
        self.assertNotIn('other',scope['forms']);self.assertEqual(scope['unsearched_activity_count'],0)
        class Runner:
            last_metadata={'web_search_count':1}
            def run(self,prompt,model,**kw):
                return model.model_validate({'facilities':[{'name':'가상시설','address':'경남 진주시 가상로 1','activity':'other','source_url':'https://example.com/article','source_role':'operator','title':'종목','published_date':None,'quote':'배드민턴','interpretation':'안내'}]})
        result=research_leisure(Runner(),scope,cancel=Event(),index=leisure(),fetcher=lambda *args:self.fail('ambiguous request must not fetch'))
        self.assertEqual(result['discoveries'],[])
        self.assertEqual(result['rejection_reasons'],{'activity_request_unverified':1})

        class IdentifiedRunner(Runner):
            def run(self,prompt,model,**kw):
                return model.model_validate({'facilities':[
                    {'criterion_id':r['criterion_id'],'name':'가상시설','address':'경남 진주시 가상로 1','activity':'other',
                     'source_url':'https://example.com/article','source_role':'operator','title':'종목',
                     'published_date':None,'quote':r['activity_name'],'interpretation':'안내'} for r in scope['requests']]})
        result=research_leisure(IdentifiedRunner(),scope,cancel=Event(),index=leisure(),
            fetcher=lambda *args:SourcePage('가상시설 경남 진주시 가상로 1 배드민턴 초보 강습 클라이밍 자유 이용',()))
        self.assertEqual(result['rejected_count'],0)
        self.assertEqual([(d['criterion_id'],d['activity_name']) for d in result['discoveries']],
                         [(r['criterion_id'],r['activity_name']) for r in scope['requests']])
        self.assertTrue(all(not d['score_eligible'] for d in result['discoveries']))

    def test_unchanged_forms_preserve_entire_profile_and_question(self):
        for p, apply, data in [
            (transport_profile(edit()),transport_profile,edit),
            (education_profile(education_settings()),education_profile,education_settings),
            (leisure_profile(leisure_settings()),leisure_profile,leisure_settings),
            (safety_profile(safety_settings()),safety_profile,safety_settings)]:
            raw=p.model_dump();raw['questions']=[dict(id='retain_question',criterion_ids=[p.criteria[0].id],
                text='누가 이용할지 확인해 줘.',reason='이용자에 따라 조건이 달라.',blocking=False)]
            p=NeedProfile.model_validate(raw)
            self.assertEqual(apply(data(profile=p,edited_fields=[])).model_dump(),p.model_dump())

    def test_explicit_scope_edit_keeps_original_need_and_extra_parameters(self):
        p=education_profile(education_settings());p.criteria[1].need='아이 수준에 맞는 수업을 원해.'
        q=education_profile(education_settings(profile=p,subject='english',edited_fields=['subject']))
        self.assertEqual(q.criteria[0],p.criteria[0])
        self.assertEqual(q.criteria[1].parameters['subject'],'english')
        self.assertTrue(q.criteria[1].need.startswith(p.criteria[1].need))
        self.assertIn('영어',q.criteria[1].label)
        p=leisure_profile(leisure_settings(include_hobby=True,activity='other',activity_name='배드민턴',activity_form='초보 강습'))
        original=next(c for c in p.criteria if c.metric=='hobby_suitability')
        q=leisure_profile(leisure_settings(profile=p,include_hobby=True,activity='other',activity_name='클라이밍',activity_form='초보 강습',edited_fields=['activity_name']))
        changed=next(c for c in q.criteria if c.id==original.id)
        self.assertEqual(changed.parameters['activity_name'],'클라이밍');self.assertEqual(changed.parameters['activity_form'],'초보 강습')
        self.assertTrue(changed.need.startswith(original.need));self.assertIn('클라이밍',changed.label)


if __name__=='__main__': unittest.main()
