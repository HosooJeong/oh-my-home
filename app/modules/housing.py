"""M3: historical apartment transactions, kept separate from point suitability."""
from datetime import date, datetime
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..contracts import CategoryResult, Contract, ReferenceDistribution, ReferenceResult, digest

SOURCE = "https://rt.molit.go.kr/pt/xls/xls.do?mobileAt="
VERSION = "jinju_apartment_transactions_v1"
LIMITATIONS = [
    "과거 신고 거래의 참고 분포야. 현재 매물·호가·개별 집의 가격·예산 충족 여부를 뜻하지 않아.",
    "가격은 점수·필수조건 판정·분석 지점 선별에 반영하지 않아. 같은 지역에서도 집마다 차이가 커.",
    "법정동 주소로 조회해. 지도 분석의 센서스 행정동과 연결하지 않았고, 후보별 가격을 추정하지 않아.",
    "계약일 기준이며 신고·정정·해제로 바뀔 수 있어. 공식 통계가 아니며 외부 통계 공개에는 신고일 기준 공식통계를 사용해야 해.",
    "아파트만 포함해. 면적·연식·층·단지·신규/갱신·공공임대 차이가 섞여 있고, 작은 표본은 대표성이 낮아.",
    "월세 보증금과 월세금은 같은 표본의 별도 분포야. 두 중앙값이 실제 한 계약의 조합인 것은 아니야.",
]


class HousingQuery(Contract):
    tenure: Literal["sale", "jeonse", "monthly"] = "sale"
    legal_area: Annotated[str, Field(max_length=100)] = ""
    area_min_m2: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] = 0.0
    area_max_m2: Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)] = 1000.0
    contract: Literal["all", "new", "renewal"] = "all"

    @model_validator(mode="after")
    def ordered(self):
        if self.area_min_m2 >= self.area_max_m2 or self.tenure == "sale" and self.contract != "all":
            raise ValueError("invalid housing filters")
        return self


def distribution(label, unit, values):
    ordered = sorted(values)
    def quantile(p):
        index = (len(ordered) - 1) * p
        left = int(index)
        right = min(left + 1, len(ordered) - 1)
        return round(ordered[left] + (ordered[right] - ordered[left]) * (index - left), 2)
    # No fabricated zero or price summary from a tiny sample.
    return ReferenceDistribution(label=label, unit=unit, count=len(values),
        **dict(zip(["minimum", "q25", "median", "q75", "maximum"],
                   [quantile(p) for p in [0, .25, .5, .75, 1]] if len(values) >= 5 else [None] * 5)))


class HousingIndex:
    def __init__(self, document=None):
        self.document = document
        self.records = []
        if document is None:
            return
        if document["version"] != VERSION or document["city_code"] != "48170" or document["source_url"] != SOURCE:
            raise ValueError("invalid housing source")
        start, end = date.fromisoformat(document["period_start"]), date.fromisoformat(document["period_end"])
        if not 0 <= (end - start).days < 366:
            raise ValueError("invalid housing period")
        datetime.fromisoformat(document["retrieved_at"])
        ids = set()
        for row in document["records"]:
            day = date.fromisoformat(row["contract_date"])
            if (row["id"] in ids or not start <= day <= end or not row["legal_area"]
                    or row["tenure"] not in ("sale", "jeonse", "monthly")
                    or row["contract"] not in ("new", "renewal", "unknown")
                    or row["source_file"] not in document["raw_sources"]
                    or type(row["source_row"]) is not int or row["source_row"] < 2
                    or not 0 < row["area_m2"] <= 1000):
                raise ValueError("untraceable housing row")
            prices = [row["sale_krw"], row["deposit_krw"], row["monthly_krw"]]
            if any(v is not None and (type(v) is not int or v < 0) for v in prices):
                raise ValueError("invalid price")
            if row["tenure"] == "sale":
                valid = prices[0] is not None and prices[0] > 0 and prices[1:] == [None, None]
            else:
                valid = prices[0] is None and prices[1] is not None and prices[2] is not None and (
                    prices[2] == 0 and prices[1] > 0 if row["tenure"] == "jeonse" else prices[2] > 0)
            if not valid:
                raise ValueError("price and tenure differ")
            ids.add(row["id"])
            self.records.append(row)

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def metadata(self):
        if self.document is None:
            return {"available": False, "source_url": SOURCE, "limitations": LIMITATIONS}
        d = self.document
        return {"available": True, "source_url": SOURCE, "period_start": d["period_start"],
                "period_end": d["period_end"], "retrieved_at": d["retrieved_at"],
                "record_count": len(self.records), "excluded": d["excluded"],
                "counts": {t: sum(r["tenure"] == t for r in self.records) for t in ("sale", "jeonse", "monthly")},
                "legal_areas": sorted({r["legal_area"] for r in self.records}),
                "raw_sources": d["raw_sources"], "snapshot_fingerprint": digest(d), "limitations": LIMITATIONS}


