"""Explicit transport edits preserve other needs; the model never sets these values."""
from typing import Annotated, Literal
from pydantic import Field

from .contracts import Contract, NeedProfile, Weight
from .modules.transport import METRIC
from .preference_edits import edited, replace_context, preserve_need, edit_quote, PreservationError

MODES = {"unknown": "미정", "bus": "버스 중심", "car": "자차 중심",
         "walking": "도보 중심", "mixed": "여러 수단 이용"}


class TransportInput(Contract):
    profile: NeedProfile
    mode: Literal["unknown", "bus", "car", "walking", "mixed"]
    destination: Annotated[str, Field(max_length=200)]
    time_of_day: Annotated[str, Field(max_length=120)]
    include_stop: bool
    ideal: Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]
    limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)]
    group_weight: Weight
    importance: Weight
    mandatory_limit: bool
    hard_limit: Annotated[float, Field(gt=0, le=50000, allow_inf_nan=False)] | None = None
    edited_fields: Annotated[list[str], Field(max_length=20)] | None = None


def transport_profile(data: TransportInput) -> NeedProfile:
    if data.edited_fields == []: return data.profile.model_copy(deep=True)
    if data.include_stop and data.ideal >= data.limit:
        raise ValueError("invalid transport distance thresholds")
    document = data.profile.model_dump()
    document["revision"] += 1
    stops = [c for c in document["criteria"] if c["module_id"] == "transport" and c["metric"] == METRIC]
    if len(stops) > 1:
        raise ValueError("ambiguous stop criteria")
    stop = stops[0] if stops else None
    hard = None
    if data.include_stop and data.mandatory_limit:
        if stop and stop['hard'] and stop['hard']['operator'] != 'lte':
            raise PreservationError('현재 필수조건은 이 거리 입력란으로 바꿀 수 없어. 원래 조건을 유지했어.')
        value = data.hard_limit if data.hard_limit is not None else stop['hard']['value'] if stop and stop['hard'] else data.limit
        hard = {'operator': 'lte', 'value': value}
    quote = (f"교통 조건 확인: 이동수단 {MODES[data.mode]}, 목적지 {data.destination.strip() or '미정'}, "
             f"이용 시간대 {data.time_of_day.strip() or '미정'}. "
             + (f"정류장 직선거리 {data.ideal:g}m 목표, {data.limit:g}m 만족도 0; "
                f"분야 중요도 {data.group_weight:g}, 정류장 조건 중요도 {data.importance:g}; "
                + (f"반드시 {hard['value']:g}m 이하." if hard else "정류장 필수 제한 없음.")
                if data.include_stop else "정류장 거리 조건은 평가에서 제외해."))
    quote = edit_quote(data, quote)
    if quote: document["request"] += "\n" + quote
    # Stable context keys keep route inputs available without pretending to query a route.
    context_values = {"travel_mode": MODES[data.mode], "travel_destination": data.destination.strip(),
                      "travel_time": data.time_of_day.strip()}
    context_fields = {'travel_mode': 'mode', 'travel_destination': 'destination', 'travel_time': 'time_of_day'}
    replace_context(document, {k:v for k,v in context_values.items() if edited(data,context_fields[k])}, quote)
    if data.include_stop:
        if stop is None:
            existing = {c["id"] for c in document["criteria"]}
            id, suffix = "bus_stop", 1
            while id in existing:
                suffix += 1
                id = "bus_stop_" + str(suffix)
            stop = {"id": id, "group_id": "transport", "module_id": "transport", "metric": METRIC}
            document["criteria"].append(stop)
        if 'need' not in stop:
            stop.update(label='버스정류장', need='등록 정류장까지 직선거리', source_quote=quote,
                        source='user', importance=data.importance, importance_source='user',
                        utility={'direction':'lower','ideal':data.ideal,'limit':data.limit,'unit':'m'}, hard=hard, parameters={})
        values = {}
        if edited(data,'ideal','limit'):
            if stop['utility'] and (stop['utility']['unit'] != 'm' or stop['utility']['direction'] != 'lower'):
                raise PreservationError('기존 이동 기준은 직선거리와 달라. 원래 조건을 유지했어.')
            values['utility'] = {'direction':'lower','ideal':data.ideal,'limit':data.limit,'unit':'m'}
        if edited(data,'mandatory_limit','hard_limit'):
            values['hard'] = hard
        if edited(data,'importance'):
            values.update(importance=data.importance, importance_source='user')
        preserve_need(stop, values, quote)
        group = next((g for g in document["groups"] if g["id"] == stop["group_id"]), None)
        if group is None:
            group = {"id": stop["group_id"], "label": "교통·동선"}
            document["groups"].append(group)
        if edited(data,'group_weight') or 'weight' not in group:
            group.update(weight=data.group_weight, source="user", reason="사용자가 교통 중요도를 확인했어.")
        if edited(data,'ideal','limit'):
            document["questions"] = [q for q in document["questions"] if not (
            q["criterion_ids"] == [stop["id"]] and "직선거리" in q["text"]
            and any(word in q["text"] for word in ("기준", "목표", "허용", "이상적")))]
    elif stop and edited(data,'include_stop'):
        stop.update(importance=0.0, importance_source="user", source="user", source_quote=quote, hard=None)
        document["questions"] = [q for q in document["questions"] if q["criterion_ids"] != [stop["id"]]]
        members = [c for c in document["criteria"] if c["group_id"] == stop["group_id"]]
        if not any(c["importance"] > 0 for c in members):
            next(g for g in document["groups"] if g["id"] == stop["group_id"]).update(
                weight=0.0, source="user", reason="사용자가 정류장 평가를 제외했어.")
    return NeedProfile.model_validate(document)
