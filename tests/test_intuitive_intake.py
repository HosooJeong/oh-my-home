import unittest
from pydantic import ValidationError
from app.contracts import InterviewTurn, Question
from app.intake import prepare_profile
from test_need_coverage import FakeRunner, criterion, draft, need


def row(source='s1', field='need', ids=('grocery',), **changes):
    return need(source=source, ids=ids, **changes) | {'field': field}


class IntuitiveIntakeTests(unittest.TestCase):
    def living(self):
        return draft(criteria=[
            criterion(need='마트는 조금 멀어도 괜찮아요', importance=30.0, importance_source='proposed', utility=None),
            criterion('convenience','convenience_straight_line_distance_m', need='편의점 가까움이 더 중요해요',
                      importance=70.0, importance_source='proposed', utility=None)],
            needs=[row(ids=('grocery','convenience')), row(field='importance',ids=('grocery','convenience'),aspect='other')])

    def test_qualitative_preferences_do_not_require_numeric_answers_or_become_filters(self):
        request='편의점이 가까운 게 더 중요하고, 마트는 조금 멀어도 괜찮아요.'
        runner=FakeRunner(self.living());p=prepare_profile(runner,request)
        self.assertEqual(p.questions,[])
        self.assertEqual([c.importance for c in p.criteria],[30,70])
        self.assertTrue(all(c.importance_source=='proposed' and c.hard is None for c in p.criteria))
        self.assertTrue(all(c.comparison_proposal for c in p.criteria))
        self.assertEqual(p.criteria[0].utility.limit,2500)
        self.assertEqual(p.criteria[1].utility.limit,1500)
        self.assertTrue(all(c.source_quote==request for c in p.criteria))

    def test_shared_equal_preference_clause_keeps_both_original_sources(self):
        request='마트와 편의점이 가까우면 좋겠어요. 두 곳의 접근성을 비슷하게 중요하게 생각해요.'
        response=self.living().model_dump()
        for c in response['criteria']:
            c['importance']=50.0
        response['needs'][1]['source_id']='s2'
        p=prepare_profile(FakeRunner(type(self.living()).model_validate(response)),request)
        self.assertEqual(p.questions,[])
        self.assertTrue(all(any('두 곳' in q for b in c.source_evidence for q in b.quotes) for c in p.criteria))

    def test_very_close_preference_is_a_reviewable_soft_proposal(self):
        request='편의점이 집 코앞에 있으면 좋겠어요.'
        c=criterion('convenience','convenience_straight_line_distance_m',
                    need=request, importance_source='proposed',utility=None)
        p=prepare_profile(FakeRunner(draft(criteria=[c],needs=[row(ids=('convenience',))])),request)
        self.assertEqual(p.questions,[])
        self.assertEqual((p.criteria[0].utility.ideal,p.criteria[0].utility.limit),(100,800))
        self.assertEqual(p.criteria[0].comparison_proposal.label,'집 바로 가까이에 있으면 좋아요')
        self.assertIsNone(p.criteria[0].hard)
        self.assertEqual(p.criteria[0].source_quote,request)

    def test_shared_quote_does_not_spread_strong_preference_to_other_facility(self):
        request='편의점이 집 코앞이면 좋겠어요. 마트는 조금 멀어도 괜찮아요.'
        response=self.living().model_dump()
        response['criteria'][1]['need']='편의점이 집 코앞이면 좋겠어요'
        p=prepare_profile(FakeRunner(type(self.living()).model_validate(response)),request)
        self.assertEqual([(c.utility.ideal,c.utility.limit) for c in p.criteria],[(600,2500),(100,800)])

    def test_model_cannot_intensify_an_ordinary_nearby_preference(self):
        request='편의점이 가까우면 좋겠어요.'
        c=criterion('convenience','convenience_straight_line_distance_m',
                    need='편의점이 집 코앞이면 좋아요',importance_source='proposed',utility=None)
        p=prepare_profile(FakeRunner(draft(criteria=[c],needs=[row(ids=('convenience',))])),request)
        self.assertEqual((p.criteria[0].utility.ideal,p.criteria[0].utility.limit),(300,1500))

    def test_original_strong_preference_survives_a_short_model_paraphrase(self):
        request='편의점이 집 코앞에 있으면 좋겠어요.'
        c=criterion('convenience','convenience_straight_line_distance_m',
                    need='편의점 접근성',importance_source='proposed',utility=None)
        p=prepare_profile(FakeRunner(draft(criteria=[c],needs=[row(ids=('convenience',))])),request)
        self.assertEqual((p.criteria[0].utility.ideal,p.criteria[0].utility.limit),(100,800))

    def test_another_facilitys_strong_preference_cannot_intensify_this_scale(self):
        request='마트는 가까우면 좋고, 편의점은 집 코앞이면 좋겠어요.'
        response=self.living().model_dump()
        response['criteria'][0]['need']='마트 접근성'
        response['criteria'][1]['need']='편의점 접근성'
        p=prepare_profile(FakeRunner(type(self.living()).model_validate(response)),request)
        self.assertEqual([(c.utility.ideal,c.utility.limit) for c in p.criteria],[(300,1500),(100,800)])

    def test_two_named_facilities_can_share_one_strong_preference(self):
        request='마트와 편의점이 집 코앞이면 좋겠어요.'
        response=self.living().model_dump()
        response['criteria'][0]['need']='마트 접근성'
        response['criteria'][1]['need']='편의점 접근성'
        p=prepare_profile(FakeRunner(type(self.living()).model_validate(response)),request)
        self.assertEqual([(c.utility.ideal,c.utility.limit) for c in p.criteria],[(100,800),(100,800)])

    def test_not_needing_a_store_at_the_door_does_not_select_strong_scale(self):
        request='편의점이 집 코앞은 아니어도 괜찮아요.'
        c=criterion('convenience','convenience_straight_line_distance_m',
                    need=request,importance_source='proposed',utility=None)
        p=prepare_profile(FakeRunner(draft(criteria=[c],needs=[row(ids=('convenience',))])),request)
        self.assertEqual((p.criteria[0].utility.ideal,p.criteria[0].utility.limit),(300,1500))

    def test_explicit_distances_and_hard_limits_are_not_replaced_by_proposals(self):
        request='마트 직선거리 100m가 좋고 2000m면 만족도 0이에요. 700m 이내는 필수예요.'
        c=criterion(importance_source='proposed',utility=dict(direction='lower',ideal=100.0,limit=2000.0,unit='m'),
                    hard=dict(operator='lte',value=700.0))
        p=prepare_profile(FakeRunner(draft(criteria=[c],needs=[row(),row('s2','hard')])),request)
        self.assertEqual(p.questions,[])
        self.assertEqual(p.criteria[0].hard.value,700)
        self.assertIsNone(p.criteria[0].comparison_proposal)

    def test_academy_question_only_needs_school_level_and_clickable_answer(self):
        request='수학 학원 선택지가 다양하면 좋겠어요.'
        c=criterion('math','academy_count_within_radius',group='education',need='수학 학원 선택지',
                    importance_source='proposed',utility=None,parameters=[dict(key='subject',value='math')])
        question=dict(id='level',text='어느 학교급의 학원을 찾으세요?',reason='대상 확인',criterion_ids=['math'],
                      blocking=True,choices=['초등학생 대상이에요.','중학생 대상이에요.','고등학생 대상이에요.'])
        p=prepare_profile(FakeRunner(draft(groups=[dict(id='education',weight=100.0,source='user')],
            criteria=[c],questions=[question],needs=[row(ids=('math',),group='education',aspect='facility_count')])),request)
        self.assertEqual(p.questions[0].choices[0],'초등학생 대상이에요.')
        self.assertEqual(p.criteria[0].parameters['radius_m'],'1500')
        self.assertEqual(p.criteria[0].utility.ideal,3)
        c['utility']=p.criteria[0].utility.model_dump()
        c['parameters'] += [dict(key='radius_m',value='1500'),dict(key='school_level',value='elementary')]
        answer=InterviewTurn(question_id='level',answer='초등학생 대상이에요.')
        q=prepare_profile(FakeRunner(draft(groups=[dict(id='education',weight=100.0,source='user')],criteria=[c],
            needs=[row(ids=('math',),group='education',aspect='facility_count'),
                   row('s2','parameters',ids=('math',),group='education',aspect='facility_count')])),request,[answer],p)
        self.assertEqual(q.questions,[])
        self.assertEqual(q.criteria[0].parameters['school_level'],'elementary')
        self.assertTrue(q.criteria[0].comparison_proposal)

    def test_fabricated_model_distances_still_trigger_review(self):
        request='마트가 가까우면 좋겠어요.'
        response=draft(criteria=[criterion(importance_source='proposed')],needs=[row()])
        p=prepare_profile(FakeRunner(response),request)
        self.assertTrue(p.questions[0].blocking)
        self.assertIsNone(p.criteria[0].comparison_proposal)

    def test_proposal_is_not_reclassified_as_a_user_numeric_answer_on_next_turn(self):
        request='편의점이 가까운 게 더 중요하고, 마트는 조금 멀어도 괜찮아요.'
        p=prepare_profile(FakeRunner(self.living()),request)
        for c in p.criteria:
            c.importance_source='user'  # The review button approved the proposed weights.
        p.questions.append(Question(id='note',text='다른 생활 조건이 있으세요?',reason='추가 조건',criterion_ids=[],blocking=False))
        response=self.living().model_dump()
        for c,old in zip(response['criteria'],p.criteria):
            c['utility']=old.utility.model_dump()
            c['importance_source']='user'
        response['context']=[dict(key='no_additions',value='추가 없음',source_id='s2')]
        response['needs'].append(row('s2','context',ids=(),group=None,aspect='other',handling='background',keys=('no_additions',)))
        q=prepare_profile(FakeRunner(type(self.living()).model_validate(response)),request,
                          [InterviewTurn(question_id='note',answer='추가 조건은 없어요.')],p)
        self.assertEqual(q.questions,[])
        self.assertTrue(all(c.comparison_proposal for c in q.criteria))
        self.assertTrue(all(c.importance_source=='proposed' for c in q.criteria))

    def test_choices_are_bounded_and_legacy_questions_still_parse(self):
        q=dict(id='q',text='학교급을 알려주세요.',reason='대상 확인',criterion_ids=[],blocking=True)
        self.assertEqual(Question(**q).choices,[])
        with self.assertRaises(ValidationError):Question(**q,choices=['a','b','c','d'])

    def test_reviewed_qualitative_weights_allow_ranking_with_verified_data(self):
        from app.orchestrator import Orchestrator
        from app.modules.living import LivingModule
        from test_living import index, candidates
        p=prepare_profile(FakeRunner(self.living()),'편의점이 가까운 게 더 중요하고, 마트는 조금 멀어도 괜찮아요.')
        for c in p.criteria:
            c.source='user'
            c.importance_source='user'
        result=Orchestrator({'living':LivingModule(index())}).run(p,candidates())
        self.assertEqual(result['report']['ranking_status'],'available')
        self.assertTrue(all(c.importance_proposal is not None for c in p.criteria))

    def test_explicit_answer_equal_to_an_old_proposal_keeps_user_numbers(self):
        request='마트가 가까우면 좋겠어요.'
        p=prepare_profile(FakeRunner(draft(criteria=[criterion(importance_source='proposed',utility=None)],needs=[row()])),request)
        p.questions=[Question(id='extra',text='추가로 정할 조건이 있으세요?',reason='추가',criterion_ids=['grocery'],blocking=False)]
        response=draft(criteria=[criterion(importance_source='proposed',utility=p.criteria[0].utility.model_dump())],
                       needs=[row(),row('s2','utility')])
        q=prepare_profile(FakeRunner(response),request,[InterviewTurn(question_id='extra',
            answer='마트의 직선거리 300m가 좋고 1500m면 만족도 0이에요.')],p)
        self.assertEqual(q.questions,[])
        self.assertEqual(q.criteria[0].utility.limit,1500)
        self.assertIsNone(q.criteria[0].comparison_proposal)

    def test_user_academy_radius_is_kept_with_a_proposed_count_scale(self):
        request='초등 수학 학원을 직선반경 800m에서 비교해 주세요.'
        c=criterion('math','academy_count_within_radius',group='education',importance_source='proposed',utility=None,
                    parameters=[dict(key='school_level',value='elementary'),dict(key='subject',value='math'),dict(key='radius_m',value='800')])
        p=prepare_profile(FakeRunner(draft(groups=[dict(id='education',weight=100.0,source='user')],criteria=[c],
              needs=[row(ids=('math',),group='education',aspect='facility_count')])),request)
        self.assertEqual(p.questions,[])
        self.assertEqual(p.criteria[0].parameters['radius_m'],'800')
        self.assertIsNone(p.criteria[0].comparison_proposal.radius_m)

    def test_walking_route_and_safety_are_not_scored_with_distance_defaults(self):
        request='실제 도보 경로를 비교해 주세요.'
        c=criterion('walk','walking_route_unverified',group='transport',importance_source='proposed',utility=None)
        p=prepare_profile(FakeRunner(draft(groups=[dict(id='transport',weight=100.0,source='user')],criteria=[c],
                  needs=[row(ids=('walk',),group='transport',aspect='walking_route')])),request)
        self.assertIsNone(p.criteria[0].utility)
        self.assertIsNone(p.criteria[0].comparison_proposal)


if __name__=='__main__':unittest.main()
