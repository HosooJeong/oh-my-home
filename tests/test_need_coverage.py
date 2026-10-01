import unittest
from app.contracts import InterviewTurn, NeedProfile
from app.codex_runner import RunnerError
from app.intake import IntakeDraft, prepare_profile, source_segments
from app.need_coverage import required_sources
from app.modules.living import LivingModule
from app.modules.transport import TransportModule
from app.orchestrator import Orchestrator
from test_living import index, candidates
from test_transport import stops, stop


def need(aspect='straight_distance', handling='compare', ids=('grocery',), source='s1', group='living', keys=(), resolution=None):
    return dict(source_id=source,group_id=group,aspect=aspect,handling=handling,
                criterion_ids=list(ids),context_keys=list(keys),resolution_source_id=resolution)


def criterion(id='grocery',metric='grocery_straight_line_distance_m',group='living',source='s1',**changes):
    return dict(id=id,group_id=group,label='거리 조건',need='직선거리',source_id=source,source='user',
        importance=100.0,importance_source='user',metric=metric,
        utility=dict(direction='lower',ideal=0.0,limit=1500.0,unit='m'),hard=None,parameters=[])|changes


def draft(**changes):
    return IntakeDraft.model_validate(dict(groups=[dict(id='living',weight=100.0,source='user')],
        criteria=[criterion()],context=[],questions=[],needs=[need()])|changes)


class FakeRunner:
    def __init__(self,answer):self.answer=answer;self.last_metadata={};self.calls=0
    def run(self,prompt,response_type,**kw):
        self.calls+=1;self.prompt=prompt
        assert response_type is IntakeDraft and not kw['search']
        return self.answer


