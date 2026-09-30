from datetime import timedelta
from threading import Event
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from app.contracts import Candidate, SafetyReferenceResult, output_schema
from app.modules.safety import CctvIndex, SafetyModule, SOURCE, METRICS
from app.safety_preferences import SafetyInput, safety_profile
from app.safety_research import (research_safety, official_url, parse_official_article,
                                 SafetyResearchResponse, SafetyExcerpt, AreaResearch)
from app.research_policy import today, SourcePage
from app.orchestrator import Orchestrator
from app.codex_runner import RunnerError
from app.web import AppState, CompareInput, PreferenceInput
from test_living import profile, candidates, index


class BoundaryFixture:
    features = {'38030111': {'properties': {'name':'가상동'}}}
    def area_at(self, lat, lon): return '38030111' if lat==35.18 else None


def cctv(identity, **changes):
    return dict(id=identity,source_row=1,kind='cctv',name='생활방범 CCTV',lat=35.18,lon=128.1,
        date=today().isoformat(),date_label='공개본 수정일 (관측일 아님)',source_url=SOURCE) | changes


def snapshot(*rows, boundary=True):
    return CctvIndex({'generated_at':today().isoformat(),'records':list(rows)},BoundaryFixture() if boundary else None,3)


def settings(**changes):
    return SafetyInput(**(dict(profile=profile(),topics=['flood','night'],group_weight=30.0,
        criterion_importance=100.0,radius_m=500.0,qualitative_research=False)|changes))


def article(**changes):
    return SafetyExcerpt(**(dict(source_url='https://www.jinju.go.kr/00138.web?amode=view&gcode=1004&idx=123',
        title='가상동 침수 예방 조치',published_date=today().isoformat(),topic='flood',
        quote='가상동 침수 예방 사업을 진행한다.',interpretation='발표된 예방 사업이며 개별 집 안전은 미확인이야.')|changes))


class RunnerFixture:
    def __init__(self,*excerpts,search_count=1):
        self.answer = SafetyResearchResponse(items=[AreaResearch(area_code='38030111',excerpts=list(excerpts))])
        self.last_metadata = {'web_search_count':search_count}
        self.prompt = None
    def run(self,prompt,model,**options):
        self.prompt,self.options=prompt,options; return self.answer


TARGET=[{'area_code':'38030111','area_name':'가상동','topics':['flood']}]


