import json
from pathlib import Path
from threading import Event, Thread
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from app.contracts import Candidate, ModuleRequest, CriterionWeight
from app.modules.living import LivingModule, ShopIndex, SOURCE, distance_m
from app.orchestrator import Orchestrator
from app.web import AppState, CompareInput, IntakeInput, PreferenceInput, QuickInput, make_handler, quick_profile


def shop(id, name, detail, lon):
    return dict(id=id, source_id=id, kind="shops", name=name, detail=detail, lat=35.18, lon=lon,
                date="2026-06-30", date_label="시험 기준일", source_row=2, source_member="synthetic.csv",
                source_url=SOURCE, address="가상 시험 주소")


def index():
    return ShopIndex({"generated_at": "2026-09-30T00:00:00+09:00", "records": [
        shop("shops:a", "가상 마트", "슈퍼마켓", 128.10),
        shop("shops:b", "가상 편의점", "편의점", 128.11),
        shop("shops:c", "GS25가상분류오류점", "슈퍼마켓", 128.105),
        shop("shops:d", "가상 식당", "한식 일반 음식점", 128.105)]})


def profile(mart=70.0, convenience=30.0, hard=False):
    return quick_profile(QuickInput(ideal=0.0, limit=1500.0, supermarket_weight=mart,
                                   convenience_weight=convenience, mandatory_limit=hard))


def candidates():
    return [Candidate(id=id, label="가상 " + id, latitude=35.18, longitude=lon, origin="fixture")
            for id, lon in [("a", 128.10), ("b", 128.11)]]


class LivingTests(unittest.TestCase):
    def run_profile(self, p=None, cs=None):
        return Orchestrator({"living": LivingModule(index())}).run(p or profile(), cs or candidates())

    def test_haversine_zero_symmetry_and_known_equatorial_degree(self):
        self.assertEqual(distance_m(35, 128, 35, 128), 0)
        self.assertAlmostEqual(distance_m(0, 0, 0, 1), 111195.08, places=2)
        self.assertEqual(distance_m(35, 128, 36, 129), distance_m(36, 129, 35, 128))

    def test_industry_and_ambiguous_brands_not_restaurants(self):
        data = index()
        self.assertEqual(data.metadata()["counts"], {"supermarket": 1, "convenience": 1})
        self.assertEqual(data.excluded_ambiguous, 1)
        self.assertEqual(data.nearest(candidates()[0], "supermarket")[0]["id"], "shops:a")

    def test_rank_changes_with_preference_and_facts_have_provenance(self):
        first, second = self.run_profile(), self.run_profile(profile(30, 70))
        self.assertEqual(first["report"]["ranking"], ["a", "b"])
        self.assertEqual(second["report"]["ranking"], ["b", "a"])
        for fact in first["modules"][0]["evidence"]:
            self.assertTrue(fact["source_record"] and fact["retrieved_at"] and fact["data_date"])
            self.assertIn("직선거리", fact["note"])

    def test_unsupported_metric_and_wrong_unit_keep_missing_weight(self):
        for change in ["metric", "unit"]:
            p = profile()
            if change == "metric":
                p.criteria[1].metric = "open_at_midnight"
            else:
                p.criteria[1].utility.unit = "min"
            result = self.run_profile(p)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["report"]["assessments"][0]["coverage"], .7)
            self.assertIsNone(result["report"]["assessments"][0]["score"])
            self.assertEqual(result["report"]["ranking"], [])

    def test_missing_utility_returns_distance_but_no_score(self):
        p = profile()
        p.criteria[0].utility = None
        result = self.run_profile(p)
        self.assertEqual(result["modules"][0]["evidence"][0]["status"], "verified")
        self.assertIsNone(result["report"]["assessments"][0]["score"])

    def test_conflicting_shop_classification_withholds_score_and_keeps_source(self):
        for row in [shop("shops:bad", "가상전자담배", "슈퍼마켓", 128.10),
                    shop("shops:bad", "지에스더프레시가상", "편의점", 128.10)]:
            data = ShopIndex({"generated_at": "test", "records": [row]})
            run = Orchestrator({"living": LivingModule(data)}).run(profile(), candidates())
            fact = next(e for e in run["modules"][0]["evidence"] if e["status"] == "conflicting")
            self.assertIsNotNone(fact["value"])
            self.assertEqual(fact["source_record"], "shops:bad")
            self.assertIsNone(run["report"]["assessments"][0]["score"])
            self.assertEqual(run["report"]["ranking"], [])

    def test_outside_window_and_empty_inventory_never_zero(self):
        cs = candidates()
        cs[0].latitude = 37.5
        result = self.run_profile(cs=cs)
        self.assertIsNone(result["modules"][0]["evidence"][0]["value"])
        empty = ShopIndex({"generated_at": "test", "records": []})
        result = Orchestrator({"living": LivingModule(empty)}).run(profile(), candidates())
        self.assertEqual(result["report"]["assessments"][0]["coverage"], 0)

    def test_zero_weight_hard_constraint_still_checked(self):
        p = profile(100, 0, True)
        p.criteria[1].hard.value = 100.0
        result = self.run_profile(p)
        self.assertEqual(result["report"]["assessments"][0]["eligibility"], "ineligible")
        self.assertEqual(result["report"]["ranking"], ["b"])

    def test_cancel_no_result(self):
        cancel = Event()
        cancel.set()
        result = Orchestrator({"living": LivingModule(index())}).run(profile(), candidates(), cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["report"])

    def test_invalid_inventory_rejected(self):
        for row in [shop("bad", "bad", "슈퍼마켓", float("nan")),
                    dict(shop("bad", "bad", "슈퍼마켓", 128.1), source_url="https://example.invalid")]:
            with self.assertRaises(ValueError):
                ShopIndex({"generated_at": "test", "records": [row]})