class NeedCoverageTests(unittest.TestCase):
    large='큰 마트에서 대량 장보기 하고 싶어. 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'

    def test_collapsed_large_store_is_restored_and_full_rank_is_withheld(self):
        # Both sentences share the same genuine source quote; that alone must not imply coverage.
        request=self.large.replace('. ', ', ')
        runner=FakeRunner(draft());p=prepare_profile(runner,request)
        unknown=next(c for c in p.criteria if c.metric=='need_facility_fit_unverified')
        self.assertEqual(unknown.need,request);self.assertIsNone(unknown.utility)
        self.assertEqual(unknown.importance_source,'proposed');self.assertEqual(runner.calls,1)
        r=Orchestrator({'living':LivingModule(index())}).run(p,candidates())
        self.assertEqual(r['report']['ranking_status'],'withheld')
        self.assertTrue(all(0<a['coverage']<1 and a['score'] is None for a in r['report']['assessments']))
        self.assertEqual(runner.last_metadata['need_review']['restored_count'],1)

    def test_a_context_only_comparison_is_not_treated_as_background(self):
        request='큰 마트에서 대량 장보기 하고 싶어, 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        p=prepare_profile(FakeRunner(draft(context=[dict(key='store_style',value='대량 장보기',source_id='s1')],
            needs=[need(),need('facility_fit','background',ids=(),keys=('store_style',))])),request)
        self.assertTrue(any(c.metric=='need_facility_fit_unverified' for c in p.criteria))

    def test_a_complete_supported_and_unsupported_mapping_is_not_duplicated(self):
        request='큰 마트에서 대량 장보기 하고 싶어, 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        runner=FakeRunner(draft(criteria=[criterion(),criterion('size','store_size_unverified',need='큰 마트에서 대량 장보기',utility=None)],
            needs=[need(),need('facility_fit',ids=('size',))]))
        p=prepare_profile(runner,request)
        self.assertEqual([c.id for c in p.criteria],['grocery','size'])
        self.assertEqual(runner.last_metadata['need_review']['restored_count'],0)

    def test_stop_distance_never_covers_mandatory_commute_and_transfer(self):
        request='통근은 30분 이내이고 환승은 1회 이하여야 하는 필수조건이야, 정류장 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        runner=FakeRunner(draft(groups=[dict(id='transport',weight=100.0,source='user')],
            criteria=[criterion('bus','bus_stop_straight_line_distance_m','transport')],
            needs=[need(ids=('bus',),group='transport')]))
        p=prepare_profile(runner,request)
        restored=[c for c in p.criteria if c.metric.startswith('need_')]
        self.assertEqual({c.metric for c in restored},{'need_travel_time_unverified','need_transfer_unverified'})
        self.assertTrue(all(c.need==request and c.hard and c.utility.unit=='bool' for c in restored))
        r=Orchestrator({'transport':TransportModule(stops([stop()]))}).run(p,candidates())
        self.assertTrue(all(a['eligibility']=='unverified' for a in r['report']['assessments']))
        self.assertEqual(r['report']['ranking_status'],'withheld')

    def test_a_research_request_is_preserved_without_an_invented_score(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야. 큰 마트의 규모와 일부 이용 평가를 인용해 줘.'
        p=prepare_profile(FakeRunner(draft(context=[dict(key='qualitative_research_requested',value='requested',source_id='s2')],
            needs=[need(),need('facility_fit','research',ids=(),keys=('qualitative_research_requested',),source='s2')])),request)
        self.assertEqual(len(p.criteria),1);self.assertEqual(p.context[0].value,'requested')

    def test_an_unknown_preference_does_not_drop_an_explicit_hard_requirement(self):
        request='통근 30분 이내는 필수조건이야.'
        p=prepare_profile(FakeRunner(draft(groups=[dict(id='transport',weight=100.0,source='user')],
            criteria=[criterion('commute','commute_unverified','transport',utility=None)],
            needs=[need('travel_time',ids=('commute',),group='transport')])),request)
        restored=next(c for c in p.criteria if c.metric=='need_travel_time_unverified')
        self.assertEqual(restored.need,request);self.assertEqual(restored.hard.value,1)

    def test_mandatory_citation_is_still_research_not_a_hard_scored_need(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야. 큰 마트의 이용 후기를 반드시 인용해 줘.'
        p=prepare_profile(FakeRunner(draft(context=[dict(key='qualitative_research_requested',value='requested',source_id='s2')],
            needs=[need(),need('facility_fit','research',ids=(),keys=('qualitative_research_requested',),source='s2')])),request)
        self.assertEqual(len(p.criteria),1);self.assertIsNone(p.criteria[0].hard)

    def test_clarify_without_a_model_question_still_requests_an_answer(self):
        request='가족 모임 공간의 대관 조건이 중요해.'
        p=prepare_profile(FakeRunner(draft(needs=[need('other','clarify')])),request)
        self.assertTrue(p.questions[-1].blocking)
        self.assertIn(request,p.questions[-1].text)
        self.assertIn('grocery',p.questions[-1].criterion_ids)

    def test_background_does_not_become_a_scored_preference(self):
        request='나는 큰 마트 직원이야. 마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        p=prepare_profile(FakeRunner(draft(criteria=[criterion(source='s2')],
            context=[dict(key='occupation',value='마트 직원',source_id='s1')],
            needs=[need(source='s2'),need('facility_fit','background',ids=(),group=None,keys=('occupation',))])),request)
        self.assertEqual(len(p.criteria),1)

    def test_missing_coverage_asks_a_short_question_and_blocks_false_completion(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        p=prepare_profile(FakeRunner(draft(needs=[])),request)
        self.assertTrue(p.questions[0].blocking)
        self.assertEqual(p.context[-1].value,request)
        r=Orchestrator({'living':LivingModule(index())}).run(p,candidates())
        self.assertEqual(r['status'],'awaiting_input');self.assertIsNone(r['report'])

    def test_an_unlisted_need_cannot_hide_in_a_supported_distance_metric(self):
        request='가족 모임 공간의 대관 조건이 중요해.'
        p=prepare_profile(FakeRunner(draft(needs=[need('other')])),request)
        self.assertTrue(any(c.metric=='need_other_unverified' and c.need==request for c in p.criteria))

    def test_repeated_incomplete_interview_retains_one_stable_blocking_question(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        p=prepare_profile(FakeRunner(draft(needs=[])),request)
        answer=InterviewTurn(question_id=p.questions[0].id,answer='마트 직선거리를 비교해 줘.')
        q=prepare_profile(FakeRunner(draft(needs=[],questions=[x.model_dump() for x in p.questions])),request,[answer],p)
        self.assertEqual([x.id for x in q.questions],['need_coverage_review'])
        self.assertTrue(q.questions[0].blocking)
        self.assertEqual(q.context[-1].value,answer.answer)

    def test_foreign_sources_contexts_and_criteria_are_rejected(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        for n in (need(source='s9'),need(ids=('missing',)),need('facility_fit','research',ids=(),keys=('fake',))):
            with self.subTest(n=n),self.assertRaisesRegex(RunnerError,'invalid_need_coverage_reference'):
                prepare_profile(FakeRunner(draft(needs=[n])),request)

    def test_a_real_but_unrelated_source_does_not_cover_another_request(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야. 가족 모임 공간이 필요해.'
        with self.assertRaisesRegex(RunnerError,'unrelated_need_coverage'):
            prepare_profile(FakeRunner(draft(needs=[need(),need('other',source='s2')])),request)

    def test_a_real_but_unrelated_context_is_not_a_research_mapping(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야. 큰 마트 후기를 인용해 줘.'
        with self.assertRaisesRegex(RunnerError,'unrelated_need_coverage'):
            prepare_profile(FakeRunner(draft(context=[dict(key='qualitative_research_requested',value='requested',source_id='s1')],
                needs=[need(),need('facility_fit','research',ids=(),keys=('qualitative_research_requested',),source='s2')])),request)

    def test_unconfirmed_exclusion_is_rejected_and_explicit_exclusion_is_kept(self):
        c=criterion('size','store_size_unverified',importance=0.0,utility=None)
        for request,allowed in [('큰 마트에서 대량 장보기 하고 싶어.',False),('큰 마트는 필요 없어서 제외해.',True)]:
            runner=FakeRunner(draft(criteria=[criterion(),c],needs=[need(),need('facility_fit','excluded',ids=('size',))]))
            if allowed:
                p=prepare_profile(runner,request);self.assertFalse(any(x.metric.startswith('need_') for x in p.criteria))
            else:
                with self.assertRaisesRegex(RunnerError,'unconfirmed_need_exclusion'):prepare_profile(runner,request)

    def test_interview_resolution_keeps_ids_and_does_not_repeat_answered_questions(self):
        request='마트의 직선거리 0m가 이상적이고 1500m면 만족도 0이야.'
        p=prepare_profile(FakeRunner(draft(needs=[])),request)
        answer=InterviewTurn(question_id=p.questions[0].id,answer='명시한 마트 직선거리만 비교해 줘.')
        q=prepare_profile(FakeRunner(draft(needs=[need(),need(source='s2',resolution='s1')])),request,[answer],p)
        self.assertEqual(q.criteria[0].id,p.criteria[0].id);self.assertEqual(q.questions,[])

    def test_navigation_scaffolding_does_not_hide_natural_language_after_it(self):
        request='진주 주거 생활권을 내 조건으로 검토해 줘.\n생활·건강: 중요도 100, 상대 비중 100%. 큰 마트에서 대량 장보기 하고 싶어.'
        sources=source_segments([request]);required=required_sources(sources)
        self.assertEqual([sources[id] for id in required],['큰 마트에서 대량 장보기 하고 싶어.'])

    def test_interview_can_explicitly_exclude_a_restored_need_without_recreating_it(self):
        request=self.large.replace('. ', ', ')
        p=prepare_profile(FakeRunner(draft(needs=[])),request)
        size=next(c for c in p.criteria if c.metric=='need_facility_fit_unverified')
        self.assertIn('grocery',p.questions[0].criterion_ids)
        answer=InterviewTurn(question_id=p.questions[0].id,
            answer='큰 마트 조건은 필요 없어서 제외하고, 명시한 마트 직선거리만 비교해 줘.')
        response=draft(criteria=[criterion(),criterion(size.id,size.metric,importance=0.0,utility=None)],
            context=[dict(key='exclusion_note',value=answer.answer,source_id='s2')],
            needs=[need(),need('facility_fit','excluded',ids=(size.id,),resolution='s2'),
                   need('other','background',ids=(),source='s2',group=None,keys=('exclusion_note',))])
        q=prepare_profile(FakeRunner(response),request,[answer],p)
        self.assertEqual({c.id for c in q.criteria},{c.id for c in p.criteria})
        self.assertEqual(next(c for c in q.criteria if c.id==size.id).importance,0)
        self.assertEqual(q.questions,[])


if __name__=='__main__':unittest.main()