class SafetyTests(unittest.TestCase):
    def test_duplicate_coordinate_rows_are_points_not_camera_counts(self):
        i=snapshot(cctv('a'),cctv('b'),cctv('c',lon=128.4))
        o=i.observe(candidates()[0],500)
        self.assertEqual((o.registered_rows_within_radius,o.registered_coordinate_points_within_radius),(2,1))
        self.assertEqual(o.nearest_source_records,['a','b'])
        self.assertEqual(o.nearest_distance_m,0)
        self.assertEqual(i.metadata()['coordinate_points'],2)
        with self.assertRaises(ValueError): snapshot(cctv('a'),cctv('a'))

    def test_zero_in_radius_unavailable_boundary_and_outside_are_distinct(self):
        o=snapshot(cctv('far',lon=128.4)).observe(candidates()[0],100)
        self.assertEqual(o.registered_coordinate_points_within_radius,0)
        self.assertGreater(o.nearest_distance_m,100)
        for i in (snapshot(),snapshot(cctv('a'),boundary=False)):
            self.assertIsNone(i.observe(candidates()[0],100).registered_rows_within_radius)
        c=candidates()[0]; c.latitude=37.5
        self.assertEqual(snapshot(cctv('a')).observe(c,100).status,'outside_scope')

    def test_old_publication_is_reference_only_and_future_or_bad_source_rejected(self):
        o=snapshot(cctv('a',date=(today()-timedelta(days=366)).isoformat())).observe(candidates()[0],100)
        self.assertEqual(o.status,'stale')
        for changes in (dict(date='2099-01-01'),dict(lat=32.2),dict(source_url='https://example.com'),dict(date_label='')):
            with self.assertRaises(ValueError): snapshot(cctv('a',**changes))

    def test_needs_and_personal_weights_preserved_but_no_cctv_safety_score(self):
        p=safety_profile(settings()); i=snapshot(cctv('a')); m=SafetyModule(i)
        self.assertEqual(p.criteria[:2],profile().criteria)
        self.assertEqual(p.groups[0],profile().groups[0])
        from app.modules.living import LivingModule
        r=Orchestrator({'living':LivingModule(index()),'safety':m},reference_modules={'safety':m}).run(p,candidates())
        self.assertEqual(r['references'][0]['score_eligible'],False)
        self.assertFalse(next(m for m in r['modules'] if m['module_id']=='safety')['evidence'])
        self.assertEqual(r['report']['ranking_status'],'withheld')
        self.assertIsNone(r['report']['assessments'][0]['score'])
        q=safety_profile(settings(profile=p,topics=[]))
        self.assertEqual(q.criteria[2].id,p.criteria[2].id)
        self.assertTrue(all(c.importance==0 for c in q.criteria[2:]))
        self.assertEqual(q.groups[-1].weight,0)

    def test_reference_fingerprint_and_candidate_identity_checked(self):
        p=safety_profile(settings()); good=SafetyModule(snapshot(cctv('a')))
        class Foreign(SafetyModule):
            def run_reference(self,p,c,cancel):
                r=super().run_reference(p,c,cancel);r.observations[0].candidate_id='other';return r
        r=Orchestrator({'safety':good},reference_modules={'safety':Foreign(good.index)}).run(p,candidates())
        self.assertFalse(r['references'])
        self.assertEqual(r['events'][-2]['stage'],'reference_failed')
        self.assertFalse(SafetyModule.reference_requested(profile()))

    def test_reference_and_model_schemas_distinct_and_cancelled(self):
        i=snapshot(cctv('a')); m=SafetyModule(i); p=safety_profile(settings())
        r=m.run_reference(p,candidates(),Event())
        self.assertEqual(SafetyReferenceResult.model_validate(r.model_dump()),r)
        self.assertIn('area_code',output_schema(SafetyResearchResponse)['$defs']['AreaResearch']['required'])
        cancelled=Event();cancelled.set()
        with self.assertRaises(InterruptedError):m.run_reference(p,candidates(),cancelled)

    def test_region_targets_public_only_and_conditional(self):
        i=snapshot(cctv('a'));p=safety_profile(settings(qualitative_research=True))
        targets=i.research_targets(p,candidates())
        self.assertEqual(len(targets),1)
        self.assertEqual(set(targets[0]),{'area_code','area_name','topics'})
        self.assertNotIn('latitude',str(targets))
        self.assertEqual(i.research_targets(safety_profile(settings()),candidates()),[])
        self.assertEqual(snapshot(cctv('a'),boundary=False).research_targets(p,candidates()),[])

    def test_reference_reused_after_weight_change_without_new_research(self):
        state=AppState(index(),safety_index=snapshot(cctv('a')))
        _,session=state.session();p=safety_profile(settings())
        with patch('app.web.research_safety') as search:
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            changed=state.preferences(session,PreferenceInput(run_id=run['run_id'],group_weights={'safety':70},criterion_importance={},confirm_weights=True))
            self.assertEqual(changed['run']['references'][1]['observations'],run['references'][1]['observations'])
            self.assertEqual(changed['run']['references'][1]['profile_fingerprint'],changed['run']['profile_fingerprint'])
            self.assertEqual(search.call_count,0)

    def test_one_automatic_research_task_returns_to_comparison(self):
        runner=SimpleNamespace(last_metadata={'web_search_count':1})
        state=AppState(index(),runner_factory=lambda:runner,safety_index=snapshot(cctv('a')))
        _,session=state.session();p=safety_profile(settings(qualitative_research=True))
        with patch('app.web.research_safety',return_value={'items':[],'score_eligible':False}) as search:
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            job=session['jobs'][run['research_job']['id']]
            for _ in range(100):
                if job['status']!='running':break
                time.sleep(.005)
            self.assertEqual(job['status'],'completed');self.assertEqual(search.call_count,1)
            self.assertEqual(job['result']['safety']['items'],[])
            self.assertEqual(job['kind'],'supplement')
            state.preferences(session,PreferenceInput(run_id=run['run_id'],group_weights={'safety':20},criterion_importance={},confirm_weights=True))
            self.assertEqual(search.call_count,1)

    def test_failed_facility_research_does_not_skip_safety_or_discard_prior_success(self):
        for fail in ('facility_reviews','safety'):
            runner=SimpleNamespace(last_metadata={'web_search_count':1})
            state=AppState(index(),runner_factory=lambda:runner,safety_index=snapshot(cctv('a')))
            _,session=state.session();p=safety_profile(settings())
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            with patch('app.web.research_reviews',side_effect=RunnerError('timeout') if fail=='facility_reviews' else None,
                       return_value={'items':[{'facility_id':'test','excerpts':[]}]}), \
                 patch('app.web.research_safety',side_effect=RunnerError('timeout') if fail=='safety' else None,
                       return_value={'items':[]}) as search:
                public=state.supplement(session,run['run_id'],[{'id':'test'}],TARGET)
                job=session['jobs'][public['id']]
                for _ in range(100):
                    if job['status']!='running':break
                    time.sleep(.005)
                self.assertEqual(job['status'],'completed');self.assertEqual(search.call_count,1)
                self.assertEqual(job['result']['errors'],[{'module':fail,'code':'timeout'}])
                if fail=='safety':self.assertTrue(job['result']['items'])
                else:self.assertEqual(job['result']['safety'],{'items':[]})


