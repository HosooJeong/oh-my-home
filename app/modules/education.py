"""M4 registered schools and subject-matched academies, with explicit coverage gaps."""
from datetime import date, datetime, timezone
import json
import hashlib
import math
from pathlib import Path

from ..contracts import CategoryResult, Evidence, digest
from ..geo import distance_m, in_supported_window
from ..research_policy import today

SCHOOL_SOURCE = 'https://www.data.go.kr/data/15021148/standard.do'
ACADEMY_SOURCE = 'https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN19220231012134453534385&infSeq=1'
LEVELS = {'elementary': '초등학교', 'middle': '중학교', 'high': '고등학교'}
SUBJECTS = {'math': '수학', 'english': '영어', 'korean': '국어', 'science': '과학', 'art': '미술', 'music': '음악'}
SCHOOL_METRIC = 'school_straight_line_distance_m'
ACADEMY_METRIC = 'academy_count_within_radius'


class EducationIndex:
    def __init__(self, document=None):
        self.document = document or {'retrieved_at': None, 'records': [], 'excluded': {}}
        self.records = {}
        for row in self.document['records']:
            if row['id'] in self.records or row['kind'] not in ('school', 'academy'):
                raise ValueError('duplicate or invalid education identity')
            source = SCHOOL_SOURCE if row['kind'] == 'school' else ACADEMY_SOURCE
            if not row['name'] or row['source_url'] != source or row['source_row'] < 1:
                raise ValueError('untraceable education record')
            date.fromisoformat(row['date'])
            if (row['lat'] is None) != (row['lon'] is None):
                raise ValueError('incomplete coordinates')
            if row['lat'] is not None and (not math.isfinite(row['lat']) or not math.isfinite(row['lon'])
                    or not in_supported_window(row['lat'], row['lon'])):
                raise ValueError('invalid education coordinates')
            if row['kind'] == 'academy' and not set(row['subjects']) <= set(SUBJECTS):
                raise ValueError('unsupported subject')
            self.records[row['id']] = row

    @classmethod
    def load(cls, path, inventory=None):
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        if inventory is not None and doc.get('coordinate_inventory_sha256') != hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest():
            raise ValueError('academy coordinate inventory changed; rebuild education')
        return cls(doc)

    def metadata(self):
        return {'available': bool(self.records), 'retrieved_at': self.document['retrieved_at'],
                'counts': {kind: sum(r['kind'] == kind for r in self.records.values()) for kind in ('school', 'academy')},
                'academy_unlocated': sum(r['kind'] == 'academy' and r['lat'] is None for r in self.records.values()),
                'academy_old_or_future': sum(r['kind'] == 'academy' and not 0 <= (today()-date.fromisoformat(r['date'])).days <= 365 for r in self.records.values()),
                'excluded': self.document['excluded'], 'levels': LEVELS, 'subjects': SUBJECTS,
                'limitations': '학교는 공식 위치, 학원은 같은 도로명주소 상가 좌표를 연결한 건물 수준 위치예요. 학교 배정·반 크기·보행 경로는 미확인이에요.'}

    def select(self, criterion):
        p = criterion.parameters
        if criterion.metric == SCHOOL_METRIC and set(p) <= {'school_level', 'school_id'} and p.get('school_level') in LEVELS:
            return [r for r in self.records.values() if r['kind'] == 'school' and r['level'] == p['school_level']
                    and (not p.get('school_id') or r['id'] == p['school_id'])], None
        if criterion.metric == ACADEMY_METRIC and set(p) <= {'subject', 'radius_m', 'school_level'} and p.get('subject') in SUBJECTS:
            radius = float(p.get('radius_m', 'nan'))
            if not math.isfinite(radius) or not 0 < radius <= 20000 or p.get('school_level') not in LEVELS:
                raise ValueError('invalid academy scope')
            # Adult-only courses are excluded in preparation; grade unknown remains an uncertainty.
            result = []
            for r in self.records.values():
                if r['kind'] != 'academy' or (r['subjects'] and p['subject'] not in r['subjects']):
                    continue
                levels = r['subject_levels'].get(p['subject'], [])
                if not levels or p['school_level'] in levels:
                    result.append({**r, 'levels': levels})
            return result, radius
        raise ValueError('unsupported education metric or scope')

    def observe(self, criterion, candidate):
        rows, radius = self.select(criterion)
        now = today()
        # Use the school's reference date / NEIS row linkage date, never download time or founding date.
        ranked, uncertain = [], []
        for row in rows:
            dates = [row['date']]
            if row['kind'] == 'academy' and row['lat'] is not None:
                dates.append(row.get('coordinate_date') or '1900-01-01')
            if any(not 0 <= (now - date.fromisoformat(value)).days <= 365 for value in dates) or row['lat'] is None:
                uncertain.append(row); continue
            distance = distance_m(candidate.latitude, candidate.longitude, row['lat'], row['lon'])
            if radius is not None and distance > radius:
                continue
            if row['kind'] == 'academy' and not row['levels']:
                uncertain.append(row); continue
            ranked.append((distance, row))
        ranked.sort(key=lambda item: (item[0], item[1]['id']))
        if criterion.metric == SCHOOL_METRIC:
            value = round(ranked[0][0], 3) if ranked else None
            selected = ranked[:1]
        else:
            value, selected = float(len(ranked)), ranked[:10]
        available = bool(self.records) and in_supported_window(candidate.latitude, candidate.longitude)
        status = 'verified' if available and not uncertain and (ranked or radius is not None) else 'missing'
        if not available:
            value = None; selected = []
        label = ('학교까지 직선거리. 최근접은 배정을 뜻하지 않아요.' if radius is None else
                 f'{radius:g}m 직선반경 안에 과목·학령·위치를 확인한 학원 {len(ranked)}개소. 과정 수를 중복 집계하지 않았어요.')
        note = label + f' 진주 해당 자료 중 위치/학령/자료 시점 미확인 {len(uncertain)}개소. '
        if radius is not None and uncertain:
            note += '이 미확인 시설이 반경 안에 포함되는지도 확정할 수 없어요. '
        if uncertain:
            note += '누락이 있어 전체 최단거리/개소 수와 점수는 확정하지 않았어요. '
        note += '등록정원·일시수용인원은 실제 반 크기가 아니에요. 도보 경로·횡단·현재 모집은 미확인.'
        return {'value': value, 'status': status, 'note': note, 'selected': [r for _, r in selected],
                'confirmed_count': len(ranked), 'uncertain_count': len(uncertain)}


