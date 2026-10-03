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
from .llm_settings import ModelSettings, server_settings
from .contracts import Candidate, Contract, InterviewTurn, NeedProfile, Weight, digest
from .candidates import CandidatePool, GenerationInput
from .intake import prepare_profile
from .debug_transcript import DebugTranscripts
from .reviews import ReviewInput, map_links, research_reviews
from .facility_facts import research_facility_facts, discover_facility_facts
from .research_plan import build_research_plan, evidence_status
from .preference_edits import PreservationError, edited, edit_quote, preserve_need
from .modules.living import LivingModule, ShopIndex
from .modules.transport import StopIndex, TransportModule
from .modules.housing import HousingIndex, HousingModule, HousingQuery
from .modules.registered_access import RegisteredAccessModule
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
from .routes import KakaoRoutes, RouteInput, RouteError
from .orchestrator import Orchestrator
from .preferences import reevaluate_preferences, update_preferences
from tools.preview.server import sdk_key

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"


class CompareInput(Contract):
    profile: NeedProfile
    candidates: Annotated[list[Candidate], Field(min_length=1, max_length=6)]
    progress_id: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')] | None = None


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
    profile: NeedProfile | None = None
    edited_fields: Annotated[list[str], Field(max_length=10)] | None = None
    ideal: Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]
    limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)]
    supermarket_weight: Weight
    convenience_weight: Weight
    mandatory_limit: bool


def quick_profile(data: QuickInput):
    if data.profile and data.edited_fields == []: return data.profile.model_copy(deep=True)
    if data.ideal >= data.limit or data.supermarket_weight + data.convenience_weight == 0:
        raise ValueError("invalid quick preferences")
    request = (f"마트와 편의점의 직선거리를 비교해 줘. {data.ideal:g}m 이내가 이상적이고 "
               f"{data.limit:g}m 이상은 만족도가 0이야. 마트 중요도 {data.supermarket_weight:g}, "
               f"편의점 중요도 {data.convenience_weight:g}. "
               + (f"두 시설 모두 반드시 {data.limit:g}m 이내여야 해." if data.mandatory_limit else "필수 제한은 없어."))
    fresh = {"schema_version": "1", "revision": 1, "request": request,
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
        "questions": []}
    if data.profile is None: return NeedProfile.model_validate(fresh)
    doc=data.profile.model_dump();doc['revision']+=1
    quote=edit_quote(data,request);doc['request']+='\n'+quote
    for template, field in zip(fresh['criteria'],('supermarket_weight','convenience_weight')):
        metrics={template['metric']}
        if field=='supermarket_weight': metrics.add('house_to_grocery_straight_line_distance_m')
        old=[c for c in doc['criteria'] if c['module_id']=='living' and c['metric'] in metrics]
        if len(old)>1 or old and old[0]['group_id']!='living':
            raise PreservationError('여러 장보기 조건이 있어요. 이 입력란으로 합치지 않고 원래 조건을 유지했어요.')
        if not old:
            while any(c['id']==template['id'] for c in doc['criteria']): template['id']+='_x'
            template['source_quote']=quote;doc['criteria'].append(template);continue
        c=old[0];values={}
        if edited(data,'ideal','limit'):
            if c['utility'] and (c['utility']['unit']!='m' or c['utility']['direction']!='lower'):
                raise PreservationError('기존 장보기 기준은 직선거리와 달라요. 원래 조건을 유지했어요.')
            values['utility']=template['utility']
        if edited(data,field): values.update(importance=template['importance'],importance_source='user')
        if edited(data,'mandatory_limit'):
            if c['hard'] and c['hard']['operator']!='lte' and data.mandatory_limit:
                raise PreservationError('기존 장보기 필수조건은 이 입력란으로 표현할 수 없어요. 원래 조건을 유지했어요.')
            values['hard']=(c['hard'] or template['hard']) if data.mandatory_limit else None
        preserve_need(c,values,quote)
    if not any(g['id']=='living' for g in doc['groups']):doc['groups'].append(fresh['groups'][0])
    return NeedProfile.model_validate(doc)


class HousingProfileInput(Contract):
    profile: NeedProfile


