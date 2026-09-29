import json
from threading import Event
import unittest

from pydantic import ValidationError
from app.contracts import (Candidate, CategoryResult, Criterion, Evidence, HardRule,
                           NeedProfile, PreferenceGroup, Question, UtilityRule, output_schema)
from app.evaluation import evaluate, utility
from app.orchestrator import Orchestrator


def profile(transport=70.0, housing=30.0):
    return NeedProfile(schema_version="1", revision=1, request="가상 시험: 교통과 비용 비교", context=[],
        groups=[PreferenceGroup(id=id, label=id, weight=weight, source="user", reason="가상 시험 지정값")
                for id, weight in [("transport", transport), ("housing", housing)]],
        criteria=[Criterion(id=id, group_id=id, module_id=id, label=id, need="가상 비교",
            source_quote="교통과 비용", source="user", importance=1.0, importance_source="user",
            metric="fixture_metric", utility=UtilityRule(direction="higher", ideal=1.0, limit=0.0, unit="fixture"),
            hard=None) for id in ("transport", "housing")], questions=[])


def candidates():
    return [Candidate(id=id, label="가상 후보 " + id, latitude=35.18, longitude=128.1, origin="fixture")
            for id in ("a", "b")]


def fact(candidate, criterion, value, **overrides):
    fields = dict(id=candidate + "_" + criterion, candidate_id=candidate, criterion_id=criterion,
        value=value, unit="fixture", status="verified", source_url="https://example.invalid/fixture",
        source_record="synthetic", data_date="2026-09-30", retrieved_at="2026-09-30T12:00:00+09:00",
        method="가상 시험값", note="실제 주거 후보·공공자료가 아님")
    return Evidence(**(fields | overrides))


def evidence():
    return [fact("a", "transport", .9), fact("a", "housing", .4),
            fact("b", "transport", .5), fact("b", "housing", .9)]


class FixtureModule:
    """Test-only adapter; never registered by the application's intake command."""
    version = "fixture-1"

    def __init__(self, id, mutate=None):
        self.id, self.mutate, self.calls = id, mutate, 0

    def run(self, request, cancel):
        self.calls += 1
        result = CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status="completed",
            evidence=[e for e in evidence() if e.criterion_id == self.id],
            unsupported_criterion_ids=[], questions=[], error_code=None)
        return self.mutate(result) if self.mutate else result


