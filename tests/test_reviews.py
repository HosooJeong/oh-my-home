from threading import Event
import time
import unittest
from unittest.mock import patch

from app.codex_runner import RunnerError
from app.reviews import (ReviewInput, ReviewExcerpt, ReviewResponse, StoreReviews,
                         VisibleText, source_url, research_reviews, fetch_article)
from app.web import AppState, CompareInput, IntakeInput, PreferenceInput
from app.research_policy import SourcePage
from test_living import index, profile, candidates
from research_fixture import supported_review


def excerpt(**changes):
    return ReviewExcerpt(**({"source_url": "https://synthetic.tistory.com/123",
        "title": "가상 매장 방문 후기", "published_date": "2026-01-01",
        "matched_name": "가상 마트", "identity_note": "가상 시험 주소와 상호 일치",
        "topic": "size", "sentiment": "mixed", "quote": "작지만 품목은 다양했어요.",
        "interpretation": "작은 규모와 품목 다양성을 언급한 개인 의견."} | changes))


class Runner:
    def __init__(self, excerpts=None, search_count=1):
        self.last_metadata = {"fixture": True, "web_search_count": search_count}
        self.excerpts = [excerpt()] if excerpts is None else excerpts
        self.calls = []
    def run(self, prompt, response_type, **kwargs):
        review=supported_review(prompt,response_type)
        if review is not None:return review
        self.calls.append((prompt, kwargs))
        return ReviewResponse(items=[StoreReviews(facility_id="shops:a", excerpts=self.excerpts)])