class HousingModule:
    id, version = "housing", "m3-reference-1"

    def __init__(self, index):
        self.index = index

    def run(self, request, cancel):
        # Budget or house requirements stay unknown; no regional median passes them.
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status="partial", evidence=[],
            unsupported_criterion_ids=[c.id for c in request.criteria], questions=[],
            error_code="housing_reference_only")

    def reference(self, query=None, profile=None, candidates=None, cancel=None):
        query = query or HousingQuery()
        query = HousingQuery.model_validate(query.model_dump())
        areas = {r["legal_area"] for r in self.index.records}
        if query.legal_area and query.legal_area not in areas:
            raise ValueError("unknown legal area")
        d = self.index.document or {}
        tenure_label = {"sale": "매매", "jeonse": "전세", "monthly": "월세"}[query.tenure]
        scope = f"진주시 {query.legal_area or '전체'} · 아파트 {tenure_label} · 전용 {query.area_min_m2:g}㎡ 이상 {query.area_max_m2:g}㎡ 미만"
        if query.contract != "all":
            scope += " · " + {"new": "신규", "renewal": "갱신"}[query.contract]
        rows = []
        for row in self.index.records:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            if (row["tenure"] == query.tenure and (not query.legal_area or row["legal_area"] == query.legal_area)
                    and query.area_min_m2 <= row["area_m2"] < query.area_max_m2
                    and (query.contract == "all" or row["contract"] == query.contract)):
                rows.append(row)
        measurements = []
        if rows:
            measurements.append(distribution("전용면적", "m2", [r["area_m2"] for r in rows]))
            if query.tenure == "sale":
                measurements.extend([distribution("매매금액", "KRW", [r["sale_krw"] for r in rows]),
                    distribution("전용 ㎡당 매매금액", "KRW/m2", [r["sale_krw"] / r["area_m2"] for r in rows])])
            else:
                measurements.append(distribution("보증금", "KRW", [r["deposit_krw"] for r in rows]))
                if query.tenure == "monthly":
                    measurements.append(distribution("월세금", "KRW/month", [r["monthly_krw"] for r in rows]))
        return ReferenceResult(module_id=self.id, module_version=self.version,
            profile_fingerprint=profile.fingerprint() if profile else None,
            candidates_fingerprint=digest([c.model_dump() for c in candidates]) if candidates else None,
            status="unavailable" if not d else "empty" if not rows else "insufficient" if len(rows) < 5 else "available",
            query_fingerprint=digest(query.model_dump()), scope=scope, sample_count=len(rows), distributions=measurements,
            contract_counts={k: sum(r["contract"] == k for r in rows) for k in ("new", "renewal", "unknown")},
            source_url=SOURCE, period_start=d.get("period_start"), period_end=d.get("period_end"),
            retrieved_at=d.get("retrieved_at"), snapshot_fingerprint=digest(d) if d else None, limitations=LIMITATIONS)

    def run_reference(self, profile, candidates, cancel):
        # Only exact explicit context values; no guessed budget-to-price conversions.
        facts = {f.key: f.value for f in profile.context}
        tenure = facts.get("housing_tenure", "sale")
        query = HousingQuery(tenure=tenure if tenure in ("sale", "jeonse", "monthly") else "sale")
        return self.reference(query, profile, candidates, cancel)
