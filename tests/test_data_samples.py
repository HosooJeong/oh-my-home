import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_samples import coordinate_error, process, distinct_nearby, distance_m


class DataValidationTests(unittest.TestCase):
    def test_bad_source_latitude_is_quarantined_without_repair(self):
        self.assertEqual(coordinate_error("32.216844", "128.13345"), "outside_broad_jinju_screen")
        self.assertIsNone(coordinate_error("35.216844", "128.13345"))

    def test_non_finite_and_missing_coordinates_are_not_accepted(self):
        for lat, lon in [("", "128"), ("nan", "128"), ("inf", "128"), ("35", "181")]:
            self.assertIsNotNone(coordinate_error(lat, lon))

    def test_cctv_repeated_rows_remain_traceable(self):
        header = "관리기관명,소재지지번주소,설치목적구분,카메라대수,위도,경도\n"
        duplicate = "경상남도 진주시청,진주시 테스트,생활방범,1,35.18,128.1\n"
        bad = "경상남도 진주시청,진주시 원본오류,생활방범,1,32.216844,128.13345\n"
        source = {"id":"cctv","title":"test","version":"test","sha256":"test",
                  "catalog_modified":"2026-09-16","source_url":"https://example.test"}
        records, excluded, stats = process(source, io.StringIO(header + duplicate * 2 + bad))
        self.assertEqual((stats["jinju_rows"], len(records), len(excluded)), (3, 2, 1))
        self.assertEqual(stats["exact_duplicate_extra_rows"], 1)
        self.assertNotEqual(records[0]["id"], records[1]["id"])
        self.assertEqual(excluded[0]["original"]["위도"], "32.216844")
        self.assertEqual(excluded[0]["row_number"], 4)
        self.assertEqual(len(distinct_nearby(records, records[0])), 1)

    def test_city_filter_does_not_use_name_substring_only(self):
        header = "정류장번호,정류장명,도시명,위도,경도,정보수집일\n"
        rows = "A,진주시청,다른 도시,35.18,128.1,2025-10-31\nB,중앙,경상남도 진주시,35.18,128.1,2025-10-31\n"
        source = {"id":"bus","title":"test","version":"test","sha256":"test","source_url":"https://example.test"}
        records, excluded, stats = process(source, io.StringIO(header + rows))
        self.assertEqual(stats["input_rows"], 2)
        self.assertEqual([r["source_id"] for r in records], ["B"])

    def test_sample_radius_does_not_silently_fill_from_far_away(self):
        anchor={"id":"a","lat":35.18,"lon":128.1}
        far={"id":"b","lat":35.4,"lon":128.1}
        self.assertGreater(distance_m(anchor, far), 2000)
        self.assertEqual(distinct_nearby([far], anchor), [])

    def test_real_sample_rows_match_inventory(self):
        root=Path(__file__).resolve().parents[1]/"data/processed"
        if not (root/"preview.json").exists():
            self.skipTest("Run build_samples.py for source-backed integration check")
        preview=json.loads((root/"preview.json").read_text(encoding="utf-8"))
        inventory=json.loads((root/"inventory.json").read_text(encoding="utf-8"))
        indexed={r["id"]:r for r in inventory["records"]}
        for region in preview["regions"]:
            self.assertEqual(len(region["samples"]),9)
            for r in region["samples"]:
                for key in ["lat","lon","name","address","source_row","date"]:
                    self.assertEqual(r[key],indexed[r["id"]][key])
                self.assertIsNone(coordinate_error(r["lat"],r["lon"]))


if __name__ == "__main__":
    unittest.main()
