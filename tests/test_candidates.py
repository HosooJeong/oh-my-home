import copy
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from app.boundaries import Boundary, SOURCE
from app.candidates import CandidatePool, GenerationInput
from app.contracts import Question
from app.modules.living import LivingModule
from app.modules.transport import StopIndex, TransportModule
from app.orchestrator import Orchestrator
from app.preferences import update_preferences
from app.transport_preferences import transport_profile
from app.web import AppState, make_handler
from test_living import index, profile
from test_transport import edit, stop


def rectangle(x1=127.95, x2=128.25, y1=35.1, y2=35.25):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]


def boundary_document():
    return dict(type="FeatureCollection", source_url=SOURCE, coordinate_system="EPSG:4326", data_date="2025-06-30",
        features=[dict(type="Feature", properties=dict(code=code, name=name),
            geometry=dict(type="Polygon", coordinates=[rectangle(x1, x2)]))
            for code, name, x1, x2 in [("38030", "가상 진주", 127.95, 128.25),
                ("38030010", "가상 서쪽", 127.95, 128.105), ("38030020", "가상 동쪽", 128.105, 128.25)]])


def pool_document():
    return dict(version="shop_grid_500m_v1", cell_size_m=500, grid_crs="EPSG:5179", inventory_generated_at="fixture",
        points=[dict(candidate=dict(id=f"grid_{2000+i}_3400", label=f"가상 {i}", latitude=35.18, longitude=lon,
                                    origin="generated"), cell=[2000+i, 3400],
                     area_code="38030010" if i == 0 else "38030020", registered_shop_count=1)
                for i, lon in enumerate([128.1, 128.11, 128.12])])


def pool():
    return CandidatePool(pool_document(), Boundary(boundary_document()))


def orchestrator():
    return Orchestrator({"living": LivingModule(index()), "transport": TransportModule(StopIndex(
        dict(generated_at="fixture", records=[stop(lon=128.12)])))})


class BoundaryTests(unittest.TestCase):
    def test_polygon_hole_edges_and_multipolygon(self):
        doc = boundary_document()
        doc["features"][0]["geometry"] = dict(type="MultiPolygon", coordinates=[
            [rectangle(127.95, 128.15), rectangle(128.02, 128.04, 35.15, 35.2)],
            [rectangle(128.2, 128.25)]])
        b = Boundary(doc)
        self.assertTrue(b.contains("38030", 35.18, 128.0))
        self.assertTrue(b.contains("38030", 35.18, 127.95))
        self.assertFalse(b.contains("38030", 35.18, 128.03))
        self.assertFalse(b.contains("38030", 35.18, 128.17))
        self.assertTrue(b.contains("38030", 35.18, 128.22))
        self.assertFalse(b.contains("38030", float("nan"), 128.0))

    def test_wrong_crs_date_duplicate_and_open_ring_rejected(self):
        for key, value in [("coordinate_system", "EPSG:5179"), ("data_date", "2024-06-30")]:
            doc = boundary_document(); doc[key] = value
            with self.assertRaises(ValueError): Boundary(doc)
        doc = boundary_document(); doc["features"].append(copy.deepcopy(doc["features"][0]))
        with self.assertRaises(ValueError): Boundary(doc)
        doc = boundary_document(); doc["features"][0]["geometry"]["coordinates"][0].pop()
        with self.assertRaises(ValueError): Boundary(doc)

    def test_city_coverage_is_not_coarse_supported_window(self):
        self.assertIsNone(Boundary(boundary_document()).area_at(35.18, 128.3))
        self.assertEqual(Boundary(boundary_document()).area_at(35.18, 128.11), "38030020")


