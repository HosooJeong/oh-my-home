import unittest
from app.contracts import InterviewTurn, output_schema
from app.intake import IntakeDraft, prepare_profile, source_segments
from app.codex_runner import CodexRunner, RunnerError
from app.modules.living import LivingModule
from app.orchestrator import Orchestrator
from test_living import index, candidates
from test_need_coverage import FakeRunner, criterion, draft, need


def row(source, field='need', ids=('grocery',), **changes):
    return need(source=source, ids=ids, **changes) | {'field': field}


class SourceBindingTests(unittest.TestCase):
    request=('마트가 가까운 곳이 좋아. 직선거리 500m 이내가 좋고 2000m 이상은 불편해. '
             '편의점도 가까운 곳이 좋아. 직선거리 200m 이내가 좋고 1000m 이상은 불편해. '
             '마트 70%, 편의점 30%로 보고 싶어.')

    def response(self, **changes):
        criteria=[criterion(importance=70.0,utility=dict(direction='lower',ideal=500.0,limit=2000.0,unit='m')),
                  criterion('convenience','convenience_straight_line_distance_m',source='s3',importance=30.0,
                            utility=dict(direction='lower',ideal=200.0,limit=1000.0,unit='m'))]
        rows=[row('s1'),row('s2','utility'),row('s3',ids=('convenience',)),
              row('s4','utility',ids=('convenience',)),row('s5','importance',ids=('grocery','convenience'),aspect='other')]
        return draft(**(dict(criteria=criteria,needs=rows)|changes))

    def test_split_target_distance_and_weight_are_preserved_as_field_sources(self):
        p=prepare_profile(FakeRunner(self.response()),self.request)
        self.assertEqual(p.questions,[])
        self.assertEqual([c.importance for c in p.criteria],[70,30])
        self.assertEqual(len(p.criteria),2)
        self.assertEqual({b.field for b in p.criteria[0].source_evidence},{'need','utility','importance'})
        self.assertEqual(next(b for b in p.criteria[0].source_evidence if b.field=='utility').quotes,
                         ['직선거리 500m 이내가 좋고 2000m 이상은 불편해.'])

    def test_two_condition_ratio_follows_original_named_order(self):
        request=self.request.replace('마트 70%, 편의점 30%로 보고 싶어.','두 조건의 중요도는 70:30이야.')
        p=prepare_profile(FakeRunner(self.response()),request)
        self.assertEqual(p.questions,[])
        self.assertEqual([c.importance for c in p.criteria],[70,30])

    def test_swapped_explicit_weights_cannot_complete_comparison(self):
        d=self.response().model_dump();d['criteria'][0]['importance']=30.0;d['criteria'][1]['importance']=70.0
        p=prepare_profile(FakeRunner(IntakeDraft.model_validate(d)),self.request)
        self.assertTrue(p.questions[0].blocking)
        self.assertEqual(Orchestrator({'living':LivingModule(index())}).run(p,candidates())['status'],'awaiting_input')

    def test_fabricated_distance_is_not_accepted_as_a_user_criterion(self):
        d=self.response().model_dump();d['criteria'][0]['utility']['limit']=9999.0
        runner=FakeRunner(IntakeDraft.model_validate(d));p=prepare_profile(runner,self.request)
        self.assertTrue(p.questions[0].blocking)
        self.assertTrue(any(i['field']=='utility' for i in runner.last_metadata['need_review']['field_binding_issues']))

    def test_a_different_facility_with_same_numbers_cannot_supply_distance(self):
        request=self.request.replace('직선거리 500m 이내가 좋고 2000m 이상은 불편해.',
                                     '학교까지 직선거리 500m 이내가 좋고 2000m 이상은 불편해.')
        p=prepare_profile(FakeRunner(self.response()),request)
        self.assertTrue(p.questions[0].blocking)
        self.assertIn('학교',p.questions[0].text)

    def test_a_real_resolution_id_does_not_launder_an_unrelated_need(self):
        request=self.request+' 가족 모임 공간이 필요해.'
        d=self.response().model_dump();d['needs'].append(row('s6',resolution='s1',aspect='other'))
        p=prepare_profile(FakeRunner(IntakeDraft.model_validate(d)),request)
        self.assertTrue(p.questions[0].blocking)
        self.assertIn('가족 모임',p.questions[0].text)

    def test_repeated_housing_reference_instruction_preserves_both_sources(self):
        request=('아파트 전세 실거래가를 참고하고 싶어요. '
                 '집·비용은 실거래 참고만 필요하고 가격 점수/실제 매물 추천은 제외해 줘.')
        response=draft(groups=[dict(id='housing',weight=0.0,source='user')],criteria=[],
            context=[dict(key='housing_reference',value='requested',source_id='s1')],
            needs=[row('s1','context',ids=(),group='housing',keys=('housing_reference',),handling='reference'),
                   row('s2','context',ids=(),group='housing',keys=('housing_reference',),handling='reference')])
        p=prepare_profile(FakeRunner(response),request)
        self.assertFalse(p.questions)
        self.assertEqual(p.context[0].source_quotes,list(source_segments([request]).values()))

    def test_unrelated_context_cannot_use_housing_reference_exception(self):
        request='아파트 전세 실거래가를 참고하고 싶어요. 산책 공원도 필요해요.'
        response=draft(groups=[dict(id='housing',weight=0.0,source='user')],criteria=[],
            context=[dict(key='housing_reference',value='requested',source_id='s1')],
            needs=[row('s1','context',ids=(),group='housing',keys=('housing_reference',),handling='reference'),
                   row('s2','context',ids=(),group='housing',keys=('housing_reference',),handling='background')])
        p=prepare_profile(FakeRunner(response),request)
        self.assertTrue(p.questions)
        self.assertIn('산책 공원',p.questions[0].text)

    def test_a_bare_distance_does_not_cross_a_category_heading(self):
        request='마트가 가까운 곳이 좋아. 교육·육아: 중요도 60, 상대 비중 50%. 직선거리 500m 이내가 좋고 2000m 이상은 불편해.'
        d=draft(criteria=[criterion(importance_source='proposed',utility=dict(direction='lower',ideal=500.0,limit=2000.0,unit='m'))],
                needs=[row('s1'),row('s3','utility')])
        p=prepare_profile(FakeRunner(d),request)
        self.assertTrue(p.questions[0].blocking)

    def test_hard_limit_needs_an_explicit_mandatory_clause(self):
        request='마트 직선거리 100m 이내가 좋고 2000m 이상은 불편해. 마트는 700m 이내면 좋아.'
        d=draft(criteria=[criterion(importance_source='proposed',utility=dict(direction='lower',ideal=100.0,limit=2000.0,unit='m'),
                                   hard=dict(operator='lte',value=700.0))],needs=[row('s1'),row('s2','hard')])
        p=prepare_profile(FakeRunner(d),request)
        self.assertTrue(p.questions[0].blocking)
        good=request.replace('이내면 좋아','이내는 필수야')
        self.assertEqual(prepare_profile(FakeRunner(d),good).questions,[])

    def test_kilometers_can_ground_a_distance_in_meters(self):
        request='마트까지 직선거리 0.5km 이내가 좋고 2km 이상은 불편해.'
        d=draft(criteria=[criterion(importance_source='proposed',utility=dict(direction='lower',ideal=500.0,limit=2000.0,unit='m'))],
                needs=[row('s1')])
        self.assertEqual(prepare_profile(FakeRunner(d),request).questions,[])

    def test_any_park_type_is_a_parameter_not_a_zero_weight_exclusion(self):
        request='공원까지 직선거리 300m 이내가 좋고 1500m 이상은 불편해. 공원 유형은 상관없어.'
        d=draft(groups=[dict(id='leisure',weight=60.0,source='user')],
                criteria=[criterion('park','park_straight_line_distance_m','leisure',importance_source='proposed',
                                    utility=dict(direction='lower',ideal=300.0,limit=1500.0,unit='m'),
                                    parameters=[dict(key='park_type',value='any')])],
                needs=[row('s1',ids=('park',),group='leisure'),row('s2','parameters',ids=('park',),aspect='other',group='leisure')])
        p=prepare_profile(FakeRunner(d),request)
        self.assertEqual(p.questions,[]);self.assertEqual(len(p.criteria),1)
        self.assertGreater(p.criteria[0].importance,0)

    def test_interview_can_supply_only_the_missing_curve_limit(self):
        request='마트까지 직선거리 500m 이내가 좋아.'
        first=draft(criteria=[criterion(importance_source='proposed',utility=None)],needs=[row('s1')],
                    questions=[dict(id='limit',text='불편하다고 보는 최대 직선거리는?',reason='점수 기준 확인',
                                    criterion_ids=['grocery'],blocking=False)])
        p=prepare_profile(FakeRunner(first),request)
        response=draft(criteria=[criterion(importance_source='proposed',utility=dict(direction='lower',ideal=500.0,limit=2000.0,unit='m'))],
                       needs=[row('s1'),row('s1','utility'),row('s2','utility')])
        q=prepare_profile(FakeRunner(response),request,[InterviewTurn(question_id='limit',answer='2000m 이상이면 불편해.')],p)
        self.assertEqual(q.questions,[]);self.assertEqual(q.criteria[0].id,'grocery')
        quotes=next(b.quotes for b in q.criteria[0].source_evidence if b.field=='utility')
        self.assertIn(request,quotes);self.assertIn('2000m 이상이면 불편해.',quotes)

    def test_native_output_schema_requires_the_field_role(self):
        schema=output_schema(IntakeDraft)
        self.assertIn('field',schema['$defs']['IntakeNeed']['required'])

    def test_fresh_native_response_cannot_silently_fall_back_to_v2(self):
        class NativeStandIn(FakeRunner,CodexRunner):pass
        with self.assertRaisesRegex(RunnerError,'invalid_intake_contract'):
            prepare_profile(NativeStandIn(draft()),'마트가 가까운 곳이 좋아.')

    def test_shared_sentence_does_not_supply_another_facilitys_target(self):
        request='마트 500m와 편의점 200m 이내가 좋아. 마트 2000m와 편의점 1000m 이상이면 불편해. 마트 70%, 편의점 30%로 보고 싶어.'
        d=self.response().model_dump()
        for c in d['criteria']:c['source_id']='s1'
        d['criteria'][0]['utility']['ideal']=200.0
        d['needs']=[row('s1',ids=('grocery','convenience')),row('s2','utility',ids=('grocery','convenience')),
                    row('s3','importance',ids=('grocery','convenience'),aspect='other')]
        p=prepare_profile(FakeRunner(IntakeDraft.model_validate(d)),request)
        self.assertTrue(p.questions[0].blocking)

    def test_ratio_order_is_original_word_order_even_if_model_reorders_criteria(self):
        request='마트와 편의점이 가까운 곳이 좋아. 마트 직선거리 500m 이내가 좋고 2000m 이상은 불편해. 편의점 직선거리 200m 이내가 좋고 1000m 이상은 불편해. 두 조건의 중요도는 70:30이야.'
        d=self.response().model_dump();d['criteria'].reverse()
        for c in d['criteria']:c['source_id']='s1'
        d['needs']=[row('s1',ids=('grocery','convenience')),row('s2','utility'),
                    row('s3','utility',ids=('convenience',)),row('s4','importance',ids=('grocery','convenience'),aspect='other')]
        p=prepare_profile(FakeRunner(IntakeDraft.model_validate(d)),request)
        self.assertEqual(p.questions,[])
        self.assertEqual({c.id:c.importance for c in p.criteria},{'grocery':70,'convenience':30})

    def test_a_distance_number_is_not_an_explicit_percentage(self):
        request='마트까지 직선거리 100m 이내가 좋고 2000m 이상은 불편해.'
        d=draft(criteria=[criterion(utility=dict(direction='lower',ideal=100.0,limit=2000.0,unit='m'))],needs=[row('s1')])
        p=prepare_profile(FakeRunner(d),request)
        self.assertTrue(p.questions[0].blocking)

    def test_school_level_cannot_change_from_elementary_to_high(self):
        request='초등학교까지 직선거리 500m 이내가 좋고 1500m 이상은 불편해.'
        d=draft(groups=[dict(id='education',weight=60.0,source='user')],
                criteria=[criterion('school','school_straight_line_distance_m','education',importance_source='proposed',
                    utility=dict(direction='lower',ideal=500.0,limit=1500.0,unit='m'),
                    parameters=[dict(key='school_level',value='high')])],needs=[row('s1',ids=('school',),group='education')])
        p=prepare_profile(FakeRunner(d),request)
        self.assertTrue(p.questions[0].blocking)


if __name__=='__main__':unittest.main()
