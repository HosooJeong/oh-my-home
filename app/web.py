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
from .intake import prepare_profile
from .reviews import ReviewInput, map_links, research_reviews
from .modules.living import LivingModule, ShopIndex
from .modules.transport import StopIndex, TransportModule
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
    def __init__(self, index, runner_factory=CodexRunner, stop_index=None):
        self.index, self.runner_factory = index, runner_factory
        self.stop_index = stop_index if stop_index is not None else StopIndex({"generated_at": "unavailable", "records": []})
        self.orchestrator = Orchestrator({"living": LivingModule(index), "transport": TransportModule(self.stop_index)})
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
            available = {id: f for id, f in self.enrich(current[2])["facilities"].items() if f["kind"] == "shops"}
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
            if kind == "reviews":
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
                    elif kind == "reviews" and session["review_key"] != review_key:
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

    def enrich(self, run):
        ids = {e["source_record"] for m in run["modules"] for e in m["evidence"] if e["source_record"]}
        facilities = {id: {**self.index.records[id], "review_links": map_links(self.index.records[id])}
                      for id in ids if id in self.index.records}
        facilities.update({id: self.stop_index.records[id] for id in ids if id in self.stop_index.records})
        return {**run, "facilities": facilities}

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
            return self.enrich(run)

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
            result["status"] = "partial" if any(d["status"] == "unknown" for a in report["assessments"] for d in a["details"]) else "completed"
            session["comparison"] = (revised, candidates, result)
            return {"profile": revised.model_dump(), "run": self.enrich(result)}


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
                         "/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
                         "/reviews.js": (STATIC / "reviews.js", "text/javascript; charset=utf-8"),
                         "/transport.js": (STATIC / "transport.js", "text/javascript; charset=utf-8"),
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
                    return self.send(200, {"token": token, "data": {**state.index.metadata(), "transport": state.stop_index.metadata()}})
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
    args = parser.parse_args()
    sdk_key(args.env_file)
    document = json.loads(args.inventory.read_text(encoding="utf-8"))
    state = AppState(ShopIndex(document), stop_index=StopIndex(document))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, args.env_file))
    server.daemon_threads = True
    print(f"Saljari M1/M2: http://localhost:{args.port} (bind {args.host})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
