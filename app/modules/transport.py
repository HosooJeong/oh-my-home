"""M2: distance to registered Jinju bus stops; no route or service inference."""
from datetime import date, datetime, timezone
import math

from ..contracts import CategoryResult, Evidence, digest
from ..geo import distance_m, in_supported_window

METRIC = "bus_stop_straight_line_distance_m"
SOURCE = "https://www.data.go.kr/data/15067528/fileData.do"


class StopIndex:
    def __init__(self, document):
        self.generated_at = document["generated_at"]
        self.records = {}
        for row in document["records"]:
            if row["kind"] != "bus":
                continue
            if (not math.isfinite(row["lat"]) or not math.isfinite(row["lon"])
                    or not in_supported_window(row["lat"], row["lon"])):
                raise ValueError("invalid stop coordinates")
            if row["id"] in self.records:
                raise ValueError("duplicate stop identity")
            if (not row["source_id"] or row["id"] != "bus:" + row["source_id"]
                    or not row["name"].strip() or row["source_url"] != SOURCE
                    or date.fromisoformat(row["date"]).isoformat() != row["date"]
                    or type(row["source_row"]) is not int or row["source_row"] < 2):
                raise ValueError("untraceable stop inventory")
            self.records[row["id"]] = row

    def nearest(self, candidate):
        if not in_supported_window(candidate.latitude, candidate.longitude) or not self.records:
            return None
        row = min(self.records.values(), key=lambda r: (
            distance_m(candidate.latitude, candidate.longitude, r["lat"], r["lon"]), r["id"]))
        return row, distance_m(candidate.latitude, candidate.longitude, row["lat"], row["lon"])

    def metadata(self):
        return {"stop_count": len(self.records), "source_url": SOURCE,
                "data_dates": sorted({r["date"] for r in self.records.values()}),
                "generated_at": self.generated_at,
                "limitations": "등록된 정류장까지 직선거리예요. 도보 경로·노선·방향·배차·현재 운행은 미확인이에요."}


class TransportModule:
    id, version = "transport", "m2-1"

    def __init__(self, index):
        self.index = index

    def run(self, request, cancel):
        evidence, unsupported = [], []
        now = datetime.now(timezone.utc).isoformat()
        for criterion in request.criteria:
            if criterion.metric != METRIC or (criterion.utility and (
                    criterion.utility.unit != "m" or criterion.utility.direction != "lower")):
                unsupported.append(criterion.id)
                continue
            for candidate in request.candidates:
                if cancel.is_set():
                    raise InterruptedError("cancelled")
                nearest = self.index.nearest(candidate)
                row, value = nearest if nearest else (None, None)
                note = (f"{row['name']} · 정류장번호 {row['source_id']} · 원본 CSV {row['source_row']}행. "
                        "진주 자료에 등록된 정류장 중 최단 직선거리. 정류장 주소 컬럼 없음. "
                        "도보 경로·횡단 가능 여부·탑승 방향·노선·배차·현재 운행은 미확인."
                        if row else "지원 좌표 범위 밖이거나 정류장 자료가 없어 거리를 확인할 수 없어요.")
                evidence.append(Evidence(id="transport_" + digest([candidate.id, criterion.id])[:24],
                    candidate_id=candidate.id, criterion_id=criterion.id,
                    value=round(value, 3) if value is not None else None, unit="m",
                    status="verified" if row else "missing", source_url=row["source_url"] if row else None,
                    source_record=row["id"] if row else None, data_date=row["date"] if row else None,
                    retrieved_at=now if row else None,
                    method="haversine_mean_earth_6371008.8m / jinju_bus_inventory / nearest_v1", note=note))
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(),
            status="partial" if unsupported or any(e.status != "verified" for e in evidence) else "completed",
            evidence=evidence, unsupported_criterion_ids=unsupported, questions=[], error_code=None)
