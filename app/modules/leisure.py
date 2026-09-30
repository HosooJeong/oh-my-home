"""M6 purpose-matched public access, explicit meeting points, and unscored hobby leads."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from ..contracts import CategoryResult, Evidence, digest
from ..geo import distance_m, in_supported_window
from ..research_policy import today

PARK_SOURCE = 'https://www.data.go.kr/data/15012890/standard.do'
LIBRARY_SOURCE = 'https://www.data.go.kr/data/15013109/standard.do'
SHOP_SOURCE = 'https://www.data.go.kr/data/15083033/fileData.do'
PARK_METRIC = 'park_straight_line_distance_m'
LIBRARY_METRIC = 'library_straight_line_distance_m'
MEETING_METRIC = 'meeting_straight_line_distance_m'
HOBBY_METRIC = 'hobby_suitability'
ACTIVITIES = {'gym':'헬스', 'pilates':'필라테스', 'table_tennis':'탁구', 'swimming':'수영', 'tennis':'테니스', 'yoga':'요가','other':'직접 입력한 취미'}
HOBBY_DETAILS = {'gym':{'헬스장'}, 'pilates':{'요가/필라테스 학원'}, 'yoga':{'요가/필라테스 학원'},
                 'table_tennis':{'탁구장'}, 'swimming':{'수영장'}, 'tennis':{'테니스장'}}
PARK_TYPES = {'any': None, 'children': '어린이공원', 'neighborhood': '근린공원'}
LIBRARY_TYPES = {'any': None, 'public': '공공도서관', 'small': '작은도서관'}
MAX_DATA_AGE = 365


def fresh(row):
    return 0 <= (today() - date.fromisoformat(row['date'])).days <= MAX_DATA_AGE


class LeisureIndex:
    def __init__(self, document=None, inventory=None, boundary=None):
        self.document = document or {'retrieved_at':None, 'records':[], 'excluded':{}}
        self.records, self.boundary = {}, boundary
        for row in self.document['records']:
            source = {'park':PARK_SOURCE, 'library':LIBRARY_SOURCE}.get(row['kind'])
            if not source or row['source_url'] != source or row['source_row'] < 1 or not row['name'] or row['id'] in self.records:
                raise ValueError('invalid leisure provenance')
            date.fromisoformat(row['date'])
            if (row['lat'] is None) != (row['lon'] is None): raise ValueError('incomplete leisure coordinates')
            if row['lat'] is not None and (not math.isfinite(row['lat']) or not math.isfinite(row['lon'])
                    or not in_supported_window(row['lat'], row['lon'])): raise ValueError('invalid leisure coordinates')
            self.records[row['id']] = row
        self.shops = {}
        for row in (inventory or {}).get('records', []):
            if row['kind'] != 'shops': continue
            if row['source_url'] != SHOP_SOURCE or row['id'] in self.shops: raise ValueError('invalid shop provenance')
            date.fromisoformat(row['date'])
            if not in_supported_window(row['lat'], row['lon']): raise ValueError('invalid hobby coordinates')
            self.shops[row['id']] = row

    @classmethod
    def load(cls, path, inventory=None, boundary=None):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')), inventory, boundary)

    def metadata(self):
        return {'available':bool(self.records), 'counts':{k:sum(r['kind']==k for r in self.records.values()) for k in ('park','library')},
                'stale_or_future':{k:sum(r['kind']==k and not fresh(r) for r in self.records.values()) for k in ('park','library')},
                'unlocated':sum(r['lat'] is None for r in self.records.values()),
                'dates':{k:sorted({r['date'] for r in self.records.values() if r['kind']==k}) for k in ('park','library')},
                'hobby_registered_counts':{k:len(self.hobby_rows(k)) for k in HOBBY_DETAILS},
                'activities':ACTIVITIES, 'max_data_age_days':MAX_DATA_AGE,
                'limitations':'공식 등록 위치의 직선거리야. 실제 경로·출입구·동반 규칙은 미확인이며 사설 후보/후기는 점수와 분리해.'}

    def select(self, criterion):
        p = criterion.parameters
        if criterion.metric == PARK_METRIC and set(p) <= {'park_type'} and p.get('park_type','any') in PARK_TYPES:
            kind, selected = 'park', PARK_TYPES[p.get('park_type','any')]
        elif criterion.metric == LIBRARY_METRIC and set(p) <= {'library_type'} and p.get('library_type','any') in LIBRARY_TYPES:
            kind, selected = 'library', LIBRARY_TYPES[p.get('library_type','any')]
        else: raise ValueError('unsupported leisure scope')
        # School/university libraries do not imply public access.
        return [r for r in self.records.values() if r['kind']==kind and (kind != 'library' or r['type'] in LIBRARY_TYPES.values())
                and (selected is None or r['type']==selected)]

    def observe(self, criterion, candidate):
        rows = self.select(criterion)
        uncertain = [r for r in rows if r['lat'] is None or not fresh(r)]
        located = [r for r in rows if r['lat'] is not None]
        ranked = sorted(((distance_m(candidate.latitude,candidate.longitude,r['lat'],r['lon']),r) for r in located),
                        key=lambda pair:(pair[0],pair[1]['id']))
        selected = ranked[:1] if in_supported_window(candidate.latitude,candidate.longitude) else []
        row = selected[0][1] if selected else None
        status = 'verified' if row and not uncertain else 'missing'
        note = f'지정 유형의 등록 장소까지 직선거리. 위치/자료 시점 미확인 {len(uncertain)}곳. '
        if uncertain: note += '전체 최단거리와 점수는 확정하지 않았어. '
        note += '실제 도보 경로·현재 이용 가능성·동반 규칙은 미확인이야.'
        return {'value':round(selected[0][0],3) if row else None, 'status':status, 'note':note,
                'selected':[row] if row else [], 'uncertain_count':len(uncertain), 'matched_registered_count':len(rows)}

    def hobby_rows(self, activity, activity_name=''):
        if activity not in ACTIVITIES: return []
        if activity=='other':
            return [r for r in self.shops.values() if activity_name and activity_name in r['name']]
        # Joint yoga/pilates classification remains a lead; only the name may narrow it.
        rows = [r for r in self.shops.values() if r['detail'] in HOBBY_DETAILS[activity]]
        return rows

    def hobby_scope(self, profile, candidates):
        candidates=[c for c in candidates if in_supported_window(c.latitude,c.longitude)
                    and (self.boundary is None or self.boundary.area_at(c.latitude,c.longitude))]
        if not candidates: return None
        active = [c for c in profile.criteria if c.module_id=='leisure' and c.metric==HOBBY_METRIC and (c.importance>0 or c.hard)]
        if not active: return None
        activities = list(dict.fromkeys(c.parameters.get('activity') for c in active if c.parameters.get('activity') in ACTIVITIES))[:3]
        if not activities: return None
        activity_names={a:(next((c.parameters.get('activity_name') for c in active if c.parameters.get('activity')==a),None) or ACTIVITIES[a]) for a in activities}
        activities=[a for a in activities if a!='other' or activity_names[a]!=ACTIVITIES[a]]
        if not activities: return None
        areas = []
        if self.boundary:
            for candidate in candidates:
                code = self.boundary.area_at(candidate.latitude,candidate.longitude)
                if code and self.boundary.features[code]['properties']['name'] not in areas:
                    areas.append(self.boundary.features[code]['properties']['name'])
        selected = []
        for activity in activities:
            rows = [r for r in self.hobby_rows(activity,activity_names[activity]) if fresh(r)]
            rows.sort(key=lambda r:(activity_names[activity] not in r['name'],
                min(distance_m(c.latitude,c.longitude,r['lat'],r['lon']) for c in candidates),r['id']))
            selected.extend({'id':r['id'],'name':r['name'],'address':r['address'],'activity':activity,
                'registered_detail':r['detail'],'data_date':r['date']} for r in rows[:2])
        return {'city':'진주시','areas':areas[:3], 'activities':activities,'activity_names':activity_names,
                'forms':{a:list(dict.fromkeys(c.parameters.get('activity_form','') for c in active if c.parameters.get('activity')==a)) for a in activities},
                'registered_leads':selected[:6], 'unsearched_activity_count':max(0,len({(c.parameters.get('activity'),c.parameters.get('activity_name')) for c in active})-len(activities))}


class LeisureModule:
    id, version = 'leisure', 'm6-1'
    def __init__(self, index): self.index = index

    def run(self, request, cancel):
        evidence, unsupported = [], []
        for criterion in request.criteria:
            try:
                if criterion.utility and (criterion.utility.unit!='m' or criterion.utility.direction!='lower'):
                    raise ValueError('incompatible leisure utility')
                if criterion.metric == MEETING_METRIC:
                    p = criterion.parameters
                    if set(p) != {'meeting_label','meeting_latitude','meeting_longitude'}: raise ValueError('invalid meeting point')
                    lat,lon = float(p['meeting_latitude']),float(p['meeting_longitude'])
                    if criterion.source!='user' or not p['meeting_label'] or not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
                        raise ValueError('invalid explicit meeting point')
                else: self.index.select(criterion)
            except (ValueError,TypeError): unsupported.append(criterion.id); continue
            for candidate in request.candidates:
                if cancel.is_set(): raise InterruptedError('cancelled')
                if criterion.metric == MEETING_METRIC:
                    observation = {'value':round(distance_m(candidate.latitude,candidate.longitude,lat,lon),3), 'status':'verified',
                        'note':f"사용자가 지정한 {p['meeting_label']}까지 직선거리. 교류 만족도·실제 이동시간은 미확인이야.", 'selected':[]}
                    source,record,data_date = None,criterion.id,today().isoformat()
                else:
                    observation = self.index.observe(criterion,candidate)
                    row = observation['selected'][0] if observation['selected'] else None
                    source = PARK_SOURCE if criterion.metric==PARK_METRIC else LIBRARY_SOURCE
                    record,data_date = (row['id'],row['date']) if row else (None,None)
                evidence.append(Evidence(id='leisure_'+digest([candidate.id,criterion.id])[:24],candidate_id=candidate.id,
                    criterion_id=criterion.id, value=observation['value'],unit='m',status=observation['status'],source_url=source,
                    source_record=record,data_date=data_date,retrieved_at=datetime.now(timezone.utc).isoformat(),
                    source_kind='user' if criterion.metric==MEETING_METRIC else 'public',
                    method='haversine_mean_earth_6371008.8m / purpose_filter / incomplete_coverage_unscored',note=observation['note']))
        return CategoryResult(module_id=self.id,module_version=self.version,request_fingerprint=request.fingerprint(),
            status='partial' if unsupported or any(e.status!='verified' for e in evidence) else 'completed',
            evidence=evidence,unsupported_criterion_ids=unsupported,questions=[],error_code=None)