class AppState:
    def __init__(self, index, runner_factory=CodexRunner, stop_index=None, candidate_pool=None, housing_index=None, education_index=None, safety_index=None, leisure_index=None, debug_transcripts=None, route_client=None, llm_settings=None):
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
                                        'safety':self.safety,'leisure':LeisureModule(self.leisure_index),
                                        'health':RegisteredAccessModule('health',index),
                                        'dining':RegisteredAccessModule('dining',index)}, reference_modules={"housing": self.housing, 'safety':self.safety})
        self.lock, self.sessions = Lock(), {}
        self.active_job = None
        self.debug_transcripts = debug_transcripts
        self.route_client = route_client
        self.llm_settings = llm_settings or ModelSettings()

    def record(self, session, role, content, **details):
        if self.debug_transcripts and session.get('debug_path'):
            try:
                self.debug_transcripts.append(session['debug_path'], role, content, **details)
            except OSError:
                # A diagnostic write must not turn a successful analysis into a failure.
                print('Debug transcript write failed.', flush=True)

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
                                        "review_job": None, "review_key": None, "lock": Lock(),
                                        'llm_settings': self.llm_settings,
                                        'debug_path': self.debug_transcripts.start() if self.debug_transcripts else None}
            if token not in self.sessions:
                raise PermissionError("session_expired")
            result = self.sessions[token]
            result["touched"] = now
            return token, result

    def model_settings(self, session, data=None):
        with self.lock:
            if data is not None:
                if any(j['status'] == 'running' for j in session['jobs'].values()):
                    raise RunnerError('busy')
                session['llm_settings'] = session['llm_settings'].updated(data)
            return session['llm_settings'].public()

    def intake(self, session, data):
        return self.start_job(session, data, "intake",
            lambda runner, cancel: prepare_profile(runner, data.request, data.answers, data.previous,
                                                    cancel=cancel).model_dump())

    def reviews(self, session, data):
        with session["lock"]:
            current = session["comparison"]
            if current is None or current[2]["run_id"] != data.run_id:
                raise ValueError("stale_comparison")
            enriched = self.enrich(current[2], current[0], current[1])
            available = {id: f for id, f in enriched["facilities"].items() if f["kind"] in ('shops', 'academy')}
            if any(id not in available for id in data.facility_ids):
                raise ValueError("unknown_facility")
            previous = session["review_job"]
            if previous:
                if previous["fingerprint"] != digest({"kind": "reviews", **data.model_dump()}):
                    raise ValueError("research_already_requested")
                return self.public_job(previous)
            shops = [available[id] for id in data.facility_ids]
            plan = build_research_plan(current[0], current[1], enriched, [], None, self.education_index)
            requested = [r for r in plan['requests'] if r['module'] in ('living', 'education')]
            questions = [q for t in plan['tasks'] for q in t.get('questions', [])
                         if set(q['facility_ids']).intersection(data.facility_ids)] if requested else None
            if requested and not set(data.facility_ids).issubset({id for q in questions for id in q['facility_ids']}):
                raise ValueError('research_scope_unconfirmed')
            return self.start_job(session, data, "reviews",
                lambda runner, cancel: research_reviews(runner, shops, cancel=cancel, questions=questions),
                review_key=session["review_key"])

    def start_job(self, session, data, kind, execute, review_key=None, request_statuses=()):
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
                   "fingerprint": fingerprint, "metadata": None, "request_statuses":[dict(r) for r in request_statuses]}
            session["jobs"][data.request_id] = job
            if kind in ('reviews', 'supplement'):
                session["review_job"] = job
            self.active_job = job
            settings = session['llm_settings']
        def work():
            runner = None
            try:
                self.record(session, '사용자 요청', data.model_dump(), job=job['id'], kind=kind)
                runner = settings.runner(self.runner_factory)
                runner.on_debug_event = lambda role, content, **details: self.record(session, role, content, job=job['id'], **details)
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
                    job['request_statuses']=[dict(r,status=job['status'],reason=code) if r['status'] in ('queued','running') else r for r in job['request_statuses']]
                    if kind=='supplement' and session['review_key']==review_key and session['comparison']:
                        plan=session['comparison'][2].get('research_plan')
                        if plan is not None:plan['requests']=[dict(r) for r in job['request_statuses']]
            finally:
                with self.lock:
                    job["metadata"] = runner.last_metadata if runner else None
                    self.active_job = None
                self.record(session, '작업 종료', {'status':job['status'], 'error':job['error'], 'metadata':job['metadata'],
                            'profile':job['profile'], 'result':job['result']}, job=job['id'], kind=kind)
        Thread(target=work, daemon=True).start()
        return self.public_job(job)

    @staticmethod
    def public_job(job):
        return {**{k: job[k] for k in ("id", "kind", "status", "profile", "result", "error", "metadata")},
                "request_statuses":[dict(r) for r in job.get("request_statuses",[])]}

    def enrich(self, run, profile=None, candidates=None):
        ids = {e["source_record"] for m in run["modules"] for e in m["evidence"] if e["source_record"]}
        facilities = {id: {**self.index.records[id], "review_links": map_links(self.index.records[id])}
                      for id in ids if id in self.index.records}
        facilities.update({id: self.stop_index.records[id] for id in ids if id in self.stop_index.records})
        facilities.update({id: self.education_index.records[id] for id in ids if id in self.education_index.records})
        facilities.update(run.get('research_facilities',{}))
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

    def supplement(self, session, run_id, facilities, targets, leisure_scope=None, plan=None):
        """Comparison-bound task; independent requested categories, one sequential model slot."""
        with session['lock']:
            if not session['comparison'] or session['comparison'][2]['run_id'] != run_id:
                raise ValueError('stale_comparison')
            tasks=plan['tasks'] if plan is not None else [
                {'module':'facility_reviews','facilities':facilities,'request_ids':[]},
                {'module':'safety','targets':targets,'request_ids':[]},
                {'module':'leisure','scope':leisure_scope,'request_ids':[]}]
            statuses=[dict(r) for r in plan['requests']] if plan is not None else []
            public_plan=session['comparison'][2].get('research_plan')
            request_id='auto_'+secrets.token_hex(12)
            def mark(ids,status,reason=None,evidence=None):
                nonlocal statuses
                statuses=[dict(r,status=status,reason=reason,evidence_status=evidence) if r['id'] in ids else r for r in statuses]
                with self.lock:
                    session['jobs'][request_id]['request_statuses']=[dict(r) for r in statuses]
                    if public_plan is not None:public_plan['requests']=[dict(r) for r in statuses]
            def execute(runner, cancel):
                result={'items':[], 'facilities':{}, 'score_eligible':False, 'safety':None, 'leisure':None, 'steps':[], 'errors':[]}
                for task in tasks:
                    module=task['module'];ids=task['request_ids'];stage='research'
                    if not (task.get('facilities') or task.get('targets') or task.get('scope') or
                            task.get('research_kind')=='facility_fact' and task.get('questions')):continue
                    if cancel.is_set():
                        mark([r['id'] for r in statuses if r['status'] in ('queued','running')],'cancelled','cancelled')
                        raise RunnerError('cancelled')
                    mark(ids,'running')
                    try:
                        if module in ('living','education','health','dining','facility_reviews'):
                            researcher=research_facility_facts if task.get('research_kind')=='facility_fact' else research_reviews
                            value=researcher(runner,task['facilities'],cancel=cancel,questions=task.get('questions')) if task['facilities'] else {'items':[]}
                            if task.get('research_kind')=='facility_fact' and not any(
                                    not x.get('registry_source') for i in value.get('items',[]) for x in i.get('excerpts',[])):
                                if task['facilities']:
                                    result['steps'].append({'module':module,'stage':'registered_facility_facts',**runner.last_metadata})
                                stage='facility_discovery'
                                try:
                                    discovered=discover_facility_facts(runner,module,task.get('questions',[]),cancel=cancel,areas=task.get('discovery_areas',[]))
                                    value['items'].extend(discovered.get('items',[]))
                                    result['facilities'].update(discovered.get('facilities',{}))
                                    value['response_validation']=discovered.get('response_validation',{})
                                except Exception as discovery_error:
                                    if cancel.is_set():raise RunnerError('cancelled')
                                    result['errors'].append({'module':module,'stage':'facility_discovery',
                                        'code':discovery_error.code if isinstance(discovery_error,RunnerError) else 'research_failed'})
                            result['items'].extend(value.get('items',[]))
                            if task.get('research_kind')=='facility_fact':result['facilities'].update(value.get('facilities',{}))
                        elif module=='safety':
                            value=research_safety(runner,task['targets'],cancel=cancel);result['safety']=value
                        else:
                            value=research_leisure(runner,task['scope'],cancel=cancel,index=self.leisure_index);result['leisure']=value
                        for record in [r for r in statuses if r['id'] in ids]:
                            scoped=value
                            if module in ('living','education','health','dining','facility_reviews'):
                                scoped={**value,'items':[i for i in value.get('items',[]) if i['facility_id'] in record['facility_ids'] or i.get('web_discovery')]}
                                discovered_ids=[i['facility_id'] for i in scoped['items'] if i.get('web_discovery') and i.get('excerpts')]
                                if discovered_ids:
                                    record['discovered_facility_ids']=discovered_ids
                                    record['discovery_scope']='진주시 공개 웹 · 집별 거리/생활권 적용 미확인'
                            elif module=='leisure' and record['criterion_ids']:
                                scoped={**value,'discoveries':[i for i in value.get('discoveries',[]) if i.get('criterion_id') in record['criterion_ids']]}
                            mark([record['id']],'completed',
                                 reason='response_validation_failed' if value.get('response_validation',{}).get('status')=='failed' else None,
                                 evidence=evidence_status(module,scoped,record['id']))
                    except Exception as error:
                        if cancel.is_set():
                            mark([r['id'] for r in statuses if r['status'] in ('queued','running')],'cancelled','cancelled')
                            raise RunnerError('cancelled')
                        code=error.code if isinstance(error,RunnerError) else 'research_failed'
                        result['errors'].append({'module':module,'code':code});mark(ids,'failed',code)
                    result['steps'].append({'module':module,'stage':stage,**runner.last_metadata})
                result['requests']=statuses
                return result
            return self.start_job(session,SupplementInput(request_id=request_id,run_id=run_id),
                'supplement',execute,review_key=session['review_key'],request_statuses=statuses)

    def compare(self, session, data):
        with session["lock"]:
            def progress(event):
                if data.progress_id:
                    with self.lock:
                        session['comparison_progress']['events'].append(dict(event))
            if data.progress_id:
                with self.lock:
                    session['comparison_progress']={'id':data.progress_id,'events':[]}
            run = self.orchestrator.run(data.profile, data.candidates, on_event=progress if data.progress_id else None)
            previous_job = session["review_job"]
            if previous_job and previous_job["status"] == "running":
                previous_job["cancel"].set()
            session["review_job"] = None
            session["review_key"] = run["run_id"]
            run["review_key"] = run["run_id"]
            session["comparison"] = (data.profile, data.candidates, run)
            enriched = self.enrich(run, data.profile, data.candidates)
        targets=self.safety_index.research_targets(data.profile,data.candidates)
        leisure_scope=self.leisure_index.hobby_scope(data.profile,data.candidates) if context_value(data.profile,'leisure_research')=='requested' else None
        plan=build_research_plan(data.profile,data.candidates,enriched,targets,leisure_scope,self.education_index,self.index)
        for task in plan['tasks']:
            if task.get('research_kind')=='facility_fact':
                task['discovery_areas']=sorted({area['name'] for c in data.candidates if (area:=self.safety_index.area(c))})
        if run.get('report') is None:
            for r in plan['requests']:
                if r['status']=='queued':r.update(status='not_executed',reason='needs_input')
            plan['tasks']=[]
        all_areas={a['code'] for c in data.candidates if (a:=self.safety_index.area(c))}
        searched={t['area_code'] for t in targets}
        for r in plan['requests']:
            if r['module']=='safety':r.update(area_codes=sorted(searched),unsearched_area_codes=sorted(all_areas-searched))
            if r['module']=='leisure' and leisure_scope:r['unsearched_areas']=leisure_scope.get('unsearched_areas',[])
        public_plan={k:v for k,v in plan.items() if k!='tasks'}
        run['research_facilities']={f['id']:f for task in plan['tasks'] for f in task.get('facilities',[])}
        enriched['facilities'].update(run['research_facilities'])
        run['research_plan']=public_plan;enriched['research_plan']=public_plan
        run['safety_research_scope']=targets;enriched['safety_research_scope']=targets
        run['leisure_research_scope']=leisure_scope;enriched['leisure_research_scope']=leisure_scope
        if plan['tasks']:
            enriched['research_facility_ids']=list(dict.fromkeys(f['id'] for t in plan['tasks'] for f in t.get('facilities',[])))
            try:enriched['research_job']=self.supplement(session,run['run_id'],[],targets,leisure_scope,plan)
            except RuntimeError:
                enriched['research_status']='busy'
                for r in public_plan['requests']:
                    if r['status']=='queued':r.update(status='not_executed',reason='busy')
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
                         '/routes': (STATIC / 'routes.html', 'text/html; charset=utf-8'),
                         '/routes.mjs': (STATIC / 'routes.mjs', 'text/javascript; charset=utf-8'),
                         '/routes.css': (STATIC / 'routes.css', 'text/css; charset=utf-8'),
                         "/workspace": (STATIC / "workspace.html", "text/html; charset=utf-8"),
                         '/analysis': (STATIC / 'analysis.html', 'text/html; charset=utf-8'),
                         '/analysis.mjs': (STATIC / 'analysis.mjs', 'text/javascript; charset=utf-8'),
                         '/village-world.mjs': (STATIC / 'village-world.mjs', 'text/javascript; charset=utf-8'),
                         '/village-journey.mjs': (STATIC / 'village-journey.mjs', 'text/javascript; charset=utf-8'),
                         '/analysis-view.mjs': (STATIC / 'analysis-view.mjs', 'text/javascript; charset=utf-8'),
                         '/result-report.mjs': (STATIC / 'result-report.mjs', 'text/javascript; charset=utf-8'),
                         '/result-report.css': (STATIC / 'result-report.css', 'text/css; charset=utf-8'),
                         '/entry-places.mjs': (STATIC / 'entry-places.mjs', 'text/javascript; charset=utf-8'),
                         '/debug-session.mjs': (STATIC / 'debug-session.mjs', 'text/javascript; charset=utf-8'),
                         '/settings': (STATIC / 'settings.html', 'text/html; charset=utf-8'),
                         '/settings.mjs': (STATIC / 'settings.mjs', 'text/javascript; charset=utf-8'),
                         '/settings.css': (STATIC / 'settings.css', 'text/css; charset=utf-8'),
                         '/typography.css': (STATIC / 'typography.css', 'text/css; charset=utf-8'),
                         '/interview.css': (STATIC / 'interview.css', 'text/css; charset=utf-8'),
                         '/kakao-map.mjs': (STATIC / 'kakao-map.mjs', 'text/javascript; charset=utf-8'),
                         '/vendor/fonts/SUIT-Variable.woff2': (STATIC / 'vendor/fonts/SUIT-Variable.woff2', 'font/woff2'),
                         '/vendor/fonts/SUIT-LICENSE.txt': (STATIC / 'vendor/fonts/SUIT-LICENSE.txt', 'text/plain; charset=utf-8'),
                         '/vendor/fonts/SUITE-Variable.woff2': (STATIC / 'vendor/fonts/SUITE-Variable.woff2', 'font/woff2'),
                         '/vendor/fonts/SUITE-LICENSE.txt': (STATIC / 'vendor/fonts/SUITE-LICENSE.txt', 'text/plain; charset=utf-8'),
                         '/analysis.css': (STATIC / 'analysis.css', 'text/css; charset=utf-8'),
                         "/village.css": (STATIC / "village.css", "text/css; charset=utf-8"),
                         "/village.mjs": (STATIC / "village.mjs", "text/javascript; charset=utf-8"),
                         "/village-model.mjs": (STATIC / "village-model.mjs", "text/javascript; charset=utf-8"),
                         "/village-models.mjs": (STATIC / "village-models.mjs", "text/javascript; charset=utf-8"),
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
                if path == '/api/routes/status':
                    return self.send(200, (state.route_client or KakaoRoutes(env_path)).status())
                if path == "/api/bootstrap":
                    token, session = state.session(self.headers.get('X-Session') or None)
                    return self.send(200, {"token": token, 'llm': state.model_settings(session), 'debug_enabled': bool(state.debug_transcripts),
                        'debug_session': session['debug_path'].stem if session.get('debug_path') else None, "data": {**state.index.metadata(),
                        "transport": state.stop_index.metadata(), "housing": state.housing.index.metadata(),
                        'education': state.education_index.metadata(),
                        'safety':state.safety_index.metadata(),
                        'leisure':state.leisure_index.metadata(),
                        "candidate_generation": state.candidate_pool.metadata()
                        if state.candidate_pool else {"available": False}}})
                if path == '/api/llm/settings':
                    _, session = state.session(self.headers.get('X-Session', ''))
                    return self.send(200, state.model_settings(session))
                if path.startswith("/api/jobs/"):
                    _, session = state.session(self.headers.get("X-Session", ""))
                    with state.lock:
                        job = session["jobs"].get(path.removeprefix("/api/jobs/"))
                        result = state.public_job(job) if job else None
                    return self.send(200 if result else 404, result or {"error": "job_not_found"})
                if path.startswith('/api/progress/'):
                    _, session = state.session(self.headers.get('X-Session', ''))
                    with state.lock:
                        value=session.get('comparison_progress')
                        result={'id':value['id'],'events':[dict(e) for e in value['events']]} if value and value['id']==path.removeprefix('/api/progress/') else None
                    return self.send(200 if result else 404, result or {'error':'progress_not_found'})
                if path == "/favicon.ico":
                    return self.send(204, b"", "image/x-icon")
                return self.send(404, {"error": "not_found"})
            except PermissionError:
                self.send(403, {"error": "session_or_origin"})
            except Exception:
                self.send(503, {"error": "unavailable"})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 131072 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("invalid_body_size")
                self.connection.settimeout(10)
                # Consume the bounded body before rejecting auth. Unread TCP data can reset
                # the connection on Windows and hide the intended 403 from the caller.
                raw = self.rfile.read(size)
                self.guard(post=True)
                _, session = state.session(self.headers.get("X-Session", ""))
                data = json.loads(raw)
                path = urlsplit(self.path).path
                if path == '/api/llm/settings':
                    # Credentials are intentionally excluded from transcript recording.
                    return self.send(200, state.model_settings(session, data))
                if path == '/api/llm/models':
                    if data != {}:
                        raise RunnerError('invalid_model_settings')
                    with state.lock:
                        settings = session['llm_settings']
                    if settings.provider != 'openai':
                        raise RunnerError('unsupported_configuration')
                    from .openai_runner import OpenAIRunner
                    return self.send(200, {'models': OpenAIRunner(settings.api_key, settings.model, settings.effort, timeout=15).models()})
                if path == '/api/routes':
                    # Route coordinates and provider responses must stay out of debug/model records.
                    request = RouteInput.model_validate(data)
                    with state.lock:
                        if state.route_client is None:
                            state.route_client = KakaoRoutes(env_path)
                    return self.send(200, state.route_client.query(request))
                if path == '/api/debug-event':
                    if set(data) != {'event','data'} or data['event'] not in ('entry_selected','candidates_confirmed','category_answer','village_confirmed','conditions_confirmed','analysis_error','comparison_result'):
                        raise ValueError('invalid_debug_event')
                    state.record(session, '화면 대화', data['data'], event=data['event'])
                    return self.send(200, {'enabled':bool(state.debug_transcripts)})
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
                if path == '/api/housing-profile-reference':
                    request=HousingProfileInput.model_validate(data)
                    result=state.housing.run_reference(request.profile,[],Event()).model_dump()
                    result['research_plan']={k:v for k,v in build_research_plan(request.profile,[],{'modules':[],'facilities':{}},[],None).items() if k!='tasks'}
                    return self.send(200,result)
                if path == "/api/housing-reference":
                    return self.send(200, state.housing.reference(HousingQuery.model_validate(data)).model_dump())
                if path == "/api/candidates":
                    request = GenerationInput.model_validate(data)
                    if not state.candidate_pool:
                        return self.send(200, {"status": "unavailable", "candidates": [],
                            "reason": "경계와 분석 지점 자료를 준비해야 자동으로 찾을 수 있어요. 지도에서 직접 후보를 골라 주세요."})
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
                    state.record(session, '후보 비교 요청', data)
                    result = state.compare(session, CompareInput.model_validate(data))
                    state.record(session, '후보 비교 결과', result)
                    return self.send(200, result)
                if path == "/api/preferences":
                    return self.send(200, state.preferences(session, PreferenceInput.model_validate(data)))
                return self.send(404, {"error": "not_found"})
            except PermissionError:
                self.send(403, {"error": "session_or_origin"})
            except RouteError as error:
                self.send(error.http_status, error.public())
            except RunnerError as error:
                self.send(409 if error.code == 'busy' else 400, {'error': error.code})
            except PreservationError as error:
                self.send(422, {'error': str(error)})
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
    parser.add_argument('--debug-transcripts', type=Path, nargs='?',
                        const=ROOT.parent / 'work/saljari-private/debug-sessions',
                        help='Opt-in local test conversation files, outside the code repository.')
    args = parser.parse_args()
    if args.debug_transcripts and args.debug_transcripts.resolve().is_relative_to(ROOT.resolve()):
        parser.error('--debug-transcripts must be outside the code repository')
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
                     housing_index=housing, education_index=education, safety_index=safety,leisure_index=leisure,
                     debug_transcripts=DebugTranscripts(args.debug_transcripts) if args.debug_transcripts else None,
                     llm_settings=server_settings(args.env_file))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, args.env_file))
    server.daemon_threads = True
    print(f"Saljari M1/M2/M3/M4/M5/M6: http://localhost:{args.port} (bind {args.host})", flush=True)
    if args.debug_transcripts:
        print(f'Test transcripts enabled: {args.debug_transcripts.resolve()}', flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
