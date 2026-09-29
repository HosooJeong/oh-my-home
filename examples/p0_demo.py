"""Synthetic P0 demonstration. No public data, model invocation or actual recommendation."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts import Candidate, CategoryResult, Evidence, NeedProfile
from app.orchestrator import Orchestrator
from app.preferences import reevaluate_preferences, update_preferences


class SyntheticModule:
    version = "synthetic-1"

    def __init__(self, module_id, values):
        self.id, self.values = module_id, values

    def run(self, request, cancel):
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status="completed",
            evidence=[Evidence(id=f"{candidate.id}_{self.id}", candidate_id=candidate.id,
                criterion_id=self.id, value=self.values[candidate.id], unit="fixture",
                status="verified", source_url="https://example.invalid/synthetic",
                source_record="example_only", data_date="synthetic",
                retrieved_at="synthetic", method="설명용 고정값", note="실제 자료가 아님")
                for candidate in request.candidates],
            unsupported_criterion_ids=[], questions=[], error_code=None)


def demonstration():
    profile = NeedProfile.model_validate({
        "schema_version":"1", "revision":1, "request":"설명용 가상 상황", "context":[],
        "groups":[{"id":id,"label":id,"weight":weight,"source":"user","reason":"설명용 설정"}
                  for id, weight in [("transport",70.0),("housing",30.0)]],
        "criteria":[{"id":id,"group_id":id,"module_id":id,"label":id,"need":"설명용 조건",
            "source_quote":"설명용 가상 상황","source":"user","importance":1.0,
            "importance_source":"user","metric":"synthetic_metric",
            "utility":{"direction":"higher","ideal":1.0,"limit":0.0,"unit":"fixture"},"hard":None}
            for id in ["transport","housing"]], "questions":[]})
    candidates = [Candidate(id=id,label=f"가상 후보 {id}",latitude=35.18,longitude=128.1,origin="fixture")
                  for id in ["a","b"]]
    main = Orchestrator({"transport":SyntheticModule("transport",{"a":.9,"b":.5}),
                         "housing":SyntheticModule("housing",{"a":.4,"b":.9})})
    first = main.run(profile, candidates)
    revised = update_preferences(profile,{"transport":30.0,"housing":70.0})
    second = reevaluate_preferences(profile,revised,candidates,first)
    return {"mode":"synthetic_demo_not_actual_recommendation", "initial_run":first,
            "changed_preferences":revised.model_dump(), "recalculated_report":second}


if __name__ == "__main__":
    print(json.dumps(demonstration(), ensure_ascii=False, indent=2))
