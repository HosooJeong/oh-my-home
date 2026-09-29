import json
from pathlib import Path
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Event, Thread
import unittest

from app.contracts import Candidate, NeedProfile, Question
from app.modules.transport import METRIC, SOURCE, StopIndex, TransportModule
from app.orchestrator import Orchestrator
from app.preferences import update_preferences
from app.reviews import ReviewInput
from app.transport_preferences import TransportInput, transport_profile
from app.web import AppState, CompareInput, PreferenceInput, make_handler
from test_living import index, profile, candidates


def stop(id="a", name="가상 정류장", lon=128.11):
    return dict(id="bus:" + id, source_id=id, kind="bus", name=name, detail="버스정류장 · " + id,
                lat=35.18, lon=lon, date="2025-10-31", date_label="정보수집일", source_row=5,
                source_member=None, source_url=SOURCE, address="")


def stops(rows=None):
    return StopIndex({"generated_at": "2026-09-30T00:00:00+09:00", "records": [stop()] if rows is None else rows})


def edit(p=None, **changes):
    return TransportInput(profile=p or profile(100, 0), mode="bus", destination="가상 직장",
        time_of_day="평일 오전 8시", include_stop=True, ideal=0.0, limit=1500.0,
        group_weight=30.0, importance=100.0, mandatory_limit=False).model_copy(update=changes)


def combined():
    return update_preferences(transport_profile(edit()), {"living": 70.0}, confirm_weights=True)


class TransportModuleTests(unittest.TestCase):
    def run_profile(self, p=None, rows=None, cs=None):
        return Orchestrator({"transport": TransportModule(stops(rows))}).run(
            p or combined(), cs or candidates())

    def test_all_rows_used_same_name_ids_distinct_and_deterministic_tie(self):
        data = stops([stop("z", "같은 이름"), stop("a", "같은 이름")])
        self.assertEqual(data.metadata()["stop_count"], 2)
        self.assertEqual(data.nearest(candidates()[1])[0]["id"], "bus:a")
        self.assertEqual(data.nearest(candidates()[1])[1], 0)

    def test_evidence_has_id_date_row_and_explicit_distance_limitations(self):
        result = self.run_profile()
        fact = next(m for m in result["modules"] if m["module_id"] == "transport")["evidence"][0]
        self.assertEqual(fact["status"], "verified")
        self.assertEqual(fact["source_record"], "bus:a")
        self.assertEqual(fact["data_date"], "2025-10-31")
        self.assertIn("CSV 5행", fact["note"])
        self.assertIn("직선거리", fact["note"])
        self.assertIn("현재 운행은 미확인", fact["note"])
        self.assertTrue(fact["retrieved_at"])

    def test_missing_utility_returns_distance_and_withholds_score(self):
        p = combined()
        p.criteria[-1].utility = None
        result = self.run_profile(p)
        fact = next(m for m in result["modules"] if m["module_id"] == "transport")["evidence"][0]
        self.assertIsNotNone(fact["value"])
        self.assertIsNone(result["report"]["assessments"][0]["score"])

    def test_route_time_walking_distance_and_wrong_unit_not_converted(self):
        for metric, unit, direction in [("commute_time_min", "min", "lower"),
                ("bus_stop_walking_distance_m", "m", "lower"), (METRIC, "min", "lower"),
                (METRIC, "m", "higher")]:
            p = combined()
            c = p.criteria[-1]
            c.metric = metric
            c.utility = c.utility.model_copy(update={"unit": unit, "direction": direction,
                                                       "ideal": 1500.0 if direction == "higher" else 0.0,
                                                       "limit": 0.0 if direction == "higher" else 1500.0})
            result = self.run_profile(p)
            m = next(m for m in result["modules"] if m["module_id"] == "transport")
            self.assertEqual(m["unsupported_criterion_ids"], [c.id])
            self.assertEqual(m["evidence"], [])
            self.assertEqual(result["report"]["ranking"], [])

    def test_empty_and_outside_screen_not_zero_distance(self):
        for rows, cs in [([], candidates()), ([stop()], [Candidate(id="out", label="범위 밖",
                latitude=37.5, longitude=127.0, origin="fixture")])]:
            result = self.run_profile(rows=rows, cs=cs)
            facts = next(m for m in result["modules"] if m["module_id"] == "transport")["evidence"]
            self.assertTrue(all(e["value"] is None and e["status"] == "missing" for e in facts))

    def test_invalid_coordinates_identity_source_date_and_row_rejected(self):
        for change in [{"lat": float("nan")}, {"lon": 129.5}, {"id": "wrong"},
                       {"source_url": "https://example.invalid"}, {"date": "2025-13-31"},
                       {"date": "20251031"}, {"source_row": 0}, {"name": " "}]:
            with self.assertRaises(ValueError): stops([stop() | change])
        with self.assertRaises(ValueError): stops([stop(), stop()])

    def test_cancel_no_published_report(self):
        cancel = Event(); cancel.set()
        result = Orchestrator({"transport": TransportModule(stops())}).run(combined(), candidates(), cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["report"])