class ContractTests(unittest.TestCase):
    def test_invalid_weights_nan_and_unknown_fields_rejected(self):
        for value in [-1, float("nan"), float("inf"), True, "50"]:
            data = profile().model_dump()
            data["groups"][0]["weight"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                NeedProfile.model_validate(data)
        with self.assertRaises(ValidationError):
            NeedProfile.model_validate(profile().model_dump() | {"fake": True})

    def test_duplicate_and_unknown_criterion_groups_rejected(self):
        for mutation in (lambda d: d["criteria"].append(d["criteria"][0]),
                         lambda d: d["criteria"][0].update(group_id="missing")):
            data = profile().model_dump()
            mutation(data)
            with self.assertRaises(ValidationError):
                NeedProfile.model_validate(data)

    def test_extension_is_retained_and_missing_is_not_zero(self):
        data = profile().model_dump()
        data["groups"].append(dict(id="music", label="악기 연습", weight=20.0, source="proposed", reason="기타 니즈"))
        data["criteria"].append(dict(data["criteria"][0], id="practice", group_id="music", module_id="extension", utility=None))
        p = NeedProfile.model_validate(data)
        report = evaluate(p, candidates(), evidence())
        self.assertTrue(report["provisional"])
        self.assertIsNone(report["assessments"][0]["score"])
        self.assertEqual(report["assessments"][0]["details"][-1]["criterion_id"], "practice")

    def test_verified_fact_requires_traceable_source(self):
        for override in ({"source_url":None}, {"source_record":None}, {"value":None},
                         {"source_url":"javascript:alert(1)"}):
            data = fact("a", "transport", .9).model_dump() | override
            with self.subTest(override=override), self.assertRaises(ValidationError):
                Evidence.model_validate(data)

    def test_schema_is_closed_and_nullable_fields_are_required(self):
        schema = output_schema(NeedProfile)
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("hard", schema["$defs"]["Criterion"]["required"])
        self.assertIn({"type": "null"}, schema["$defs"]["Criterion"]["properties"]["hard"]["anyOf"])


class EvaluationTests(unittest.TestCase):
    def test_same_facts_change_order_with_personal_weights(self):
        first = evaluate(profile(), candidates(), evidence())
        second = evaluate(profile(30.0, 70.0), candidates(), evidence())
        self.assertEqual(first["ranking"], ["a", "b"])
        self.assertEqual(second["ranking"], ["b", "a"])
        self.assertEqual([a["score"] for a in first["assessments"]], [75, 62])
        self.assertEqual([a["score"] for a in second["assessments"]], [55, 78])

    def test_missing_evidence_keeps_original_weight_and_score_interval(self):
        report = evaluate(profile(), candidates(), evidence()[:1])
        a = report["assessments"][0]
        self.assertIsNone(a["score"])
        self.assertEqual(a["coverage"], .7)
        self.assertEqual(a["score_range"], [63, 93])
        self.assertIsNone(a["details"][1]["contribution"])
        self.assertEqual(report["ranking"], [])

    def test_hard_failure_cannot_be_offset_by_high_other_score(self):
        p = profile()
        p.criteria[1].hard = HardRule(operator="gte", value=.8)
        report = evaluate(p, candidates(), evidence())
        self.assertEqual(report["ranking"], ["b"])
        self.assertEqual(report["assessments"][0]["eligibility"], "ineligible")

    def test_missing_hard_constraint_blocks_verified_ranking(self):
        p = profile()
        p.criteria[1].hard = HardRule(operator="gte", value=.8)
        report = evaluate(p, candidates(), evidence()[:1])
        self.assertEqual(report["assessments"][0]["eligibility"], "unverified")
        self.assertEqual(report["ranking"], [])

    def test_wrong_units_conflict_and_missing_are_not_scored(self):
        for override in ({"unit": "minutes"}, {"status": "conflicting"}, {"status": "missing", "value": None}):
            ev = evidence()
            ev[0] = fact("a", "transport", .9).model_copy(update=override)
            report = evaluate(profile(), candidates(), ev)
            self.assertIsNone(report["assessments"][0]["score"])

    def test_duplicate_evidence_is_not_double_counted(self):
        with self.assertRaises(ValueError):
            evaluate(profile(), candidates(), evidence() + evidence()[:1])

    def test_utility_is_personal_continuous_and_clamped(self):
        rule = UtilityRule(direction="lower", ideal=300.0, limit=800.0, unit="m")
        self.assertEqual([utility(x, rule) for x in (100, 300, 550, 800, 900)], [1, 1, .5, 0, 0])
        target = UtilityRule(direction="target", ideal=20.0, limit=10.0, unit="C")
        self.assertEqual([utility(x, target) for x in (10, 15, 20, 25, 30)], [0, .5, 1, .5, 0])

    def test_proposed_weights_do_not_become_confirmed_ranking(self):
        p = profile()
        p.groups[0].source = "proposed"
        report = evaluate(p, candidates(), evidence())
        self.assertTrue(report["provisional"])
        self.assertEqual(report["ranking_status"], "withheld")


class OrchestratorTests(unittest.TestCase):
    def test_dispatch_and_merge_two_modules(self):
        modules = {id: FixtureModule(id) for id in ("transport", "housing")}
        run = Orchestrator(modules).run(profile(), candidates())
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["report"]["ranking"], ["a", "b"])
        self.assertEqual([m.calls for m in modules.values()], [1, 1])

    def test_zero_weight_unrequested_module_is_not_called(self):
        modules = {id: FixtureModule(id) for id in ("transport", "housing")}
        p = profile(100.0, 0.0)
        p.groups[1].source = "proposed"
        run = Orchestrator(modules).run(p, candidates())
        self.assertEqual(modules["housing"].calls, 0)
        self.assertEqual(run["status"], "completed")
        self.assertFalse(run["report"]["provisional"])

    def test_module_receives_global_weights_and_priority_order(self):
        received = []
        class Inspect(FixtureModule):
            def run(self, request, cancel):
                received.append((self.id, request.weights[0].weight))
                return super().run(request, cancel)
        Orchestrator({id:Inspect(id) for id in ("transport","housing")}).run(profile(30.0,70.0),candidates())
        self.assertEqual(received, [("housing",.7),("transport",.3)])

    def test_module_followup_can_withhold_ranking(self):
        def ask(result):
            result.questions = [Question(id="required",text="확인 필요",reason="충돌",criterion_ids=["transport"],blocking=True)]
            return result
        run=Orchestrator({"transport":FixtureModule("transport",ask),"housing":FixtureModule("housing")}).run(profile(),candidates())
        self.assertEqual(run["status"],"awaiting_input")
        self.assertEqual(run["report"]["ranking"],[])

    def test_invalid_boolean_metric_does_not_abort_other_module(self):
        p = profile()
        p.criteria[0].utility = UtilityRule(direction="boolean", ideal=1.0, limit=0.0, unit="fixture")
        run = Orchestrator({id:FixtureModule(id) for id in ("transport","housing")}).run(p,candidates())
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["modules"][0]["status"], "failed")
        self.assertEqual(run["modules"][1]["status"], "completed")

    def test_missing_module_preserves_weight_and_partial_result(self):
        run = Orchestrator({"transport": FixtureModule("transport")}).run(profile(), candidates())
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["report"]["assessments"][0]["coverage"], .7)

    def test_stale_module_response_is_rejected_without_losing_other_module(self):
        def stale(result):
            return result.model_copy(update={"request_fingerprint": "old"})
        run = Orchestrator({"transport": FixtureModule("transport", stale),
                            "housing": FixtureModule("housing")}).run(profile(), candidates())
        self.assertEqual(run["modules"][0]["status"], "failed")
        self.assertEqual(run["modules"][1]["status"], "completed")
        self.assertEqual(run["report"]["assessments"][0]["coverage"], .3)

    def test_foreign_evidence_and_duplicates_are_rejected(self):
        def invalid(result):
            result.evidence.append(fact("b", "housing", .8))
            return result
        run = Orchestrator({"transport": FixtureModule("transport", invalid)}).run(profile(), candidates())
        self.assertEqual(run["modules"][0]["status"], "failed")

    def test_blocking_question_does_not_call_modules(self):
        p = profile()
        p.questions = [Question(id="where", text="후보 지역은?", reason="후보 범위 필요", criterion_ids=[], blocking=True)]
        module = FixtureModule("transport")
        run = Orchestrator({"transport": module}).run(p, candidates())
        self.assertEqual(run["status"], "awaiting_input")
        self.assertEqual(module.calls, 0)

    def test_cancellation_before_and_after_module_has_no_final_ranking(self):
        cancelled = Event()
        cancelled.set()
        self.assertEqual(Orchestrator({}).run(profile(), candidates(), cancelled)["status"], "cancelled")
        cancelled.clear()
        class Cancelling(FixtureModule):
            def run(self, request, cancel):
                result = super().run(request, cancel)
                cancel.set()
                return result
        run = Orchestrator({"transport": Cancelling("transport")}).run(profile(), candidates(), cancelled)
        self.assertEqual(run["status"], "cancelled")
        self.assertIsNone(run["report"])


if __name__ == "__main__":
    unittest.main()