class SafetyResearchTests(unittest.TestCase):
    def test_official_board_url_only_with_stable_query(self):
        self.assertEqual(official_url(article().source_url+'#content'),official_url(article().source_url))
        for url in ('http://www.jinju.go.kr/00138.web?amode=view&idx=1','https://www.jinju.go.kr.evil.com/00138.web?amode=view&idx=1',
                    'https://www.jinju.go.kr/Download.do?idx=1','https://www.jinju.go.kr/00138.web?amode=view&idx=1&idx=2',
                    'https://www.jinju.go.kr:444/00138.web?amode=view&idx=1'):
            self.assertIsNone(official_url(url))

    def test_parser_separates_nav_dates_and_regions_from_article(self):
        html='<nav>가상동 작성일 2026-01-02</nav><h2 id="sns_bbs_title">보도 제목</h2><div class="info1">작성일 2026-01-01 수정일 2026-01-03</div><div class="substanceautolink">다른동 침수 예방<br>조치</div>'
        page=parse_official_article(html)
        self.assertEqual(page.published_dates,('2026-01-01',))
        self.assertNotIn('가상동',page.text)
        self.assertEqual(page.text,'보도 제목 다른동 침수 예방 조치')
        self.assertIsNone(parse_official_article('<p>가상동 작성일 2026-01-01 침수</p>'))

    def test_verified_excerpt_is_unscored_and_prompt_contains_no_private_input(self):
        runner=RunnerFixture(article()); page=SourcePage(article().quote,(today().isoformat(),))
        result=research_safety(runner,TARGET,cancel=Event(),fetcher=lambda *_:page)
        self.assertEqual(result['items'][0]['status'],'found')
        self.assertFalse(result['items'][0]['excerpts'][0]['score_eligible'])
        self.assertTrue(runner.options['search']);self.assertFalse(runner.options['retries'])
        self.assertNotIn('latitude',runner.prompt)

    def test_wrong_region_old_unknown_date_missing_quote_topic_and_no_search_rejected(self):
        for changes,text,reason in [({},'다른동 침수 예방 사업을 진행한다.','quote_unverified'),
            ({'quote':'침수 예방 사업을 진행한다.'},'다른동 침수 예방 사업을 진행한다.','area_unverified'),
            ({'published_date':None},article().quote,'date_unknown'),
            ({'published_date':'2018-01-01'},article().quote,'outdated_or_future'),
            ({'quote':'가상동 사업을 진행한다.'},'가상동 사업을 진행한다.','topic_unverified')]:
            q=article(**changes);page=SourcePage(text,(q.published_date,) if q.published_date else ())
            r=research_safety(RunnerFixture(q),TARGET,cancel=Event(),fetcher=lambda *_:page)
            self.assertIn(reason,r['items'][0]['rejection_reasons']);self.assertFalse(r['items'][0]['excerpts'])
        r=research_safety(RunnerFixture(article(),search_count=0),TARGET,cancel=Event(),fetcher=lambda *_:None)
        self.assertIn('search_unverified',r['items'][0]['rejection_reasons'])

    def test_empty_is_unknown_cancellation_and_foreign_response_fail(self):
        result=research_safety(RunnerFixture(),TARGET,cancel=Event())
        self.assertEqual(result['items'][0]['unconfirmed_topics'],['flood'])
        self.assertEqual(result['policy']['absence_of_report'],'unknown')
        cancelled=Event();cancelled.set()
        with self.assertRaises(RunnerError):research_safety(RunnerFixture(),TARGET,cancel=cancelled)
        r=RunnerFixture();r.answer.items[0].area_code='other'
        with self.assertRaises(RunnerError):research_safety(r,TARGET,cancel=Event())


if __name__=='__main__':unittest.main()
