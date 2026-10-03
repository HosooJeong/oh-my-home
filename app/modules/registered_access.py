"""Access to registered health and dining facilities; never quality or safety scores."""
from datetime import date, datetime, timezone
from ..contracts import CategoryResult, Evidence, digest
from ..geo import distance_m, in_supported_window

HEALTH_TYPES = {
    'pharmacy_straight_line_distance_m': {'약국'},
    'clinic_straight_line_distance_m': {'내과/소아과 의원'},
}
DINING_TYPES = {
    'everyday_meal_straight_line_distance_m': {'백반/한정식', '국/탕/찌개류', '김밥/만두/분식'},
    'restaurant_straight_line_distance_m': {
        '백반/한정식', '국/탕/찌개류', '김밥/만두/분식', '국수/칼국수', '중국집', '경양식',
        '기타 한식 음식점', '기타 서양식 음식점', '기타 일식 음식점', '분류 안된 외국식 음식점',
        '일식 회/초밥', '횟집', '소고기 구이/찜', '돼지고기 구이/찜', '닭/오리고기 구이/찜',
        '해산물 구이/찜', '곱창 전골/구이', '피자', '치킨', '그 외 기타 간이 음식점',
    },
}
TYPES = {'health': HEALTH_TYPES, 'dining': DINING_TYPES}


class RegisteredAccessModule:
    version = 'registered-access-1'

    def __init__(self, module_id, index, as_of=None):
        self.id, self.index = module_id, index
        self.types = TYPES[module_id]
        self.as_of = as_of
        self.groups = {metric: [r for r in index.records.values() if r['detail'] in details]
                       for metric, details in self.types.items()}

    def run(self, request, cancel):
        evidence, unsupported = [], []
        now = datetime.now(timezone.utc)
        today = self.as_of or now.date()
        for criterion in request.criteria:
            if criterion.metric not in self.types or (criterion.utility and
                    (criterion.utility.unit != 'm' or criterion.utility.direction != 'lower')):
                unsupported.append(criterion.id)
                continue
            for candidate in request.candidates:
                if cancel.is_set():
                    raise InterruptedError('cancelled')
                rows = self.groups[criterion.metric] if in_supported_window(candidate.latitude, candidate.longitude) else []
                row = min(rows, key=lambda r: (distance_m(candidate.latitude, candidate.longitude,
                    r['lat'], r['lon']), r['id'])) if rows else None
                # A stale nearest record must not be silently skipped in favour of a farther one.
                try:
                    fresh = row is not None and 0 <= (today - date.fromisoformat(row['date'])).days <= 365
                except (ValueError, TypeError):
                    fresh = False
                value = round(distance_m(candidate.latitude, candidate.longitude, row['lat'], row['lon']), 3) if fresh else None
                note = (f"{row['name']} · 원본 업종 {row['detail']} · {row['source_member']} {row['source_row']}행. "
                        '진주 등록자료에서 해당 업종의 최단 직선거리. 현재 운영·실제 경로·이용 가능성은 미확인. '
                        if row else '지원 범위 밖이거나 해당 업종의 등록자료가 없어요. ')
                if row and not fresh:
                    note += '자료 기준일이 불명확하거나 365일을 넘겨 충족도 계산을 보류했어요. '
                note += ('의료기관의 진료과·진료 수준·응급 대응을 평가하지 않아요.' if self.id == 'health'
                         else '음식의 품질·가격·식단 적합성을 평가하지 않아요.')
                evidence.append(Evidence(id=self.id + '_' + digest([candidate.id, criterion.id])[:24],
                    candidate_id=candidate.id, criterion_id=criterion.id, value=value, unit='m',
                    status='verified' if fresh else 'missing', source_url=row['source_url'] if row else None,
                    source_record=row['id'] if row else None, data_date=row['date'] if row else None,
                    retrieved_at=now.isoformat() if row else None,
                    method='haversine_mean_earth_6371008.8m / jinju_registered_industry_v1', note=note))
        return CategoryResult(module_id=self.id, module_version=self.version,
            request_fingerprint=request.fingerprint(), status='partial' if unsupported or any(
                e.status != 'verified' for e in evidence) else 'completed', evidence=evidence,
            unsupported_criterion_ids=unsupported, questions=[], error_code=None)
