import unittest
from pydantic import ValidationError
from app.codex_runner import RunnerError
from app.contracts import NeedProfile, PreferenceGroup, Criterion, CategoryResult, Evidence
from app.intake import IntakeDraft, IntakeParameter, expand_draft, prepare_profile
from app.candidates import GenerationInput, execution_plan
from app.orchestrator import Orchestrator
from app.web import AppState, CompareInput
from test_living import profile, index
from test_candidates import pool, orchestrator
from test_agent_core import candidates


class IntakeFlowTests(unittest.TestCase):
    def test_compact_parameter_keys_match_the_final_contract(self):
        from app.contracts import MetricParameters
        allowed = IntakeParameter.model_json_schema()['properties']['key']['enum']
        self.assertEqual(set(allowed), set(MetricParameters.__annotations__))
        with self.assertRaises(ValidationError):
            IntakeParameter(key='preferred_max_time_min',value='10')

    def draft(self, **changes):
        return IntakeDraft.model_validate(dict(groups=[dict(id='housing',weight=0.0,source='user')],
            criteria=[],context=[dict(key='housing_reference',value='requested',source_id='s1')],
            questions=[],**changes))

    def test_reference_only_contract_does_not_invent_price_score(self):
        p=expand_draft(self.draft(), '실거래 참고만', 1, {'s1':'실거래 참고만'})
        self.assertEqual(p.criteria,[])
        self.assertEqual(p.groups[0].weight,0)
        self.assertEqual(p.context[0].source_quote,'실거래 참고만')
        d=p.model_dump();d['context']=[]
        with self.assertRaises(ValidationError): NeedProfile.model_validate(d)

    def test_housing_reference_group_can_coexist_without_a_criterion(self):
        p=profile(100,0).model_dump()
        p['groups'].append(dict(id='housing',label='집·비용',weight=0.0,source='user',reason='참고'))
        value=NeedProfile.model_validate(p)
        self.assertFalse(any(c.group_id=='housing' for c in value.criteria))

    def test_source_reference_is_restored_exactly_and_unknown_id_is_rejected(self):
        p=expand_draft(self.draft(), '집·비용은 참고만.', 1, {'s1':'집·비용은 참고만.'})
        self.assertEqual(p.request,'집·비용은 참고만.')
        with self.assertRaisesRegex(RunnerError,'unsupported_source_reference'):
            expand_draft(self.draft(),p.request,1,{'s2':p.request})

    def test_actual_intake_boundary_uses_compact_schema_and_local_identity(self):
        class Fake:
            last_metadata={}
            def run(inner,prompt,response_type,**kwargs):
                self.assertIs(response_type,IntakeDraft)
                self.assertFalse(kwargs['search'])
                return self.draft()
        p=prepare_profile(Fake(),'실거래 참고만')
        self.assertEqual((p.request,p.revision),('실거래 참고만',1))

    def test_exploration_retains_unknown_weight_and_withholds_full_rank(self):
        p=profile(100,0)
        p.groups.append(PreferenceGroup(id='safety',label='안전',weight=100.0,source='user',reason='시험'))
        p.criteria.append(Criterion(id='night',group_id='safety',module_id='safety',label='야간 안전',
            need='근거 확인',source_quote='근거 확인',source='user',importance=100.0,importance_source='user',
            metric='night_safety_or_environment_unverified',utility=None,hard=None))
        result=pool().generate(GenerationInput(profile=p,mode='exploratory',separation_m=0.0),orchestrator())
        self.assertEqual(len(result['candidates']),3)
        self.assertEqual(result['ranking_status'],'withheld')
        self.assertTrue(all(v['score'] is None and v['coverage']==.5 for v in result['selected']))
        self.assertEqual(result['execution_plan'][-1]['weight'],.5)

    def test_exploratory_mode_never_ignores_unsupported_hard_condition(self):
        p=profile(100,0,hard=True);p.criteria[1].module_id='housing';p.criteria[1].metric='rent_krw'
        result=pool().generate(GenerationInput(profile=p,mode='exploratory'),orchestrator())
        self.assertEqual(result['status'],'unsupported')
        self.assertEqual(result['candidates'],[])

    def test_school_metric_uses_common_pool_instead_of_static_rejection(self):
        p=profile(100,0);p.criteria[0].module_id='education';p.criteria[0].metric='school_straight_line_distance_m'
        calls=[]
        class School:
            id='education';version='fixture'
            def run(self,request,cancel):
                calls.append([c.id for c in request.candidates])
                return CategoryResult(module_id=self.id,module_version=self.version,request_fingerprint=request.fingerprint(),
                    status='completed',evidence=[Evidence(id='school_'+c.id,candidate_id=c.id,criterion_id=p.criteria[0].id,
                    value=100.0,unit='m',status='verified',source_url='https://example.invalid/fixture',
                    source_record='synthetic',data_date='2026-10-01',retrieved_at='2026-10-01T00:00:00Z',
                    method='fixture',note='가상 시험') for c in request.candidates],unsupported_criterion_ids=[],questions=[],error_code=None)
        result=pool().generate(GenerationInput(profile=p,separation_m=0.0),Orchestrator({'education':School()}))
        self.assertEqual(len(calls[0]),3)
        self.assertEqual(result['module_ids'],['education'])
        self.assertEqual(result['status'],'completed')

    def test_one_home_is_an_analysis_without_requiring_a_second_candidate(self):
        p=profile(100,0);data=CompareInput(profile=p,candidates=candidates()[:1])
        app=AppState(index());_,session=app.session()
        result=app.compare(session,data)
        self.assertEqual(len(result['report']['assessments']),1)


if __name__=='__main__': unittest.main()