class GenerationTests(unittest.TestCase):
    def test_weights_change_shortlist_deterministically(self):
        p = transport_profile(edit())
        first = update_preferences(p, {"living": 90.0, "transport": 10.0}, confirm_weights=True)
        second = update_preferences(p, {"living": 10.0, "transport": 90.0}, confirm_weights=True)
        a = pool().generate(GenerationInput(profile=first, count=2, separation_m=0.0), orchestrator())
        b = pool().generate(GenerationInput(profile=second, count=2, separation_m=0.0), orchestrator())
        self.assertEqual(a["candidates"][0]["longitude"], 128.1)
        self.assertEqual(b["candidates"][0]["longitude"], 128.12)
        c = pool().generate(GenerationInput(profile=first, count=2, separation_m=0.0), orchestrator())
        self.assertEqual(a["selected"], c["selected"])
        self.assertEqual(a["module_ids"], ["living", "transport"])

    def test_each_module_receives_same_entire_pool(self):
        o = orchestrator(); calls = []
        for module in o.modules.values():
            original = module.run
            def record(request, cancel, original=original):
                calls.append([(c.id, c.latitude, c.longitude) for c in request.candidates])
                return original(request, cancel)
            module.run = record
        pool().generate(GenerationInput(profile=transport_profile(edit())), o)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(calls[0]), 3)

    def test_area_filter_diversity_and_no_unannounced_relaxation(self):
        result = pool().generate(GenerationInput(profile=profile(100, 0), count=3,
            area_codes=["38030020"], separation_m=5000.0), orchestrator())
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["searched_count"], 2)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["selected"][0]["area_code"], "38030020")

    def test_zero_weight_hard_constraint_filters_and_no_match_is_empty(self):
        p = profile(100, 0, hard=True)
        p.criteria[1].hard.value = 10.0
        result = pool().generate(GenerationInput(profile=p, separation_m=0.0), orchestrator())
        self.assertEqual(result["hard_failed_count"], 2)
        self.assertEqual(result["candidates"][0]["longitude"], 128.11)
        p.criteria[0].hard.value = 10.0
        result = pool().generate(GenerationInput(profile=p), orchestrator())
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["candidates"], [])

    def test_unknown_active_requirement_or_hard_never_silently_ignored(self):
        for hard in [False, True]:
            p = profile(100, 0, hard=hard)
            c = p.criteria[1 if hard else 0]
            c.module_id, c.metric = "housing", "rent_krw"
            original = p.model_dump()
            result = pool().generate(GenerationInput(profile=p), orchestrator())
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(result["candidates"], [])
            self.assertEqual(p.model_dump(), original)

    def test_unconfirmed_or_blocking_profile_not_selected(self):
        p = profile(); p.groups[0].source = "proposed"
        self.assertEqual(pool().generate(GenerationInput(profile=p), orchestrator())["status"], "needs_input")
        p = profile(); p.questions = [Question(id="q", text="답변 필요", reason="시험", criterion_ids=[], blocking=True)]
        self.assertEqual(pool().generate(GenerationInput(profile=p), orchestrator())["status"], "needs_input")

    def test_missing_utility_not_interpreted_as_default_distance(self):
        p = profile(); p.criteria[0].utility = None
        self.assertEqual(pool().generate(GenerationInput(profile=p), orchestrator())["status"], "unsupported")

    def test_conflicting_point_excluded_with_explicit_count(self):
        data = index(); data.conflicts["shops:a"] = "시험 분류 충돌"
        o = Orchestrator({"living": LivingModule(data)})
        result = pool().generate(GenerationInput(profile=profile(100, 0)), o)
        self.assertEqual(result["unverified_count"], 3)
        self.assertEqual(result["status"], "empty")

    def test_invalid_pool_or_area_rejected(self):
        for change in [{"origin": "user"}, {"longitude": 128.3}, {"latitude": float("nan")}]:
            d = pool_document(); d["points"][0]["candidate"].update(change)
            with self.assertRaises(ValueError): CandidatePool(d, Boundary(boundary_document()))
        for areas in [["wrong"], ["38030020", "38030020"]]:
            with self.assertRaises(ValueError): pool().generate(GenerationInput(profile=profile(), area_codes=areas), orchestrator())
        with self.assertRaises(ValueError): GenerationInput(profile=profile(), count=7)

    def test_stale_inventory_or_boundary_hash_rejected(self):
        with TemporaryDirectory() as root:
            paths = [Path(root) / n for n in ["pool.json", "boundary.json", "inventory.json"]]
            d = pool_document(); d.update(boundary_sha256="bad", inventory_sha256="bad")
            paths[0].write_text(json.dumps(d), encoding="utf-8")
            paths[1].write_text(json.dumps(boundary_document()), encoding="utf-8")
            paths[2].write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError): CandidatePool.load(*paths)


class CandidateHTTPTests(unittest.TestCase):
    def test_http_contract_session_and_existing_comparison_preserved(self):
        state = AppState(index(), candidate_pool=pool())
        token, session = state.session()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, Path(".env")))
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", server.server_port)
            payload = GenerationInput(profile=profile(100, 0), count=2, separation_m=0.0).model_dump_json().encode("utf-8")
            headers = {"Content-Type": "application/json", "X-Session": token}
            conn.request("POST", "/api/candidates", payload, headers); response = conn.getresponse()
            result = json.loads(response.read()); self.assertEqual(response.status, 200)
            self.assertEqual(result["status"], "completed"); self.assertEqual(len(result["candidates"]), 2)
            self.assertIsNone(session["comparison"])
            conn.request("POST", "/api/candidates", payload, {"Content-Type": "application/json"})
            response = conn.getresponse(); response.read(); self.assertEqual(response.status, 403)
            conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_real_acquired_pool_has_30_areas_and_exact_inside_points(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/processed/candidate-pool.json").exists():
            self.skipTest("prepare the official source first")
        p = CandidatePool.load(root / "data/processed/candidate-pool.json",
            root / "data/reference/jinju-boundary-2025.geojson", root / "data/processed/inventory.json")
        self.assertEqual(len(p.points), 654)
        self.assertEqual(len(p.metadata()["areas"]), 30)
        self.assertEqual(len({v["area_code"] for v in p.points.values()}), 30)
        self.assertEqual(p.document["excluded_occupied_cells_outside_center"], 5)


if __name__ == "__main__":
    unittest.main()
