"""Apply only fields the user edited; never flatten an ambiguous context."""
import json

FIELD_LABELS = {
    'mode':'이동수단', 'destination':'목적지', 'time_of_day':'이용 시간대',
    'include_stop':'정류장 평가 포함', 'ideal':'거리 목표', 'limit':'거리 만족도 0 기준',
    'group_weight':'분야 중요도', 'importance':'정류장 중요도',
    'mandatory_limit':'정류장 필수 제한 적용', 'hard_limit':'정류장 필수 제한 거리',
    'school_level':'학교급', 'include_school':'학교 평가 포함', 'school_ideal':'학교 거리 목표',
    'school_limit':'학교 거리 만족도 0 기준', 'school_importance':'학교 중요도',
    'include_academy':'학원 평가 포함', 'subject':'학원 과목', 'radius_m':'조회 반경',
    'sufficient_count':'충분한 학원 개소', 'academy_importance':'학원 중요도',
    'travel_mode':'통학 방식', 'qualitative_research':'웹 보완 조사',
    'topics':'안전·환경 관심 문제', 'criterion_importance':'선택 조건별 중요도',
    'include_park':'공원 평가 포함', 'park_type':'공원 종류', 'park_importance':'공원 중요도',
    'include_library':'도서관 평가 포함', 'library_type':'도서관 종류', 'library_importance':'도서관 중요도',
    'include_meeting':'만남 지점 평가 포함', 'meeting_label':'만남 지점 이름',
    'meeting_latitude':'만남 지점 위도', 'meeting_longitude':'만남 지점 경도', 'meeting_importance':'만남 지점 중요도',
    'include_hobby':'취미 조사 포함', 'activity':'취미 종목', 'activity_name':'취미 이름',
    'activity_form':'취미 이용 형태', 'hobby_importance':'취미 중요도',
    'supermarket_weight':'마트 중요도', 'convenience_weight':'편의점 중요도',
}


class PreservationError(ValueError):
    """A safe user-facing explanation for edits the form cannot represent."""


def edited(data, *fields):
    names = getattr(data, 'edited_fields', None)
    if names is None:
        return True  # Existing API callers explicitly submit a complete form.
    if set(names) - (set(type(data).model_fields) - {'profile', 'edited_fields'}):
        raise PreservationError('수정할 항목을 확인해 주세요.')
    return bool(set(fields) & set(names))


def edit_quote(data, full_quote):
    """Do not describe unchanged form defaults as newly confirmed needs."""
    names = getattr(data, 'edited_fields', None)
    if names is None or data.profile is None:
        return full_quote
    edited(data)  # Validate the field names before recording them.
    values = data.model_dump()
    return '조건 수정: ' + '; '.join(
        FIELD_LABELS[key] + ' = ' + json.dumps(values[key],ensure_ascii=False)
        for key in dict.fromkeys(names)) if names else ''


def replace_context(document, values, quote):
    for key, value in values.items():
        old = [c for c in document['context'] if c['key'] == key]
        if old and old[0]['value'] == value:
            continue
        if len(old) > 1:
            raise PreservationError('여러 사람의 이동 조건이 있어요. 이 입력란으로 함께 바꾸지 않고 원래 조건을 유지했어요. 인터뷰에서 바꿀 사람과 동선을 알려주세요.')
        document['context'] = [c for c in document['context'] if c['key'] != key]
        if value:
            document['context'].append(dict(key=key, value=value, source_quote=quote))


def preserve_need(criterion, values, quote):
    """Keep the original need/label and any parameters outside this form."""
    changes = {k:v for k,v in values.items() if criterion.get(k) != v}
    if changes:
        criterion.update(changes)
        if any(k in changes for k in ('utility', 'parameters', 'hard')):
            criterion.update(source='user', source_quote=quote)
