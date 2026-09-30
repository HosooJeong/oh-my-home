"""Local category comparison. Bounded, in-memory sessions; no personal-input files."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
from threading import Event, Lock, Thread
import time
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field

from .codex_runner import CodexRunner, RunnerError
from .contracts import Candidate, Contract, InterviewTurn, NeedProfile, Weight, digest
from .candidates import CandidatePool, GenerationInput
from .intake import prepare_profile
from .reviews import ReviewInput, map_links, research_reviews
from .modules.living import LivingModule, ShopIndex
from .modules.transport import StopIndex, TransportModule
from .modules.housing import HousingIndex, HousingModule, HousingQuery
from .modules.education import EducationIndex, EducationModule
from .education_preferences import EducationInput, education_profile
from .modules.safety import CctvIndex, SafetyModule, context_value
from .safety_preferences import SafetyInput, safety_profile
from .safety_research import research_safety
from .modules.leisure import LeisureIndex, LeisureModule, PARK_METRIC, LIBRARY_METRIC, HOBBY_METRIC, ACTIVITIES
from .leisure_preferences import LeisureInput, leisure_profile
from .leisure_research import research_leisure
from .geo import distance_m
from .transport_preferences import TransportInput, transport_profile
from .orchestrator import Orchestrator
from .preferences import reevaluate_preferences, update_preferences
from tools.preview.server import sdk_key

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"


class CompareInput(Contract):
    profile: NeedProfile
    candidates: Annotated[list[Candidate], Field(min_length=2, max_length=6)]


class IntakeInput(Contract):
    request_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
    request: Annotated[str, Field(min_length=1, max_length=4000)]
    previous: NeedProfile | None = None
    answers: Annotated[list[InterviewTurn], Field(max_length=10)] = []


class PreferenceInput(Contract):
    run_id: str
    group_weights: dict[str, Weight]
    criterion_importance: dict[str, Weight]
    confirm_weights: bool


class SupplementInput(Contract):
    request_id: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
    run_id: str


class QuickInput(Contract):
    ideal: Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]
    limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)]
    supermarket_weight: Weight
    convenience_weight: Weight
    mandatory_limit: bool


def quick_profile(data: QuickInput):
    if data.ideal >= data.limit or data.supermarket_weight + data.convenience_weight == 0:
        raise ValueError("invalid quick preferences")
    request = (f"마트와 편의점의 직선거리를 비교해 줘. {data.ideal:g}m 이내가 이상적이고 "
               f"{data.limit:g}m 이상은 만족도가 0이야. 마트 중요도 {data.supermarket_weight:g}, "
               f"편의점 중요도 {data.convenience_weight:g}. "
               + (f"두 시설 모두 반드시 {data.limit:g}m 이내여야 해." if data.mandatory_limit else "필수 제한은 없어."))
    return NeedProfile.model_validate({"schema_version": "1", "revision": 1, "request": request,
        "context": [], "groups": [{"id": "living", "label": "생활·건강", "weight": 100.0,
                                    "source": "user", "reason": "직접 선택한 장보기 조건"}],
        "criteria": [{"id": id, "group_id": "living", "module_id": "living", "label": label,
            "need": label + "까지의 직선거리", "source_quote": request, "source": "user",
            "importance": weight, "importance_source": "user", "metric": metric,
            "utility": {"direction": "lower", "ideal": data.ideal, "limit": data.limit, "unit": "m"},
            "hard": {"operator": "lte", "value": data.limit} if data.mandatory_limit else None}
            for id, label, metric, weight in [
                ("grocery", "마트", "grocery_straight_line_distance_m", data.supermarket_weight),
                ("convenience", "편의점", "convenience_straight_line_distance_m", data.convenience_weight)]],
        "questions": []})


class AppState:
    def __init__(self, index, runner_factory=CodexRunner, stop_index=None, candidate_pool=None, housing_index=None, education_index=None, safety_index=None, leisure_index=None):
        self.index, self.runner_factory = index, runner_factory
        self.candidate_pool = candidate_pool
        self.stop_index = stop_index if stop_index is not None else StopIndex({"generated_at": "unavailable", "records": []})
        self.housing = HousingModule(housing_index if housing_index is not None else HousingIndex())
        self.education_index = education_index if education_index is not None else EducationIndex()
        self.safety_index = safety_index if safety_index is not None else CctvIndex()
        self.safety = SafetyModule(self.safety_index)
        self.leisure_index = leisure_index if leisure_index is not None else LeisureIndex()
        self.orchestrator = Orchestrator({"living": LivingModule(index), "transport": TransportModule(self.stop_index),
                                        "housing": self.housing, 'education': EducationModule(self.education_index),
                                        'safety':self.safety,'leisure':LeisureModule(self.leisure_index)}, reference_modules={"housing": self.housing, 'safety':self.safety})
        self.lock, self.sessions = Lock(), {}
        self.active_job = None

    def session(self, token=None):
        with self.lock:
            now = time.monotonic()
            for key, value in list(self.sessions.items()):
                if now - value["touched"] > 3600 and not any(j["status"] == "running" for j in value["jobs"].values()):
                    del self.sessions[key]
            if token is None:
                if len(self.sessions) >= 64:
                    raise RuntimeError("busy")
                token = secrets.token_urlsafe(32)
                self.sessions[token] = {"touched": now, "jobs": {}, "comparison": None,
                                        "review_job": None, "review_key": None, "lock": Lock()}
            if token not in self.sessions:
                raise PermissionError("session_expired")
            result = self.sessions[token]
            result["touched"] = now
            return token, result

    def intake(self, session, data):
        return self.start_job(session, data, "intake",
            lambda runner, cancel: prepare_profile(runner, data.request, data.answers, data.previous,
                                                    cancel=cancel).model_dump())

    def reviews(self, session, data):
        with session["lock"]:
            current = session["comparison"]
            if current is None or current[2]["run_id"] != data.run_id:
                raise ValueError("stale_comparison")
            available = {id: f for id, f in self.enrich(current[2], current[0], current[1])["facilities"].items() if f["kind"] in ('shops', 'academy')}
            if any(id not in available for id in data.facility_ids):
                raise ValueError("unknown_facility")
            previous = session["review_job"]
            if previous:
                if previous["fingerprint"] != digest({"kind": "reviews", **data.model_dump()}):
                    raise ValueError("research_already_requested")
                return self.public_job(previous)
            shops = [available[id] for id in data.facility_ids]
            return self.start_job(session, data, "reviews",
                lambda runner, cancel: research_reviews(runner, shops, cancel=cancel),
                review_key=session["review_key"])

    def start_job(self, session, data, kind, execute, review_key=None):
        fingerprint = digest({"kind": kind, **data.model_dump()})
        with self.lock:
            old = session["jobs"].get(data.request_id)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("request_id_conflict")
                return self.public_job(old)
            if self.active_job:
                raise RuntimeError("busy")
            if len(session["jobs"]) >= 20:
                del session["jobs"][next(iter(session["jobs"]))]
            job = {"id": data.request_id, "kind": kind, "status": "running", "profile": None,
                   "result": None, "error": None, "cancel": Event(),
                   "fingerprint": fingerprint, "metadata": None}
            session["jobs"][data.request_id] = job
            if kind in ('reviews', 'supplement'):
                session["review_job"] = job
            self.active_job = job
        def work():
            runner = None
            try:
                runner = self.runner_factory()
                result = execute(runner, job["cancel"])
                with session["lock"], self.lock:
                    job["metadata"] = runner.last_metadata
                    if job["cancel"].is_set():
                        job["status"] = "cancelled"
                    elif kind in ('reviews', 'supplement') and session["review_key"] != review_key:
                        job.update(status="stale", error="stale_comparison")
                    else:
                        job.update({"profile" if kind == "intake" else "result": result,
                                    "status": "completed"})
            except Exception as error:
                with self.lock:
                    code = error.code if isinstance(error, RunnerError) else kind + "_failed"
                    job.update(status="cancelled" if job["cancel"].is_set() else "failed", error=code)
            finally:
                with self.lock:
                    job["metadata"] = runner.last_metadata if runner else None
                    self.active_job = None
        Thread(target=work, daemon=True).start()
        return self.public_job(job)

    @staticmethod
    def public_job(job):
        return {k: job[k] for k in ("id", "kind", "status", "profile", "result", "error", "metadata")}

    def enrich(self, run, profile=None, candidates=None):
        ids = {e["source_record"] for m in run["modules"] for e in m["evidence"] if e["source_record"]}
        facilities = {id: {**self.index.records[id], "review_links": map_links(self.index.records[id])}
                      for id in ids if id in self.index.records}
        facilities.update({id: self.stop_index.records[id] for id in ids if id in self.stop_index.records})
        facilities.update({id: self.education_index.records[id] for id in ids if id in self.education_index.records})
        details = []
        if profile and candidates:
            for criterion in profile.criteria:
                if criterion.module_id != 'education' or not (criterion.importance > 0 or criterion.hard): continue
                for candidate in candidates:
                    try: observation = self.education_index.observe(criterion, candidate)
                    except (ValueError, TypeError): continue
                    details.append({'candidate_id': candidate.id, 'criterion_id': criterion.id, **observation})
                    for row in observation['selected']:
                        facilities[row['id']] = {**row, 'review_links': map_links(row)}
        for id, row in list(facilities.items()):
            if row['kind'] == 'academy' and 'review_links' not in row:
                facilities[id] = {**row, 'review_links': map_links(row)}
        leisure_details=[]
        if profile and candidates:
            for criterion in profile.criteria:
                if criterion.module_id!='leisure' or not (criterion.importance>0 or criterion.hard): continue
                if criterion.metric in (PARK_METRIC,LIBRARY_METRIC):
                    for candidate in candidates:
                        try: observation=self.leisure_index.observe(criterion,candidate)
                        except (ValueError,TypeError): continue
                        leisure_details.append({'candidate_id':candidate.id,'criterion_id':criterion.id,**observation})
                        facilities.update({r['id']:r for r in observation['selected']})
                elif criterion.metric==HOBBY_METRIC:
                    activity=criterion.parameters.get('activity')
                    for candidate in candidates:
                        rows=self.leisure_index.hobby_rows(activity,criterion.parameters.get('activity_name',''))
                        ranked=sorted(((distance_m(candidate.latitude,candidate.longitude,r['lat'],r['lon']),r) for r in rows),key=lambda pair:(pair[0],pair[1]['id']))[:3]
                        leisure_details.append({'candidate_id':candidate.id,'criterion_id':criterion.id,'activity':activity,
                            'activity_form':criterion.parameters.get('activity_form',''),'activity_name':criterion.parameters.get('activity_name',''), 'score_eligible':False,
                            'registered_leads':[{'id':r['id'],'name':r['name'],'address':r['address'],'detail':r['detail'],
                                'date':r['date'],'source_url':r['source_url'],'distance_m':round(d,3)} for d,r in ranked]})
        return {**run, "facilities": facilities, 'education_details': details,'leisure_details':leisure_details}

    def supplement(self, session, run_id, facilities, targets, leisure_scope=None):
        """One cancellable, comparison-bound task; category research executes sequentially."""
        with session['lock']:
            if not session['comparison'] or session['comparison'][2]['run_id'] != run_id:
                raise ValueError('stale_comparison')
            def execute(runner, cancel):
                result = {'items':[], 'score_eligible':False, 'safety':None,'leisure':None, 'steps':[], 'errors':[]}
                for module, enabled, query in [
                    ('facility_reviews', facilities, lambda:research_reviews(runner,facilities,cancel=cancel)),
                    ('safety', targets, lambda:research_safety(runner,targets,cancel=cancel)),
                    ('leisure',leisure_scope,lambda:research_leisure(runner,leisure_scope,cancel=cancel,index=self.leisure_index))]:
                    if not enabled: continue
                    try:
                        value = query()
                        if module == 'safety': result['safety'] = value
                        elif module == 'leisure': result['leisure'] = value
                        else: result.update(value)
                    except Exception as error:
                        if cancel.is_set(): raise RunnerError('cancelled')
                        result['errors'].append({'module':module,
                            'code':error.code if isinstance(error,RunnerError) else 'research_failed'})
                    result['steps'].append({'module':module, **runner.last_metadata})
                return result
            return self.start_job(session, SupplementInput(request_id='auto_'+secrets.token_hex(12),run_id=run_id),
                'supplement', execute, review_key=session['review_key'])

    def compare(self, session, data):
        with session["lock"]:
            run = self.orchestrator.run(data.profile, data.candidates)
            previous_job = session["review_job"]
            if previous_job and previous_job["status"] == "running":
                previous_job["cancel"].set()
            session["review_job"] = None
            session["review_key"] = run["run_id"]
            run["review_key"] = run["run_id"]
            session["comparison"] = (data.profile, data.candidates, run)
            enriched = self.enrich(run, data.profile, data.candidates)
        # Conditional public-only research follows numerical modules; no search when unnecessary.
        requested = any(c.key in ('education_research', 'qualitative_research_requested') and c.value == 'requested'
                        for c in data.profile.context)
        facilities = []
        if requested:
            kind = 'academy' if any(c.key == 'education_research' and c.value == 'requested' for c in data.profile.context) else 'shops'
            facilities = sorted((f for f in enriched['facilities'].values() if f['kind'] == kind),
                key=lambda f:(min(distance_m(c.latitude,c.longitude,f['lat'],f['lon']) for c in data.candidates),f['id']))[:3]
            if not facilities:
                enriched['research_status'] = 'no_verified_facility'
        targets = self.safety_index.research_targets(data.profile, data.candidates)
        run['safety_research_scope'] = targets
        enriched['safety_research_scope'] = targets
        if context_value(data.profile, 'safety_research') == 'requested' and not targets:
            enriched['safety_research_status'] = 'no_verified_area_or_topic'
        leisure_scope=self.leisure_index.hobby_scope(data.profile,data.candidates) if context_value(data.profile,'leisure_research')=='requested' else None
        run['leisure_research_scope']=leisure_scope
        enriched['leisure_research_scope']=leisure_scope
        if context_value(data.profile,'leisure_research')=='requested' and not leisure_scope:
            enriched['leisure_research_status']='no_supported_activity'
        if facilities or targets or leisure_scope:
            enriched['research_facility_ids'] = [f['id'] for f in facilities]
            try:
                enriched['research_job'] = self.supplement(session,run['run_id'], facilities, targets,leisure_scope)
            except RuntimeError:
                enriched['research_status'] = 'busy'
        return enriched

    def preferences(self, session, data):
        with session["lock"]:
            previous = session["comparison"]
            if previous is None or previous[2]["run_id"] != data.run_id:
                raise ValueError("stale_comparison")
            profile, candidates, run = previous
            revised = update_preferences(profile, data.group_weights, data.criterion_importance, data.confirm_weights)
            report = reevaluate_preferences(profile, revised, candidates, run)
            # New identity prevents two simultaneous edits from reusing the same revision.
            result = {**run, "run_id": secrets.token_hex(16), "profile_fingerprint": revised.fingerprint(),
                      "report": report, "events": [*run["events"], {"stage": "reweighted_without_query"}]}
            result["references"] = [{**r, "profile_fingerprint": revised.fingerprint()} for r in run.get("references", [])]
            result["status"] = "partial" if any(d["status"] == "unknown" for a in report["assessments"] for d in a["details"]) else "completed"
            session["comparison"] = (revised, candidates, result)
            return {"profile": revised.model_dump(), "run": self.enrich(result, revised, candidates)}


def make_handler(state, env_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, mime="application/json; charset=utf-8"):
            payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            for name, value in {"Content-Type": mime, "Content-Length": str(len(payload)),
                                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                "Referrer-Policy": "strict-origin-when-cross-origin"}.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def guard(self, post=False):
            host = self.headers.get("Host", "")
            parsed = urlsplit("http://" + host)
            if parsed.username or parsed.password or not parsed.hostname:
                raise PermissionError("invalid_host")
            if parsed.hostname != "localhost":
                try:
                    ipaddress.ip_address(parsed.hostname)
                except ValueError:
                    raise PermissionError("use_localhost_or_ip")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                raise PermissionError("cross_origin")
            if post and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("json_required")

        def do_GET(self):
            try:
                self.guard()
                path = urlsplit(self.path).path
                files = {"/": (STATIC / "index.html", "text/html; charset=utf-8"),
                         "/workspace": (STATIC / "workspace.html", "text/html; charset=utf-8"),
                         "/village.css": (STATIC / "village.css", "text/css; charset=utf-8"),
                         "/village.mjs": (STATIC / "village.mjs", "text/javascript; charset=utf-8"),
                         "/village-model.mjs": (STATIC / "village-model.mjs", "text/javascript; charset=utf-8"),
                         "/vendor/three/three.module.min.js": (STATIC / "vendor/three/three.module.min.js", "text/javascript; charset=utf-8"),
                         "/vendor/three/three.core.min.js": (STATIC / "vendor/three/three.core.min.js", "text/javascript; charset=utf-8"),
                         "/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
                         "/candidates.js": (STATIC / "candidates.js", "text/javascript; charset=utf-8"),
                         "/reviews.js": (STATIC / "reviews.js", "text/javascript; charset=utf-8"),
                         "/transport.js": (STATIC / "transport.js", "text/javascript; charset=utf-8"),
                         "/housing.js": (STATIC / "housing.js", "text/javascript; charset=utf-8"),
                         '/education.js': (STATIC / 'education.js', 'text/javascript; charset=utf-8'),
                         '/safety.js': (STATIC / 'safety.js', 'text/javascript; charset=utf-8'),
                         '/leisure.js': (STATIC / 'leisure.js', 'text/javascript; charset=utf-8'),
                         "/style.css": (STATIC / "style.css", "text/css; charset=utf-8"),
                         "/preview/app.js": (ROOT / "tools/preview/app.js", "text/javascript; charset=utf-8"),
                         "/preview/style.css": (ROOT / "tools/preview/style.css", "text/css; charset=utf-8")}
                if path in files:
                    file, mime = files[path]
                    return self.send(200, file.read_bytes(), mime)
                if path == "/samples":
                    html = (ROOT / "tools/preview/index.html").read_text(encoding="utf-8")
                    html = html.replace('"/app.js"', '"/preview/app.js"').replace('"/style.css"', '"/preview/style.css"')
                    return self.send(200, html.encode(), "text/html; charset=utf-8")
                if path == "/api/samples":
                    return self.send(200, (ROOT / "data/processed/preview.json").read_bytes())
                if path == "/api/config":
                    return self.send(200, {"javascriptKey": sdk_key(env_path)})
                if path == "/api/bootstrap":
                    token, _ = state.session()
                    return self.send(200, {"token": token, "data": {**state.index.metadata(),
                        "transport": state.stop_index.metadata(), "housing": state.housing.index.metadata(),
                        'education': state.education_index.metadata(),
                        'safety':state.safety_index.metadata(),
                        'leisure':state.leisure_index.metadata(),
                        "candidate_generation": state.candidate_pool.metadata()
                        if state.candidate_pool else {"available": False}}})
                if path.startswith("/api/jobs/"):
                    _, session = state.session(self.headers.get("X-Session", ""))
                    with state.lock:
                        job = session["jobs"].get(path.removeprefix("/api/jobs/"))
                        result = state.public_job(job) if job else None
                    return self.send(200 if result else 404, result or {"error": "job_not_found"})
                if path == "/favicon.ico":
                    return self.send(204, b"", "image/x-icon")
                return self.send(404, {"error": "not_found"})
            except PermissionError:
                self.send(403, {"error": "session_or_origin"})
            except Exception:
                self.send(503, {"error": "unavailable"})

        def do_POST(self):
            try:
                self.guard(post=True)
                _, session = state.session(self.headers.get("X-Session", ""))
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 131072 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("invalid_body_size")
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == "/api/quick":
                    return self.send(200, {"profile": quick_profile(QuickInput.model_validate(data)).model_dump()})
                if path == "/api/transport-profile":
                    return self.send(200, {"profile": transport_profile(TransportInput.model_validate(data)).model_dump()})
                if path == '/api/education-profile':
                    return self.send(200, {'profile': education_profile(EducationInput.model_validate(data)).model_dump()})
                if path == '/api/safety-profile':
                    return self.send(200, {'profile': safety_profile(SafetyInput.model_validate(data)).model_dump()})
                if path == '/api/leisure-profile':
                    return self.send(200, {'profile': leisure_profile(LeisureInput.model_validate(data)).model_dump()})
                if path == "/api/housing-reference":
                    return self.send(200, state.housing.reference(HousingQuery.model_validate(data)).model_dump())
                if path == "/api/candidates":
                    request = GenerationInput.model_validate(data)
                    if not state.candidate_pool:
                        return self.send(200, {"status": "unavailable", "candidates": [],
                            "reason": "경계와 분석 지점 자료를 준비해야 자동으로 찾을 수 있어. 지도에서 직접 후보를 골라 줘."})
                    return self.send(200, state.candidate_pool.generate(request, state.orchestrator))
                if path == "/api/intake":
                    return self.send(202, state.intake(session, IntakeInput.model_validate(data)))
                if path == "/api/reviews":
                    return self.send(202, state.reviews(session, ReviewInput.model_validate(data)))
                if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                    id = path[len("/api/jobs/"):-len("/cancel")]
                    with state.lock:
                        job = session["jobs"].get(id)
                        if not job:
                            return self.send(404, {"error": "job_not_found"})
                        if job["status"] == "running":
                            job["cancel"].set()
                        return self.send(200, state.public_job(job))
                if path == "/api/compare":
                    return self.send(200, state.compare(session, CompareInput.model_validate(data)))
                if path == "/api/preferences":
                    return self.send(200, state.preferences(session, PreferenceInput.model_validate(data)))
                return self.send(404, {"error": "not_found"})
            except PermissionError:
                self.send(403, {"error": "session_or_origin"})
            except (ValueError, TypeError):
                self.send(400, {"error": "invalid_or_stale_input"})
            except RuntimeError:
                self.send(409, {"error": "busy"})
            except Exception:
                self.send(500, {"error": "request_failed"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/processed/inventory.json")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--candidate-pool", type=Path, default=ROOT / "data/processed/candidate-pool.json")
    parser.add_argument("--boundary", type=Path, default=ROOT / "data/reference/jinju-boundary-2025.geojson")
    parser.add_argument("--housing", type=Path, default=ROOT / "data/processed/housing.json")
    parser.add_argument('--education', type=Path, default=ROOT / 'data/processed/education.json')
    parser.add_argument('--leisure', type=Path, default=ROOT / 'data/processed/leisure.json')
    parser.add_argument('--quarantine', type=Path, default=ROOT / 'data/processed/quarantine.json')
    args = parser.parse_args()
    sdk_key(args.env_file)
    document = json.loads(args.inventory.read_text(encoding="utf-8"))
    pool = None
    try:
        pool = CandidatePool.load(args.candidate_pool, args.boundary, args.inventory)
    except (OSError, ValueError, KeyError, TypeError):
        print("Candidate generation unavailable: prepare matching boundary/inventory/pool files.", flush=True)
    housing = HousingIndex()
    try:
        housing = HousingIndex.load(args.housing)
    except (OSError, ValueError, KeyError, TypeError):
        print("Housing reference unavailable: prepare validated apartment CSV snapshots.", flush=True)
    education = EducationIndex()
    try:
        education = EducationIndex.load(args.education, document)
    except (OSError, ValueError, KeyError, TypeError):
        print('Education unavailable: prepare verified school/academy snapshots.', flush=True)
    excluded = None
    try:
        quarantined = json.loads(args.quarantine.read_text(encoding='utf-8'))
        if quarantined['generated_at'] == document['generated_at']:
            excluded = sum(r['source'] == 'cctv' and r['reason'] in ('outside_broad_jinju_screen','invalid_coordinate')
                           for r in quarantined['records'])
    except (OSError, ValueError, KeyError, TypeError): pass
    safety = CctvIndex(document, pool.boundary if pool else None, excluded)
    leisure=LeisureIndex(inventory=document,boundary=pool.boundary if pool else None)
    try:
        leisure=LeisureIndex.load(args.leisure,document,pool.boundary if pool else None)
    except (OSError,ValueError,KeyError,TypeError):
        print('Leisure public data unavailable: prepare verified park/library snapshots.',flush=True)
    state = AppState(ShopIndex(document), stop_index=StopIndex(document), candidate_pool=pool,
                     housing_index=housing, education_index=education, safety_index=safety,leisure_index=leisure)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, args.env_file))
    server.daemon_threads = True
    print(f"Saljari M1/M2/M3/M4/M5/M6: http://localhost:{args.port} (bind {args.host})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
