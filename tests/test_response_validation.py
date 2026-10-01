import json,unittest
from threading import Event
from app.codex_runner import RunnerError
from app.research_policy import SourcePage,today
from app.response_validation import ResponseReview,ClaimDecision,make_claim,verify_claims
from app.research_plan import evidence_status
from app.reviews import research_reviews
from app.safety_research import research_safety
from app.leisure_research import research_leisure
from app.modules.living import ShopIndex,LivingModule
from app.orchestrator import Orchestrator
from test_reviews import Runner as ReviewRunner,excerpt as review_excerpt
from test_safety import RunnerFixture as SafetyRunner,article,TARGET
from test_leisure import RunnerFixture as LeisureRunner,excerpt as hobby_excerpt,SCOPE,PAGE_TEXT,leisure
from test_living import index,shop,profile,candidates


def claim():
    x=review_excerpt().model_dump()
    return make_claim('living',{'name':'가상 마트'},x,SourcePage('가상 마트 '+x['quote'],('2026-01-01',)),
        [dict(request_id='q1',question='품목 선택 경험')])


class Verifier:
    def __init__(self,mode='supported'):
        self.mode=mode;self.last_metadata={'web_search_count':1,'fixture':True};self.calls=[]
    def run(self,prompt,response_type,**options):
        self.calls.append(options);self.last_metadata={'web_search_count':0,'search_mode':'disabled','fixture':True}
        if self.mode=='timeout':raise RunnerError('timeout')
        items=json.loads(prompt.split('검토 JSON:\n')[1]);decisions=[]
        for c in items:
            decisions.append(ClaimDecision(claim_id=c['claim_id'],verdict='supported' if self.mode=='supported' else 'contradicted',
                request_ids=[q['request_id'] for q in c['questions']],reason='supported' if self.mode=='supported' else 'interpretation_unsupported'))
        return ResponseReview(decisions=decisions)


