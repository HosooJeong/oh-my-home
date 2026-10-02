import csv
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

from app.contracts import ContextFact, Criterion, HardRule, PreferenceGroup, UtilityRule
from app.modules.housing import HousingIndex, HousingModule, HousingQuery, SOURCE, VERSION
from app.modules.living import LivingModule
from app.orchestrator import Orchestrator
from app.preferences import reevaluate_preferences, update_preferences
from app.web import AppState, CompareInput, PreferenceInput, make_handler
from tools.prepare_housing import money, prepare
from test_living import index, profile, candidates


def document():
    records = []
    for tenure in ("sale", "jeonse", "monthly"):
        for n in range(1, 6):
            records.append(dict(id=f"{tenure}:{n}", legal_area="가상동", area_m2=50.0,
                contract_date="2026-08-01", source_file="synthetic.csv", source_row=n + 2,
                tenure=tenure, contract="new" if n < 3 else "renewal",
                sale_krw=n * 100_000_000 if tenure == "sale" else None,
                deposit_krw=n * 10_000_000 if tenure != "sale" else None,
                monthly_krw=n * 100_000 if tenure == "monthly" else 0 if tenure == "jeonse" else None))
    return dict(version=VERSION, city_code="48170", source_url=SOURCE, period_start="2026-08-01",
                period_end="2026-08-31", retrieved_at="2026-09-30T12:00:00+09:00",
                raw_sources={"synthetic.csv": {"fixture": True}}, excluded={"cancelled_sale": 0, "invalid_row": 0},
                records=records)


