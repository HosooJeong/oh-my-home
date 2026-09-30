"""M5: CCTV registration references; unresolved risk criteria stay unresolved."""
from collections import defaultdict
from datetime import date
import math

from ..contracts import CategoryResult, CctvObservation, SafetyReferenceResult, digest
from ..geo import distance_m, in_supported_window
from ..research_policy import today

SOURCE = 'https://www.data.go.kr/data/15143299/fileData.do'
TOPICS = {'night': '야간 보행 안전', 'traffic': '보행·교통사고', 'flood': '침수·재해',
          'noise': '소음', 'air': '대기환경'}
METRICS = {key: key + '_safety_or_environment_unverified' for key in TOPICS}


def context_value(profile, key, default=None):
    return next((c.value for c in reversed(profile.context) if c.key == key), default)


def requested_topics(profile):
    values = context_value(profile, 'safety_topics', '').split(',')
    return [key for key in TOPICS if key in values]


class CctvIndex:
    def __init__(self, document=None, boundary=None, excluded_coordinate_rows=None):
        self.document = document or {'generated_at': None, 'records': []}
        self.boundary, self.excluded = boundary, excluded_coordinate_rows
        self.records, self.points = {}, defaultdict(list)
        for row in self.document['records']:
            if row['kind'] != 'cctv': continue
            if (row['id'] in self.records or row['source_url'] != SOURCE or row['source_row'] < 1
                    or not row['name'] or not row['date_label']
                    or not all(math.isfinite(row[k]) for k in ('lat', 'lon'))
                    or not in_supported_window(row['lat'], row['lon'])):
                raise ValueError('untraceable CCTV record')
            if date.fromisoformat(row['date']) > today(): raise ValueError('future CCTV publication')
            self.records[row['id']] = row
            self.points[(row['lat'], row['lon'])].append(row)
        dates = {r['date'] for r in self.records.values()}
        if len(dates) > 1: raise ValueError('mixed CCTV snapshots')
        self.publication_date = next(iter(dates), None)
        self.fingerprint = digest(list(self.records.values())) if self.records else None

    def metadata(self):
        return {'available': bool(self.records) and self.boundary is not None,
                'registered_rows': len(self.records), 'coordinate_points': len(self.points),
                'publication_date': self.publication_date, 'retrieved_at': self.document['generated_at'],
                'excluded_coordinate_rows': self.excluded, 'source_url': SOURCE,
                'topics': TOPICS, 'score_eligible': False}

    def area(self, candidate):
        if self.boundary is None: return None
        code = self.boundary.area_at(candidate.latitude, candidate.longitude)
        if not code: return None
        return {'code': code, 'name': self.boundary.features[code]['properties']['name']}

    def observe(self, candidate, radius):
        area = self.area(candidate)
        base = dict(candidate_id=candidate.id, area_code=area['code'] if area else None,
            area_name=area['name'] if area else None, registered_rows_within_radius=None,
            registered_coordinate_points_within_radius=None, nearest_distance_m=None,
            nearest_source_records=[], purposes_within_radius=[])
        if not self.records or self.boundary is None:
            return CctvObservation(**base, status='unavailable')
        if not area: return CctvObservation(**base, status='outside_scope')
        ranked = sorted((distance_m(candidate.latitude, candidate.longitude, lat, lon), (lat, lon), rows)
                        for (lat, lon), rows in self.points.items())
        within = [rows for d, _, rows in ranked if d <= radius]
        base.update(registered_rows_within_radius=sum(len(rows) for rows in within),
                    registered_coordinate_points_within_radius=len(within),
                    nearest_distance_m=round(ranked[0][0], 3),
                    nearest_source_records=[r['id'] for r in ranked[0][2]],
                    purposes_within_radius=sorted({r['name'] for rows in within for r in rows}))
        age = (today() - date.fromisoformat(self.publication_date)).days
        return CctvObservation(**base, status='available' if age <= 365 else 'stale')

    def research_targets(self, profile, candidates):
        topics = requested_topics(profile)
        if context_value(profile, 'safety_research') != 'requested' or not topics: return []
        areas = {}
        for candidate in candidates:
            area = self.area(candidate)
            if area: areas[area['code']] = area
        # Stable bounded public areas. The UI reports remaining areas rather than silently treating them as searched.
        return [{'area_code': area['code'], 'area_name': area['name'], 'topics': topics}
                for area in sorted(areas.values(), key=lambda a: a['code'])[:3]]


class SafetyModule:
    id, version = 'safety', 'm5-1'

    def __init__(self, index): self.index = index

    def run(self, request, cancel):
        if cancel.is_set(): raise InterruptedError('cancelled')
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status='partial', evidence=[],
            unsupported_criterion_ids=[c.id for c in request.criteria], questions=[],
            error_code='risk_metrics_unverified')

    @staticmethod
    def reference_requested(profile):
        return (any(c.module_id == 'safety' for c in profile.criteria)
                or context_value(profile, 'safety_reference') == 'requested')

    def run_reference(self, profile, candidates, cancel):
        radius = float(context_value(profile, 'safety_radius_m', '500'))
        if not math.isfinite(radius) or not 0 < radius <= 5000: raise ValueError('invalid reference radius')
        observations = []
        for c in candidates:
            if cancel.is_set(): raise InterruptedError('cancelled')
            observations.append(self.index.observe(c, radius))
        statuses = {o.status for o in observations}
        return SafetyReferenceResult(module_id=self.id, module_version=self.version,
            profile_fingerprint=profile.fingerprint(), candidates_fingerprint=digest([c.model_dump() for c in candidates]),
            status='available' if statuses == {'available'} else 'partial' if statuses & {'available', 'stale'} else 'unavailable',
            radius_m=radius, source_url=SOURCE, publication_date=self.index.publication_date,
            retrieved_at=self.index.document['generated_at'], snapshot_fingerprint=self.index.fingerprint,
            excluded_coordinate_rows=self.index.excluded, observations=observations, limitations=[
                '공개본 수정일은 촬영·관측일이나 현재 작동 확인일이 아니야. CCTV 작동·방향·사각지대는 미확인.',
                '같은 좌표의 여러 등록 행을 묶었어. 좌표 지점 수는 카메라 대수나 서로 다른 설치 시설 수가 아니야.',
                '좌표 오류 분리 행은 어느 후보 반경에 포함되는지 몰라. 등록 자료의 누락도 있을 수 있어.',
                'CCTV 수·최근접 직선거리는 범죄율·야간 안전·사고·침수·소음·대기환경의 평가 근거로 사용하지 않아.',
                '직선반경은 실제 이동 경로가 아니야. 웹 조사 결과도 집이나 통학로의 안전을 보장하지 않아.'])