class TransportEditTests(unittest.TestCase):
    def test_explicit_profile_edit_preserves_other_needs_and_context(self):
        p = profile(100, 0)
        original = p.model_dump()
        result = transport_profile(edit(p))
        self.assertEqual(p.model_dump(), original)
        self.assertEqual(result.criteria[:2], p.criteria)
        self.assertEqual(result.revision, p.revision + 1)
        self.assertTrue(result.request.startswith(p.request))
        self.assertEqual({c.key: c.value for c in result.context}, {
            "travel_mode": "버스 중심", "travel_destination": "가상 직장", "travel_time": "평일 오전 8시"})
        self.assertTrue(all(c.source_quote in result.request for c in result.context))

    def test_mode_change_alone_does_not_remove_bus_preference(self):
        p = combined()
        changed = transport_profile(edit(p, mode="car", include_stop=True))
        self.assertEqual(changed.criteria[-1].importance, 100)
        self.assertEqual(changed.criteria[-1].id, p.criteria[-1].id)

    def test_explicit_exclusion_clears_stop_hard_but_preserves_unrelated_transport(self):
        p = transport_profile(edit(mandatory_limit=True))
        route = p.criteria[-1].model_dump() | {"id": "commute", "metric": "commute_time_min",
            "label": "통근시간", "utility": None, "hard": None, "importance": 50.0}
        d = p.model_dump(); d["criteria"].append(route)
        p = NeedProfile.model_validate(d)
        result = transport_profile(edit(p, mode="car", include_stop=False))
        stop_c = next(c for c in result.criteria if c.metric == METRIC)
        self.assertEqual(stop_c.importance, 0)
        self.assertIsNone(stop_c.hard)
        self.assertEqual(result.criteria[-1].model_dump(), route)
        self.assertEqual(next(g for g in result.groups if g.id == "transport").weight, 30)

    def test_excluding_only_stop_sets_group_zero_and_keeps_history(self):
        p = combined()
        result = transport_profile(edit(p, include_stop=False))
        self.assertEqual(len(result.criteria), len(p.criteria))
        self.assertEqual(next(g for g in result.groups if g.id == "transport").weight, 0)

    def test_distance_question_resolved_commute_question_preserved(self):
        p = combined(); id = p.criteria[-1].id
        p.questions = [Question(id="distance", text="정류장 직선거리 목표 기준은?", reason="기준", criterion_ids=[id], blocking=False),
                       Question(id="commute", text="출근 목적지는?", reason="경로", criterion_ids=[id], blocking=False)]
        result = transport_profile(edit(p))
        self.assertEqual([q.id for q in result.questions], ["commute"])

    def test_identifier_collision_avoided(self):
        p = profile(100, 0); p.criteria[0].id = "bus_stop"
        self.assertEqual(transport_profile(edit(p)).criteria[-1].id, "bus_stop_2")

    def test_bad_threshold_and_profile_length_rejected(self):
        for change in [{"ideal": 1500.0}, {"importance": 0.0}]:
            with self.assertRaises(ValueError): transport_profile(edit(**change))
        p = profile(100, 0); p.request = "가" * 4000
        with self.assertRaises(ValueError): transport_profile(edit(p))