class EducationModule:
    id, version = 'education', 'm4-1'

    def __init__(self, index):
        self.index = index

    def run(self, request, cancel):
        evidence, unsupported = [], []
        for criterion in request.criteria:
            try:
                self.index.select(criterion)
                unit, direction = ('m', 'lower') if criterion.metric == SCHOOL_METRIC else ('count', 'higher')
                if criterion.utility and (criterion.utility.unit != unit or criterion.utility.direction != direction):
                    raise ValueError('incompatible utility')
            except (ValueError, TypeError):
                unsupported.append(criterion.id); continue
            for candidate in request.candidates:
                if cancel.is_set():
                    raise InterruptedError('cancelled')
                observation = self.index.observe(criterion, candidate)
                rows = observation['selected']
                source = SCHOOL_SOURCE if unit == 'm' else ACADEMY_SOURCE
                evidence.append(Evidence(id='education_' + digest([criterion.id, candidate.id])[:24],
                    criterion_id=criterion.id, candidate_id=candidate.id, value=observation['value'], unit=unit,
                    status=observation['status'], source_url=source,
                    source_record=rows[0]['id'] if unit == 'm' and rows else 'education-snapshot',
                    data_date=rows[0]['date'] if rows else (self.index.document['retrieved_at'] or '')[:10] or None,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    method='haversine_mean_earth_6371008.8m / official_scope / unique_registration / incomplete_coverage_unscored',
                    note=observation['note']))
        return CategoryResult(module_id=self.id, module_version=self.version, request_fingerprint=request.fingerprint(),
            status='partial' if unsupported or any(e.status != 'verified' for e in evidence) else 'completed',
            evidence=evidence, unsupported_criterion_ids=unsupported, questions=[], error_code=None)
