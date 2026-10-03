from datetime import date
from threading import Event
import unittest
from app.contracts import NeedProfile
from app.intake import prepare_profile, source_segments
from app.need_coverage import required_sources
from app.modules.living import ShopIndex
from app.modules.registered_access import RegisteredAccessModule
from app.orchestrator import Orchestrator
from app.research_plan import build_research_plan
from app.candidates import execution_plan
from test_living import shop, candidates
from test_need_coverage import FakeRunner, criterion, draft, need


def profile(module='health', metric='pharmacy_straight_line_distance_m'):
    return NeedProfile.model_validate(dict(schema_version='1', revision=1, request='약국이 가까우면 좋겠어요.',
        context=[], questions=[], groups=[dict(id=module,label=module,weight=100.0,source='user',reason='시험 조건')],
        criteria=[dict(id='access',group_id=module,module_id=module,label='접근성',need='가까움',
            source_quote='약국이 가까우면 좋겠어요.',source='user',importance=100.0,importance_source='user',
            metric=metric,utility=dict(direction='lower',ideal=100.0,limit=1500.0,unit='m'),hard=None)]))


class RegisteredAccessTests(unittest.TestCase):
    def run_module(self, rows, p=None):
        p=p or profile()
        index=ShopIndex(dict(generated_at='fixture', records=rows))
        module=RegisteredAccessModule(p.criteria[0].module_id,index,date(2026,10,3))
        return Orchestrator({module.id:module}).run(p,candidates())

    def test_pharmacy_distance_uses_exact_registered_type_and_bound_source(self):
        r=self.run_module([shop('shops:a','시험 약국','약국',128.10),shop('shops:b','의료기기 판매점','의료기기 소매업',128.11)])
        es=r['modules'][0]['evidence'];self.assertEqual(es[0]['value'],0)
        self.assertTrue(all(e['status']=='verified' and e['source_record']=='shops:a' for e in es))
        self.assertEqual(r['status'],'completed');self.assertEqual(es[0]['data_date'],'2026-06-30')

    def test_clinic_scope_excludes_veterinary_dental_and_general_hospitals(self):
        rows=[shop('shops:a','시험 내과','내과/소아과 의원',128.10),shop('shops:b','시험 동물병원','동물병원',128.11),
              shop('shops:c','시험 치과','치과의원',128.11),shop('shops:d','시험 병원','일반병원',128.11)]
        r=self.run_module(rows,profile(metric='clinic_straight_line_distance_m'))
        self.assertTrue(all(e['source_record']=='shops:a' for e in r['modules'][0]['evidence']))
        self.assertIn('진료과',r['modules'][0]['evidence'][0]['note'])

    def test_everyday_meal_does_not_count_cafes_bars_or_food_retail(self):
        rows=[shop('shops:a','시험 백반','백반/한정식',128.10)] + [shop('shops:'+str(i),t,t,128.11)
            for i,t in enumerate(['카페','요리 주점','반찬/식료품 소매업','돼지고기 구이/찜'])]
        r=self.run_module(rows,profile('dining','everyday_meal_straight_line_distance_m'))
        self.assertTrue(all(e['source_record']=='shops:a' for e in r['modules'][0]['evidence']))

    def test_restaurant_includes_meals_and_grill_but_excludes_cafes_and_bars(self):
        r=self.run_module([shop('shops:a','시험 구이','돼지고기 구이/찜',128.10),shop('shops:b','시험 카페','카페',128.11)],
                          profile('dining','restaurant_straight_line_distance_m'))
        self.assertEqual(r['status'],'completed');self.assertTrue(all(e['source_record']=='shops:a' for e in r['modules'][0]['evidence']))

    def test_stale_future_and_absent_records_remain_unknown_not_zero(self):
        for stamp in ['2025-01-01','2026-12-01','invalid']:
            rows=[shop('shops:a','가까운 약국','약국',128.10),shop('shops:b','먼 약국','약국',128.15)]
            rows[0]['date']=stamp;r=self.run_module(rows)
            self.assertIsNone(r['modules'][0]['evidence'][0]['value']);self.assertEqual(r['modules'][0]['evidence'][0]['status'],'missing')
        r=self.run_module([]);self.assertEqual(r['report']['assessments'][0]['coverage'],0)
        self.assertIsNone(r['modules'][0]['evidence'][0]['value'])

    def test_walking_and_quality_requirements_are_not_converted_to_straight_distance(self):
        p=profile();p.criteria[0].utility.unit='min';r=self.run_module([],p)
        self.assertEqual(r['modules'][0]['unsupported_criterion_ids'],['access']);self.assertEqual(r['modules'][0]['evidence'],[])
        p=profile(metric='clinical_quality');r=self.run_module([],p)
        self.assertEqual(r['modules'][0]['unsupported_criterion_ids'],['access'])

    def test_discovery_plan_recognizes_both_new_modules_without_hiding_unsupported_needs(self):
        for group,metric in [('health','clinic_straight_line_distance_m'),('dining','restaurant_straight_line_distance_m')]:
            p=profile(group,metric);self.assertEqual(execution_plan(p)[0]['role'],'query')
            p.criteria[0].metric='quality_unknown';self.assertEqual(execution_plan(p)[0]['role'],'unverified')

    def test_new_category_priority_headers_are_app_scaffolding_not_missing_user_needs(self):
        request='\n'.join(name+': 중요도 60, 상대 비중 15%.' for name in
            ['생활·장보기','교통·동선','교육·육아','건강·의료','여가·관계','식사·외식'])
        self.assertEqual(required_sources(source_segments([request])),[])
        self.assertEqual(len(required_sources(source_segments([request+'\n약국이 가까우면 좋겠어요.']))),1)

    def test_intake_supports_new_group_and_original_soft_scale_without_numeric_interview(self):
        for group,metric,text in [('health','pharmacy_straight_line_distance_m','약국이 집 바로 가까이에 있으면 좋겠어요.'),
                                  ('dining','everyday_meal_straight_line_distance_m','백반집이 가까우면 좋겠어요.')]:
            d=draft(groups=[dict(id=group,weight=100.0,source='user')],
                criteria=[criterion('access',metric,group,need=text,utility=None)],
                needs=[need(ids=('access',),group=group)])
            p=prepare_profile(FakeRunner(d),text)
            self.assertEqual(p.criteria[0].module_id,group);self.assertEqual(p.criteria[0].source_quote,text)
            self.assertIsNone(p.criteria[0].hard);self.assertEqual(p.questions,[])
            self.assertIsNotNone(p.criteria[0].comparison_proposal)

    def test_new_research_uses_only_verified_same_type_facilities_and_stays_unscored(self):
        p=profile('dining','everyday_meal_straight_line_distance_m');p.context=[
            dict(key='dining_research',value='requested',source_quote='백반 후기'),
            dict(key='dining_research_question',value='백반 선택지에 관한 공개 평가가 있나요?',source_quote='백반 후기')]
        p=NeedProfile.model_validate(p.model_dump());row=shop('shops:a','시험 백반','백반/한정식',128.10)
        run=self.run_module([row],p);enriched={**run,'facilities':{'shops:a':row}}
        plan=build_research_plan(p,candidates(),enriched,[],None)
        self.assertEqual(plan['tasks'][0]['module'],'dining');self.assertEqual(plan['requests'][0]['facility_ids'],['shops:a'])
        self.assertEqual(plan['tasks'][0]['questions'][0]['target'],'everyday_meal')

    def test_stale_health_or_dining_records_do_not_become_verified_research_targets(self):
        p=profile('health','pharmacy_straight_line_distance_m');p.context=[
            dict(key='health_research',value='requested',source_quote='약국 이용 정보'),
            dict(key='health_research_question',value='약국의 공개 이용 정보를 알려주세요.',source_quote='약국 이용 정보')]
        p=NeedProfile.model_validate(p.model_dump());row=shop('shops:a','시험 약국','약국',128.10);row['date']='2025-01-01'
        run=self.run_module([row],p);plan=build_research_plan(p,candidates(),{**run,'facilities':{'shops:a':row}},[],None)
        self.assertEqual(plan['tasks'],[]);self.assertEqual(plan['requests'][0]['status'],'not_executed')