class TwoModuleTests(unittest.TestCase):
    def setUp(self):
        self.state = AppState(index(), stop_index=stops())
        _, self.session = self.state.session()

    def test_two_modules_rank_reversal_reuses_identical_evidence(self):
        run = self.state.compare(self.session, CompareInput(profile=combined(), candidates=candidates()))
        self.assertEqual(run["report"]["ranking"], ["a", "b"])
        self.assertEqual({m["module_id"] for m in run["modules"]}, {"living", "transport"})
        changed = self.state.preferences(self.session, PreferenceInput(run_id=run["run_id"],
            group_weights={"living": 30.0, "transport": 70.0}, criterion_importance={}, confirm_weights=True))
        self.assertEqual(changed["run"]["report"]["ranking"], ["b", "a"])
        self.assertEqual(changed["run"]["modules"], run["modules"])
        self.assertEqual(changed["run"]["review_key"], run["review_key"])
        for a in changed["run"]["report"]["assessments"]:
            self.assertAlmostEqual(sum(d["contribution"] or 0 for d in a["details"]), a["score"], places=5)

    def test_changed_distance_requeries_transport_and_changes_result(self):
        p = combined()
        first = self.state.compare(self.session, CompareInput(profile=p, candidates=candidates()))
        changed = transport_profile(edit(p, limit=200.0, group_weight=30.0))
        second = self.state.compare(self.session, CompareInput(profile=changed, candidates=candidates()))
        self.assertNotEqual(second["profile_fingerprint"], first["profile_fingerprint"])
        self.assertNotEqual(second["review_key"], first["review_key"])
        self.assertLess(second["report"]["assessments"][0]["score"], first["report"]["assessments"][0]["score"])

    def test_zero_weight_bus_hard_constraint_still_blocks(self):
        p = transport_profile(edit(group_weight=0.0, mandatory_limit=True, limit=100.0))
        run = self.state.compare(self.session, CompareInput(profile=p, candidates=candidates()))
        self.assertEqual(run["report"]["assessments"][0]["eligibility"], "ineligible")
        self.assertEqual(run["report"]["ranking"], ["b"])

    def test_unknown_commute_condition_keeps_weight_and_withholds_ranking(self):
        p = combined(); d = p.model_dump()
        d["criteria"].append(d["criteria"][-1] | {"id": "commute", "metric": "commute_time_min", "importance": 100.0})
        run = self.state.compare(self.session, CompareInput(profile=NeedProfile.model_validate(d), candidates=candidates()))
        self.assertEqual(run["report"]["assessments"][0]["coverage"], .85)
        self.assertIsNone(run["report"]["assessments"][0]["score"])
        self.assertEqual(run["report"]["ranking"], [])

    def test_bus_facility_cannot_be_sent_to_shop_review_job(self):
        run = self.state.compare(self.session, CompareInput(profile=combined(), candidates=candidates()))
        self.assertEqual(run["facilities"]["bus:a"]["kind"], "bus")
        self.assertNotIn("review_links", run["facilities"]["bus:a"])
        with self.assertRaises(ValueError):
            self.state.reviews(self.session, ReviewInput(request_id="no_bus_review", run_id=run["run_id"], facility_ids=["bus:a"]))
        self.assertIsNone(self.state.active_job)


class TransportHttpTests(unittest.TestCase):
    def test_http_profile_bootstrap_two_module_comparison(self):
        state = AppState(index(), stop_index=stops())
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, Path("no-test-env")))
        Thread(target=server.serve_forever, daemon=True).start()
        def call(path, data=None, token=None):
            c = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            c.request("GET" if data is None else "POST", path, json.dumps(data) if data else None,
                      {"Content-Type": "application/json", "X-Session": token or ""})
            response = c.getresponse(); result = response.status, json.loads(response.read()); c.close()
            return result
        try:
            _, b = call('/api/bootstrap'); token = b['token']
            self.assertEqual(b['data']['transport']['stop_count'], 1)
            self.assertEqual(call('/api/transport-profile', edit().model_dump())[0], 403)
            status, p = call('/api/transport-profile', edit().model_dump(), token)
            self.assertEqual(status, 200)
            status, run = call('/api/compare', {'profile':p['profile'], 'candidates':[c.model_dump() for c in candidates()]}, token)
            self.assertEqual(status, 200)
            self.assertEqual({m['module_id'] for m in run['modules']}, {'living', 'transport'})
            self.assertEqual(call('/api/transport-profile', edit(mode='fly').model_dump(), token)[0], 400)
        finally:
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