class WebStateTests(unittest.TestCase):
    def setUp(self):
        self.state = AppState(index())
        self.token, self.session = self.state.session()

    def test_reweight_reuses_exact_facts_and_rejects_old_revision(self):
        run = self.state.compare(self.session, CompareInput(profile=profile(), candidates=candidates()))
        request = PreferenceInput(run_id=run["run_id"], group_weights={},
            criterion_importance={"grocery": 30.0, "convenience": 70.0}, confirm_weights=True)
        result = self.state.preferences(self.session, request)
        self.assertEqual(result["run"]["report"]["ranking"], ["b", "a"])
        self.assertEqual(result["run"]["modules"], run["modules"])
        with self.assertRaises(ValueError):
            self.state.preferences(self.session, request)

    def test_newly_enabled_criterion_is_unknown_until_requery(self):
        run = self.state.compare(self.session, CompareInput(profile=profile(100, 0), candidates=candidates()))
        result = self.state.preferences(self.session, PreferenceInput(run_id=run["run_id"], group_weights={},
            criterion_importance={"convenience": 100.0}, confirm_weights=True))
        self.assertEqual(result["run"]["status"], "partial")
        self.assertIsNone(result["run"]["report"]["assessments"][0]["score"])

    def test_session_ownership_and_expiry(self):
        with self.assertRaises(PermissionError):
            self.state.session("foreign")
        self.session["touched"] -= 3601
        with self.assertRaises(PermissionError):
            self.state.session(self.token)

    def test_job_idempotency_busy_conflict_and_cancel(self):
        started, released = Event(), Event()
        class Runner:
            last_metadata = {"fixture": True}
            def run(self, *args, cancel, **kwargs):
                started.set()
                released.wait(3)
                return profile()
        self.state.runner_factory = Runner
        data = IntakeInput(request_id="job1", request=profile().request)
        self.state.intake(self.session, data)
        self.assertTrue(started.wait(2))
        self.assertEqual(self.state.intake(self.session, data)["id"], "job1")
        with self.assertRaises(ValueError):
            self.state.intake(self.session, IntakeInput(request_id="job1", request="different"))
        with self.assertRaises(RuntimeError):
            self.state.intake(self.session, IntakeInput(request_id="job2", request="next"))
        self.session["jobs"]["job1"]["cancel"].set()
        released.set()
        deadline = time.monotonic() + 3
        while self.state.active_job and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.session["jobs"]["job1"]["status"], "cancelled")
        self.assertIsNone(self.session["jobs"]["job1"]["profile"])

    def test_quick_invalid_thresholds_and_all_zero(self):
        for ideal, limit, a, b in [(1000, 300, 70, 30), (300, 1000, 0, 0)]:
            with self.assertRaises(ValueError):
                quick_profile(QuickInput(ideal=ideal, limit=limit, supermarket_weight=a,
                    convenience_weight=b, mandatory_limit=False))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = AppState(index())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.state, Path("missing-test-env")))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, data=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("GET" if data is None else "POST", path, json.dumps(data) if data is not None else None,
                           {"Content-Type": "application/json", **(headers or {})})
        result = connection.getresponse()
        status, body = result.status, result.read()
        connection.close()
        return status, json.loads(body)

    def test_origin_missing_session_and_rebinding_rejected(self):
        self.assertEqual(self.call("/api/compare", {})[0], 403)
        self.assertEqual(self.call("/api/bootstrap", headers={"Origin": "http://evil.invalid"})[0], 403)
        self.assertEqual(self.call("/api/bootstrap", headers={"Host": "evil.invalid"})[0], 403)

    def test_real_http_compare_and_session_isolation(self):
        _, bootstrap = self.call("/api/bootstrap")
        headers = {"X-Session": bootstrap["token"]}
        status, run = self.call("/api/compare", {"profile": profile().model_dump(),
                            "candidates": [c.model_dump() for c in candidates()]}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(run["report"]["ranking"], ["a", "b"])
        self.assertEqual(len(run["facilities"]), 2)
        _, other = self.call("/api/bootstrap")
        status, _ = self.call("/api/preferences", {"run_id": run["run_id"], "group_weights": {},
            "criterion_importance": {}, "confirm_weights": True}, {"X-Session": other["token"]})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