class ResponseValidationTests(unittest.TestCase):
    def test_other_region_claim_is_rejected_before_codex_review(self):
        q=article(quote='다른동 침수 피해 복구 사업을 진행한다.',interpretation='가상동의 침수 피해를 복구했다.')
        text='가상동은 공원 행사를 열었다. 다른동 침수 피해 복구 사업을 진행한다.'
        result=research_safety(SafetyRunner(q),TARGET,cancel=Event(),fetcher=lambda *_:SourcePage(text,(today().isoformat(),)))
        item=result['items'][0]
        self.assertEqual(item['unconfirmed_topics'],['flood']);self.assertFalse(item['excerpts'])
        self.assertIn('area_claim_unverified',item['rejection_reasons']);self.assertEqual(result['response_validation']['status'],'not_needed')

    def test_same_quote_in_conflicting_regions_is_ambiguous(self):
        q=article(quote='침수 피해를 복구했다.')
        page=SourcePage('가상동 침수 피해를 복구했다. 다른동 침수 피해를 복구했다.',(today().isoformat(),))
        result=research_safety(SafetyRunner(q),TARGET,cancel=Event(),fetcher=lambda *_:page)
        self.assertFalse(result['items'][0]['excerpts'])

    def test_next_sentence_region_cannot_validate_the_previous_claim(self):
        q=article(quote='다른동 침수 피해를 복구했다.')
        page=SourcePage('다른동 침수 피해를 복구했다. 가상동은 공원 행사를 열었다.',(today().isoformat(),))
        result=research_safety(SafetyRunner(q),TARGET,cancel=Event(),fetcher=lambda *_:page)
        self.assertFalse(result['items'][0]['excerpts'])

    def test_source_valid_safety_claim_with_unsupported_interpretation_is_withheld(self):
        runner=SafetyRunner(article(interpretation='침수 위험이 없고 이 집은 안전해.'))
        old=runner.run;verifier=Verifier('contradicted')
        runner.run=lambda prompt,model,**kw:verifier.run(prompt,model,**kw) if model is ResponseReview else old(prompt,model,**kw)
        result=research_safety(runner,TARGET,cancel=Event(),fetcher=lambda *_:SourcePage(article().quote,(today().isoformat(),)))
        self.assertFalse(result['items'][0]['excerpts']);self.assertEqual(result['items'][0]['unconfirmed_topics'],['flood'])

    def test_wrong_hobby_form_remains_a_discovery_and_never_a_matching_quote(self):
        q=hobby_excerpt(quote='매트 필라테스 개인 레슨을 제공한다.',interpretation='기구 소그룹이야.')
        page=SourcePage('가상필라테스 경상남도 진주시 가상로 2 '+q.quote,(today().isoformat(),))
        result=research_leisure(LeisureRunner(q),SCOPE,cancel=Event(),index=leisure(),fetcher=lambda *_:page)
        self.assertEqual(len(result['discoveries']),1);self.assertEqual(result['discoveries'][0]['status'],'request_unverified')
        self.assertFalse(result['discoveries'][0]['excerpts']);self.assertIn('activity_form_unverified',result['rejection_reasons'])
        self.assertEqual(evidence_status('leisure',result),'unverified')

    def test_negative_matching_form_is_evidence_without_suitability_claim(self):
        q=hobby_excerpt(quote='기구 필라테스 소그룹 수업을 제공하지 않는다.',interpretation='운영자 안내에 기구 소그룹 수업을 제공하지 않는다고 나와.')
        page=SourcePage('가상필라테스 경상남도 진주시 가상로 2 '+q.quote,(today().isoformat(),))
        result=research_leisure(LeisureRunner(q),SCOPE,cancel=Event(),index=leisure(),fetcher=lambda *_:page)
        self.assertTrue(result['discoveries'][0]['excerpts']);self.assertFalse(result['discoveries'][0]['score_eligible'])

    def test_even_supported_verifier_cannot_bypass_the_source_gate(self):
        runner=ReviewRunner()
        result=research_reviews(runner,[index().records['shops:a']],cancel=Event(),fetcher=lambda *_:SourcePage('가상 마트 가상 시험 주소 가짜 인용만 있어요.',('2026-01-01',)))
        self.assertEqual(result['response_validation']['candidate_count'],0);self.assertFalse(result['items'][0]['excerpts'])

    def test_verifier_is_search_disabled_and_diagnostics_keep_both_stages(self):
        runner=Verifier();decisions,report=verify_claims(runner,[claim()],Event())
        self.assertEqual(report['accepted_count'],1);self.assertFalse(runner.calls[0]['search'] or runner.calls[0]['retries'])
        self.assertEqual(runner.last_metadata['web_search_count'],1)
        self.assertEqual(report['verifier_metadata']['web_search_count'],0)

    def test_missing_duplicate_foreign_claim_or_request_ids_fail_closed(self):
        for mode in ('missing','foreign','duplicate','foreign_request','wrong_schema'):
            runner=Verifier()
            def invalid(prompt,response_type,**kw):
                c=claim();d=dict(claim_id=c['claim_id'],verdict='supported',request_ids=['q1'],reason='supported')
                if mode=='missing':return ResponseReview(decisions=[])
                if mode=='foreign':d['claim_id']='0'*64
                if mode=='foreign_request':d['request_ids']=['foreign']
                if mode=='wrong_schema':return {'decisions':[d]}
                return ResponseReview(decisions=[ClaimDecision(**d)]*(2 if mode=='duplicate' else 1))
            runner.run=invalid
            decisions,report=verify_claims(runner,[claim()],Event())
            self.assertEqual(report['status'],'failed');self.assertEqual(report['accepted_count'],0)
            self.assertTrue(all(d['verdict']!='supported' for d in decisions.values()))

    def test_verifier_timeout_does_not_publish_unreviewed_interpretation(self):
        runner=Verifier('timeout');runner.timeout=120;decisions,report=verify_claims(runner,[claim()],Event())
        self.assertEqual(report['error'],'timeout');self.assertEqual(report['accepted_count'],0)
        self.assertEqual(runner.timeout,120);self.assertEqual(report['timeout_seconds'],45)
        self.assertFalse(any(d['verdict']=='supported' for d in decisions.values()))

    def test_only_explicitly_matched_question_gets_found_status(self):
        result={'items':[{'facility_id':'same','excerpts':[{'request_ids':['allergy'],'quote':'표시'}]}]}
        self.assertEqual(evidence_status('living',result,'allergy'),'found')
        self.assertEqual(evidence_status('living',result,'wheelchair'),'not_found')

    def test_question_not_matched_by_supported_verifier_is_not_accepted(self):
        runner=Verifier();runner.run=lambda *a,**k:ResponseReview(decisions=[ClaimDecision(claim_id=claim()['claim_id'],verdict='supported',request_ids=[],reason='supported')])
        _,report=verify_claims(runner,[claim()],Event());self.assertEqual(report['accepted_count'],0)

    def test_cancelled_verification_does_not_publish_a_result(self):
        runner=Verifier();cancel=Event()
        def cancelled(*a,**kw):cancel.set();raise RunnerError('cancelled')
        runner.run=cancelled
        with self.assertRaises(RunnerError):verify_claims(runner,[claim()],cancel)

    def test_known_name_industry_conflict_is_queued_and_keeps_scores_unknown(self):
        row=shop('shops:suspect','신성통상TOPTEN탑마트서진주점','슈퍼마켓',128.10)
        data=ShopIndex({'generated_at':'test','records':[row]})
        run=Orchestrator({'living':LivingModule(data)}).run(profile(),candidates())
        self.assertTrue(data.metadata()['classification_review_queue']);self.assertEqual(run['report']['ranking_status'],'withheld')
        self.assertTrue(any(e['status']=='conflicting' for e in run['modules'][0]['evidence']))

    def test_bad_numeric_and_extra_fields_cannot_pass_the_verifier_contract(self):
        for doc in ({'decisions':[{'claim_id':'0'*64,'verdict':'supported','request_ids':['q1'],'reason':'supported','score':100}]},
                    {'decisions':[{'claim_id':'0'*64,'verdict':'supported','request_ids':[7],'reason':'supported'}]}):
            with self.assertRaises(ValueError):ResponseReview.model_validate(doc)


if __name__=='__main__':unittest.main()