class HousingTests(unittest.TestCase):
    def module(self):
        return HousingModule(HousingIndex(document()))

    def test_type_units_quantiles_and_separate_monthly_amounts(self):
        sale = self.module().reference(HousingQuery(tenure="sale"))
        self.assertEqual(sale.sample_count, 5)
        price = sale.distributions[1]
        self.assertEqual((price.minimum, price.q25, price.median, price.q75, price.maximum),
                         (100_000_000, 200_000_000, 300_000_000, 400_000_000, 500_000_000))
        monthly = self.module().reference(HousingQuery(tenure="monthly"))
        self.assertEqual([d.unit for d in monthly.distributions], ["m2", "KRW", "KRW/month"])
        self.assertEqual([d.median for d in monthly.distributions], [50.0, 30_000_000, 300_000])
        self.assertEqual(money("1,000.5"), 10_005_000)

    def test_region_area_contract_filters_and_small_empty_unavailable_are_not_zero(self):
        m = self.module()
        with self.assertRaises(ValueError):
            m.reference(HousingQuery(legal_area="없는동"))
        empty = m.reference(HousingQuery(area_min_m2=50.0, area_max_m2=60.0))
        self.assertEqual(empty.status, "available")
        empty = m.reference(HousingQuery(area_min_m2=0.0, area_max_m2=50.0))
        self.assertEqual((empty.status, empty.sample_count, empty.distributions), ("empty", 0, []))
        small = m.reference(HousingQuery(tenure="monthly", contract="new"))
        self.assertEqual((small.status, small.sample_count), ("insufficient", 2))
        self.assertTrue(all(d.median is None for d in small.distributions))
        self.assertEqual(HousingModule(HousingIndex()).reference().status, "unavailable")

    def test_reference_does_not_change_scored_evidence_ranking_or_reweight(self):
        p, cs, housing = profile(), candidates(), self.module()
        baseline = Orchestrator({"living": LivingModule(index())}).run(p, cs)
        run = Orchestrator({"living": LivingModule(index())}, {"housing": housing}).run(p, cs)
        self.assertEqual(run["report"], baseline["report"])
        self.assertEqual(run["references"][0]["profile_fingerprint"], p.fingerprint())
        self.assertEqual(len(run["modules"]), 1)
        class StaleReference:
            id = "housing"
            def run_reference(self, p, cs, cancel):
                return housing.run_reference(p, cs, cancel).model_copy(update={"profile_fingerprint": "wrong"})
        stale = Orchestrator({"living": LivingModule(index())}, {"housing": StaleReference()}).run(p, cs)
        self.assertEqual(stale["references"], [])
        self.assertEqual(stale["report"], baseline["report"])
        revised = update_preferences(p, criterion_importance={"grocery": 30.0, "convenience": 70.0})
        report = reevaluate_preferences(p, revised, cs, run)
        self.assertEqual(report["ranking"], ["b", "a"])
        self.assertTrue(all(len(a["details"]) == 2 for a in report["assessments"]))

    def test_actual_budget_stays_unknown_and_is_never_passed_by_region_price(self):
        p = profile()
        p.groups.append(PreferenceGroup(id="housing", label="집·비용", weight=10.0,
                                       source="user", reason="가상 필수 예산"))
        p.criteria.append(Criterion(id="budget", group_id="housing", module_id="housing", label="예산",
            need="가상 실제 집 예산", source_quote="가상 실제 집 예산", source="user", importance=100.0,
            importance_source="user", metric="actual_home_price_krw",
            utility=UtilityRule(direction="lower", ideal=100_000_000.0, limit=200_000_000.0, unit="KRW"),
            hard=HardRule(operator="lte", value=200_000_000.0)))
        housing = self.module()
        run = Orchestrator({"living": LivingModule(index()), "housing": housing}, {"housing": housing}).run(p, candidates())
        self.assertEqual(run["report"]["ranking_status"], "withheld")
        self.assertTrue(all(a["hard_unknown"] == ["budget"] for a in run["report"]["assessments"]))
        self.assertTrue(all(not m["evidence"] for m in run["modules"] if m["module_id"] == "housing"))

    def test_explicit_tenure_context_and_cancelled_reference(self):
        p = profile()
        p.context.append(ContextFact(key="housing_tenure", value="monthly", source_quote="가상 월세"))
        reference = self.module().run_reference(p, candidates(), Event())
        self.assertIn("월세", reference.scope)
        cancel = Event(); cancel.set()
        with self.assertRaises(InterruptedError):
            self.module().run_reference(p, candidates(), cancel)

    def test_city_and_explicit_dong_reference_are_one_nested_scope(self):
        p=profile()
        p.context.extend([ContextFact(key='housing_location',value='진주',source_quote='진주에서 비교해요.'),
            ContextFact(key='housing_location',value='가상동',source_quote='가상동 전세 참고'),
            ContextFact(key='housing_legal_area',value='가상동',source_quote='가상동 전세 참고'),
            ContextFact(key='housing_tenure',value='jeonse',source_quote='가상동 전세 참고')])
        before=p.model_dump()
        result=self.module().run_reference(p,candidates(),Event())
        self.assertEqual(result.status,'available')
        self.assertEqual(result.sample_count,5)
        self.assertIn('가상동',result.scope)
        self.assertIn('전세',result.scope)
        self.assertEqual(p.model_dump(),before)

    def test_different_dong_requests_still_require_scope_review(self):
        p=profile()
        p.context.extend([ContextFact(key='housing_location',value='다른동',source_quote='다른동도 참고'),
            ContextFact(key='housing_location',value='가상동',source_quote='가상동 전세 참고'),
            ContextFact(key='housing_legal_area',value='가상동',source_quote='가상동 전세 참고')])
        result=self.module().run_reference(p,candidates(),Event())
        self.assertEqual(result.status,'unsupported')
        self.assertEqual(result.sample_count,0)

    def test_tampered_index_wrong_city_date_amount_and_tenure_rejected(self):
        for mutate in [lambda d: d.update(city_code="38030"),
                lambda d: d["records"][0].update(contract_date="2025-01-01"),
                lambda d: d["records"][0].update(area_m2=float("nan")),
                lambda d: d["records"][0].update(monthly_krw=10),
                lambda d: d["records"][-1].update(monthly_krw=0)]:
            d = document(); mutate(d)
            with self.assertRaises(ValueError):
                HousingIndex(d)

    def test_official_csv_hash_period_cancel_and_invalid_rows(self):
        with TemporaryDirectory() as temp:
            paths = {}
            for kind in ("sale", "rent"):
                header = ["NO", "시군구", "전용면적(㎡)", "계약년월", "계약일"] + (
                    ["거래금액(만원)", "해제사유발생일"] if kind == "sale" else
                    ["전월세구분", "보증금(만원)", "월세금(만원)", "계약구분"])
                rows = [["1", "경상남도 진주시 가상동", "50", "202608", "01"] + (
                    ["1,000.5", "-"] if kind == "sale" else ["월세", "1,000", "30", "신규"])]
                if kind == "sale":
                    rows.append(["2", "경상남도 진주시 가상동", "50", "202608", "02", "5,000", "2026.08.03"])
                rows.append(["3", "서울특별시 가상구", "50", "202608", "01"] + rows[0][5:])
                stream=io.StringIO(); writer=csv.writer(stream)
                writer.writerow(["계약일자 : 2026-08-01 ~ 2026-08-31"])
                writer.writerow(header); writer.writerows(rows)
                data=stream.getvalue().encode("cp949")
                path=Path(temp)/f"{kind}.csv"; path.write_bytes(data); paths[kind]=path
                meta=dict(source_url=SOURCE, retrieved_at="2026-09-30T12:00:00+09:00", filename=path.name,
                    sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                    query=dict(srhSggCd="48170", srhThingNo="A", srhDelngSecd="1" if kind=="sale" else "2",
                               srhFromDt="2026-08-01", srhToDt="2026-08-31"))
                path.with_suffix('.json').write_text(json.dumps(meta),encoding='utf-8')
            prepared=prepare(paths)
            self.assertEqual(prepared["excluded"], {"cancelled_sale":1, "invalid_row":2})
            self.assertEqual(prepared["records"][0]["sale_krw"],10_005_000)
            self.assertEqual(prepared["records"][0]["source_row"],3)
            paths["sale"].write_bytes(paths["sale"].read_bytes()+b'x')
            with self.assertRaises(ValueError): prepare(paths)

    def test_http_reference_is_guarded_and_compare_contains_common_reference(self):
        state=AppState(index(), housing_index=HousingIndex(document()))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(state,Path('missing.env')))
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        client=HTTPConnection('127.0.0.1',server.server_port)
        try:
            client.request('GET','/api/bootstrap'); response=client.getresponse(); bootstrap=json.loads(response.read())
            self.assertTrue(bootstrap['data']['housing']['available'])
            headers={'Content-Type':'application/json','X-Session':bootstrap['token']}
            client.request('POST','/api/housing-reference',json.dumps({'tenure':'monthly'}),headers)
            response=client.getresponse(); body=json.loads(response.read())
            self.assertEqual((response.status,body['sample_count']), (200,5))
            client.request('POST','/api/housing-reference',json.dumps({'legal_area':'bad'}),headers)
            response=client.getresponse();response.read();self.assertEqual(response.status,400)
            client.request('POST','/api/housing-reference','{}',{'Content-Type':'application/json'})
            response=client.getresponse();response.read();self.assertEqual(response.status,403)
            run=state.compare(state.session(bootstrap['token'])[1],CompareInput(profile=profile(), candidates=candidates()))
            self.assertEqual(run['references'][0]['sample_count'],5)
            self.assertEqual(run['report']['ranking'], ['a','b'])
            self.assertTrue(all(f['kind']=='shops' for f in run['facilities'].values()))
            revised = state.preferences(state.session(bootstrap['token'])[1], PreferenceInput(
                run_id=run['run_id'], group_weights={'living':100.0},
                criterion_importance={'grocery':30.0,'convenience':70.0}, confirm_weights=True))
            self.assertEqual(revised['run']['references'][0]['profile_fingerprint'],revised['run']['profile_fingerprint'])
            self.assertEqual(revised['run']['references'][0]['snapshot_fingerprint'],run['references'][0]['snapshot_fingerprint'])
        finally:
            client.close();server.shutdown();server.server_close()


if __name__ == '__main__': unittest.main()