class ReviewTests(unittest.TestCase):
    def run_reviews(self, runner=None, text="작지만 품목은 다양했어요.", cancel=None):
        page = None if text is None else SourcePage('가상 마트 가상 시험 주소 ' + text, ('2026-01-01',))
        return research_reviews(runner or Runner(), [index().records["shops:a"]],
                                cancel=cancel or Event(), fetcher=lambda *args: page)

    def test_verbatim_quote_checked_but_opinion_is_not_scored(self):
        runner=Runner(); result=self.run_reviews(runner)
        quote=result["items"][0]["excerpts"][0]
        self.assertTrue(quote["quote_verified"])
        self.assertFalse(quote["score_eligible"] or result["score_eligible"])
        self.assertEqual(quote["identity_verification"], "name_and_public_address_in_page")
        self.assertTrue(quote['publication_verified'])
        prompt, args=runner.calls[0]
        self.assertTrue(args["search"]); self.assertEqual(args["domains"], ["tistory.com"])
        self.assertEqual(args["retries"],0)
        self.assertNotIn('"lat"',prompt); self.assertNotIn('"longitude"',prompt)

    def test_invented_quote_blocked_and_inaccessible_source_not_filled(self):
        for text in ["실제 원문에는 다른 문장만 있어요.", None]:
            item=self.run_reviews(text=text)["items"][0]
            self.assertEqual(item["status"],"unverified")
            self.assertEqual(item["excerpts"],[])

    def test_unknown_old_invalid_and_future_dates_rejected(self):
        for value in [None, "2018-01-01", "2026-02-31","2099-01-01"]:
            self.assertEqual(self.run_reviews(Runner([excerpt(published_date=value)]))["items"][0]["excerpts"],[])

    def test_different_store_or_no_search_rejected(self):
        for runner in [Runner([excerpt(matched_name="다른 점포")]),Runner(search_count=0)]:
            self.assertEqual(self.run_reviews(runner)["items"][0]["excerpts"],[])

    def test_per_source_word_limit_across_quotes_and_query_variants(self):
        first=" ".join("가"+str(i) for i in range(12))
        second=" ".join("나"+str(i) for i in range(12))
        runner=Runner([excerpt(quote=first),excerpt(quote=second,source_url="https://synthetic.tistory.com/123?x=1#section")])
        result=self.run_reviews(runner,text=first+" "+second)["items"][0]
        self.assertEqual(len(result["excerpts"]),1)
        self.assertEqual(result["rejected_count"],1)

    def test_oversized_quote_and_request_limits(self):
        for ids in [[],["a","a"],["a","b","c","d"]]:
            with self.assertRaises(ValueError):
                ReviewInput(request_id="test",run_id="run",facility_ids=ids)
        with self.assertRaises(ValueError):
            excerpt(quote="a"*161)
        q=" ".join("a" for _ in range(21))
        self.assertEqual(self.run_reviews(Runner([excerpt(quote=q)]),text=q)["items"][0]["excerpts"],[])

    def test_source_links_reject_maps_credentials_ports_private_hosts_and_redirect_paths(self):
        for url in ["http://synthetic.tistory.com/123","https://synthetic.tistory.com.evil.com/123",
                    "https://127.0.0.1/123","https://place.map.kakao.com/123","https://blog.naver.com/test/123",
                    "https://synthetic.tistory.com/search?q=a","https://synthetic.tistory.com:999/123",
                    "https://u@synthetic.tistory.com/123","https://synthetic.tistory.com\\@evil.com/123"]:
            self.assertIsNone(source_url(url))
        self.assertEqual(source_url("https://synthetic.tistory.com/123?a=b#c"),"https://synthetic.tistory.com/123")

    def test_script_text_not_used_for_quote_verification(self):
        parser=VisibleText();parser.feed('<p>보이는 문장</p><script>가짜 인용</script><style>숨김</style>')
        self.assertEqual(parser.parts,["보이는 문장"])

    def test_empty_search_result_does_not_mean_negative_review(self):
        item=self.run_reviews(Runner([]))["items"][0]
        self.assertEqual(item["status"],"not_found");self.assertEqual(item["excerpts"],[])

    def test_foreign_or_duplicate_model_ids_rejected(self):
        runner=Runner()
        for items in [[StoreReviews(facility_id="foreign",excerpts=[])],
                      [StoreReviews(facility_id="shops:a",excerpts=[])]*2]:
            with patch.object(runner,"run",return_value=ReviewResponse(items=items)), self.assertRaises(RunnerError):
                self.run_reviews(runner)

    def test_cancellation_before_model_and_after_fetch(self):
        cancel=Event();cancel.set();runner=Runner()
        with self.assertRaises(RunnerError):self.run_reviews(runner,cancel=cancel)
        self.assertEqual(runner.calls,[])
        cancel.clear()
        def fetch(*args):cancel.set();return "작지만 품목은 다양했어요."
        with self.assertRaises(RunnerError):
            research_reviews(runner,[index().records["shops:a"]],cancel=cancel,fetcher=fetch)

    def test_robots_disallow_no_page_read(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'User-agent: *\nDisallow: /'
        class Opener:
            count=0
            def open(self,*args,**kwargs):self.count+=1;return Response()
        opener=Opener()
        with patch('app.reviews.build_opener',return_value=opener):
            self.assertIsNone(fetch_article('https://synthetic.tistory.com/123',Event()))
        self.assertEqual(opener.count,1)


class ReviewJobTests(unittest.TestCase):
    def setUp(self):
        self.started,self.released=Event(),Event()
        started,released=self.started,self.released
        class Delayed(Runner):
            def run(self,*args,**kwargs):
                started.set();released.wait(3)
                return ReviewResponse(items=[StoreReviews(facility_id="shops:a",excerpts=[])])
        self.runner=Delayed();self.state=AppState(index(),lambda:self.runner,llm_settings=ModelSettings(provider='codex'))
        _,self.session=self.state.session()
        self.run=self.state.compare(self.session,CompareInput(profile=profile(),candidates=candidates()))
        self.data=ReviewInput(request_id="review1",run_id=self.run["run_id"],facility_ids=["shops:a"])
    def tearDown(self):
        self.released.set();self.wait()
    def wait(self):
        deadline=time.monotonic()+4
        while self.state.active_job and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(self.state.active_job)
    def start(self):
        self.state.reviews(self.session,self.data);self.assertTrue(self.started.wait(2))
    def test_session_facility_and_run_ownership(self):
        _,other=self.state.session()
        with self.assertRaises(ValueError):self.state.reviews(other,self.data)
        for changed in [{"facility_ids":["foreign"]},{"run_id":"old"}]:
            with self.assertRaises(ValueError):self.state.reviews(self.session,ReviewInput(**(self.data.model_dump()|changed)))
    def test_duplicate_budget_shared_busy_and_score_unchanged(self):
        self.start()
        self.assertEqual(self.state.reviews(self.session,self.data)["id"],"review1")
        with self.assertRaises(ValueError):
            self.state.reviews(self.session,ReviewInput(**(self.data.model_dump()|{"request_id":"extra"})))
        with self.assertRaises(RuntimeError):self.state.intake(self.session,IntakeInput(request_id="intake",request="가상"))
        self.released.set();self.wait()
        self.assertEqual(self.session["review_job"]["status"],"completed")
        self.assertEqual(self.session["comparison"][2]["report"],self.run["report"])
    def test_reweight_keeps_review_identity_new_compare_cancels_old_result(self):
        self.start()
        revised=self.state.preferences(self.session,PreferenceInput(run_id=self.run["run_id"],group_weights={},criterion_importance={"grocery":20.0},confirm_weights=True))
        self.assertEqual(revised["run"]["review_key"],self.run["review_key"])
        job=self.session["review_job"]
        self.state.compare(self.session,CompareInput(profile=profile(),candidates=candidates()))
        self.released.set();self.wait()
        self.assertEqual(job["status"],"cancelled");self.assertIsNone(job["result"])
    def test_cancel_leaves_result_empty_and_request_does_not_restart(self):
        self.start();self.session["review_job"]["cancel"].set();self.released.set();self.wait()
        job=self.state.reviews(self.session,self.data)
        self.assertEqual(job["status"],"cancelled");self.assertIsNone(job["result"])
from app.llm_settings import ModelSettings
