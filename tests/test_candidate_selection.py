"""R5: no unsupported recommendation, measured zero differs from no evidence."""
import unittest

from app.candidates import GenerationInput
from app.contracts import Candidate, NeedProfile
from app.orchestrator import Orchestrator
from app.modules.living import LivingModule
from app.web import AppState, CompareInput
from test_candidates import pool, orchestrator
from test_living import index, profile


def unknown_profile(topic='noise', mixed=False):
    p=profile(50,50) if mixed else profile(100,0)
    c=p.criteria[1 if mixed else 0]
    c.module_id='safety';c.metric=topic+'_unverified';c.label={'noise':'주변 소음','flood':'침수','night':'야간 보행'}[topic]
    c.need=c.label+'을 확인하고 싶어.'
    return NeedProfile.model_validate(p.model_dump())


class SelectionTests(unittest.TestCase):
    def generate(self,p,**kw):
        return pool().generate(GenerationInput(profile=p,mode='exploratory',separation_m=0.0),
                               kw.get('orchestrator',orchestrator()))

    def test_unsupported_only_topics_return_scope_question_without_same_three_points(self):
        for topic in ('noise','flood','night'):
            p=unknown_profile(topic);before=p.model_dump();r=self.generate(p)
            self.assertEqual(r['status'],'needs_scope');self.assertEqual(r['reason_code'],'no_selection_evidence')
            self.assertEqual(r['candidates'],[]);self.assertEqual(r['selected'],[])
            self.assertEqual(r['ranking_status'],'withheld');self.assertEqual(r['next_action'],'choose_area_and_point')
            self.assertEqual(r['no_selection_evidence_count'],3);self.assertEqual(p.model_dump(),before)

    def test_area_choice_does_not_create_evidence_or_selection(self):
        r=pool().generate(GenerationInput(profile=unknown_profile(),mode='exploratory',area_codes=['38030020']),orchestrator())
        self.assertEqual(r['status'],'needs_scope');self.assertEqual(r['searched_count'],2)
        self.assertEqual(r['candidates'],[]);self.assertEqual(r['area_codes'],['38030020'])

    def test_conflicting_measures_are_not_selection_evidence(self):
        data=index();data.conflicts['shops:a']='가상 업종 충돌'
        r=self.generate(profile(100,0),orchestrator=Orchestrator({'living':LivingModule(data)}))
        self.assertEqual(r['status'],'needs_scope');self.assertEqual(r['no_selection_evidence_count'],3)

    def test_partial_measures_explain_sources_and_unknown_original_weight(self):
        p=unknown_profile(mixed=True);r=self.generate(p)
        self.assertEqual(r['status'],'completed');self.assertEqual(r['ranking_status'],'withheld')
        for s in r['selected']:
            reason=s['selection_reason'];self.assertEqual(s['coverage'],.5);self.assertIsNone(s['score'])
            self.assertEqual(len(reason['basis']),1);self.assertEqual(len(reason['unverified']),1)
            self.assertEqual(reason['basis'][0]['weight'],.5);self.assertEqual(reason['unverified'][0]['weight'],.5)
            self.assertEqual(reason['basis'][0]['source_url'],'https://www.data.go.kr/data/15083033/fileData.do')
            self.assertIn('미확인',reason['text']);self.assertIn('주변 소음',reason['text'])
            self.assertNotIn('편의점',reason['text'])

    def test_confirmed_zero_is_selected_and_tie_rule_is_not_personalized_reason(self):
        p=unknown_profile(mixed=True);p.criteria[0].utility.limit=1.0
        # Every candidate is away from this verified grocery; utilities are truly zero.
        data=index();data.groups['supermarket'][0]['lon']=128.15
        r=self.generate(p,orchestrator=Orchestrator({'living':LivingModule(data)}))
        self.assertEqual(r['status'],'completed');self.assertEqual(len(r['selected']),3)
        for s in r['selected']:
            self.assertEqual(s['coverage'],.5);self.assertEqual(s['score_range'],[0,50])
            self.assertIn('기여는 0점',s['selection_reason']['text'])
            self.assertIn('ID 순서',s['selection_reason']['text'])
            self.assertEqual(s['selection_reason']['tie_breaker'],'candidate_id_then_separation')

    def test_candidates_without_weighted_facts_are_excluded_from_mixed_pool(self):
        data=index();original=data.nearest
        data.nearest=lambda c,k:None if c.longitude==128.1 else original(c,k)
        r=self.generate(unknown_profile(mixed=True),orchestrator=Orchestrator({'living':LivingModule(data)}))
        self.assertEqual(r['status'],'limited');self.assertEqual(r['no_selection_evidence_count'],1)
        self.assertEqual(len(r['candidates']),2);self.assertNotIn(128.1,[c['longitude'] for c in r['candidates']])

    def test_unverified_hard_constraints_still_prevent_auto_selection(self):
        p=unknown_profile(mixed=True);p.criteria[1].hard={'operator':'lte','value':10.0}
        p=NeedProfile.model_validate(p.model_dump())
        r=self.generate(p);self.assertEqual(r['status'],'unsupported');self.assertEqual(r['candidates'],[])

    def test_manual_single_point_keeps_unknown_weight_and_withheld_ranking(self):
        app=AppState(index());_,session=app.session();p=unknown_profile()
        result=app.compare(session,CompareInput(profile=p,candidates=[Candidate(id='manual',label='직접 선택',
            latitude=35.18,longitude=128.1,origin='user')]))
        a=result['report']['assessments'][0]
        self.assertEqual(a['coverage'],0);self.assertIsNone(a['score'])
        self.assertEqual(result['report']['ranking_status'],'withheld');self.assertEqual(a['details'][0]['weight'],1)

    def test_pool_scope_and_view_bounds_describe_acquired_boundary_not_recommendation(self):
        p=pool();meta=p.metadata()
        self.assertIn('상가가 등록된 500m',meta['limitations']);self.assertIn('고르게 대표하지',meta['limitations'])
        for area in meta['areas']:
            self.assertEqual(area['view_bounds'],list(p.boundary.bounds[area['code']]))


if __name__=='__main__':unittest.main()
