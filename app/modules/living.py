"""M1: nearest grocery facilities in the complete, locally acquired Jinju inventory."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from ..contracts import CategoryResult, Evidence, digest
from ..geo import distance_m, in_supported_window

METRICS = {
    "grocery_straight_line_distance_m": "supermarket",
    "convenience_straight_line_distance_m": "convenience",
    # The explicit straight-line metric produced by the P0 verified interview.
    "house_to_grocery_straight_line_distance_m": "supermarket",
}
CONVENIENCE_BRAND = re.compile(r"^(gs25|지에스25|cu|씨유|세븐일레븐|이마트24|미니스톱)", re.I)
SUPERMARKET_BRAND = re.compile(r"^(gs더프레시|지에스더프레시|gs수퍼|이마트에브리데이|홈플러스익스프레스)", re.I)
CLOTHING_BRAND = re.compile(r'^(?:신성통상)?(?:topten|탑텐)', re.I)
SOURCE = "https://www.data.go.kr/data/15083033/fileData.do"


class ShopIndex:
    def __init__(self, document):
        self.generated_at = document["generated_at"]
        self.records, self.groups = {}, {"supermarket": [], "convenience": []}
        self.excluded_ambiguous = 0
        self.conflicts = {}
        for row in document["records"]:
            if row["kind"] != "shops":
                continue
            if (not math.isfinite(row["lat"]) or not math.isfinite(row["lon"])
                    or not in_supported_window(row["lat"], row["lon"])):
                raise ValueError("invalid inventory coordinates")
            if row["id"] in self.records:
                raise ValueError("duplicate shop identity")
            if row["source_url"] != SOURCE or not row["date"]:
                raise ValueError("untraceable inventory")
            self.records[row["id"]] = row
            compact_name = re.sub(r"\s+", "", row["name"])
            if row['detail'] in ('슈퍼마켓','편의점') and CLOTHING_BRAND.match(compact_name):
                self.conflicts[row['id']]='의류 브랜드 상호와 장보기 업종의 충돌이 의심돼요. 동일 시설 대조 전에는 장보기 근거로 확정하지 않아요.'
            if row["detail"] in ("슈퍼마켓", "편의점") and "전자담배" in compact_name:
                self.conflicts[row["id"]] = "상호에 전자담배가 포함돼 업종 분류와 충돌이 의심돼요. 장보기 시설인지 확인이 필요해요."
            if row["detail"] == "편의점" and SUPERMARKET_BRAND.match(compact_name):
                self.conflicts[row["id"]] = "편의점 업종이지만 슈퍼마켓 브랜드 상호여서 분류 확인이 필요해요."
            if row["detail"] == "편의점":
                self.groups["convenience"].append(row)
            elif row["detail"] == "슈퍼마켓":
                if CONVENIENCE_BRAND.match(compact_name):
                    self.excluded_ambiguous += 1
                else:
                    self.groups["supermarket"].append(row)

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def nearest(self, candidate, kind):
        if not in_supported_window(candidate.latitude, candidate.longitude):
            return None
        rows = self.groups[kind]
        if not rows:
            return None
        row = min(rows, key=lambda r: (distance_m(candidate.latitude, candidate.longitude, r["lat"], r["lon"]), r["id"]))
        return row, distance_m(candidate.latitude, candidate.longitude, row["lat"], row["lon"])

    def metadata(self):
        return {"shop_count": len(self.records), "counts": {k: len(v) for k, v in self.groups.items()},
                "excluded_ambiguous": self.excluded_ambiguous, "conflicting_count": len(self.conflicts),
                'classification_review_queue':[{'id':id,'name':self.records[id]['name'],'source_detail':self.records[id]['detail'],
                    'source_url':self.records[id]['source_url'],'reason':reason} for id,reason in sorted(self.conflicts.items())],
                "generated_at": self.generated_at,
                "source_url": SOURCE, "data_dates": sorted({r["date"] for r in self.records.values()}),
                "filter": "슈퍼마켓 업종 중 편의점 브랜드 접두어를 제외. 편의점은 원본 편의점 업종만 사용.",
                "limitations": "진주 자료에 등록된 시설의 직선거리예요. 도보 경로·재고·현재 영업·휴폐업은 확인되지 않았어요."}


class LivingModule:
    id, version = "living", "m1-2"

    def __init__(self, index):
        self.index = index

    def run(self, request, cancel):
        evidence, unsupported = [], []
        now = datetime.now(timezone.utc).isoformat()
        for criterion in request.criteria:
            kind = METRICS.get(criterion.metric)
            # Don't turn walking minutes or a Boolean into metres just to produce a score.
            if kind is None or (criterion.utility and
                                (criterion.utility.unit != "m" or criterion.utility.direction != "lower")):
                unsupported.append(criterion.id)
                continue
            for candidate in request.candidates:
                if cancel.is_set():
                    raise InterruptedError("cancelled")
                nearest = self.index.nearest(candidate, kind)
                row, value = nearest if nearest else (None, None)
                conflict = self.index.conflicts.get(row["id"]) if row else None
                note = (f"{row['name']} · 원본 업종 {row['detail']} · 원본 {row['source_member']} {row['source_row']}행. "
                        "진주 자료에 등록된 시설 중 최단 직선거리. 도보 거리·재고·현재 영업은 미확인."
                        if row else "지원 좌표 범위 밖이거나 해당 업종 자료가 없어 거리를 확인할 수 없어요.")
                if conflict:
                    note = conflict + " " + note
                evidence.append(Evidence(id="living_" + digest([candidate.id, criterion.id])[:24],
                    candidate_id=candidate.id, criterion_id=criterion.id,
                    value=round(value, 3) if value is not None else None, unit="m",
                    status="conflicting" if conflict else "verified" if row else "missing", source_url=row["source_url"] if row else None,
                    source_record=row["id"] if row else None, data_date=row["date"] if row else None,
                    retrieved_at=now if row else None,
                    method="haversine_mean_earth_6371008.8m / jinju_inventory / industry_filter_v1 / name_conflict_v2", note=note))
        partial = unsupported or any(e.status != "verified" for e in evidence)
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status="partial" if partial else "completed",
            evidence=evidence, unsupported_criterion_ids=unsupported, questions=[], error_code=None)
