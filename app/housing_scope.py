"""Resolve explicit reference filters without silently widening an unsupported request."""
import re

FIELDS={'housing_tenure':'tenure','housing_legal_area':'legal_area',
        'housing_area_min_m2':'area_min_m2','housing_area_max_m2':'area_max_m2',
        'housing_area_max_inclusive':'area_max_inclusive','housing_contract':'contract'}


def housing_scope(profile, legal_areas, available):
    from .modules.housing import HousingQuery
    facts={};errors=[]
    for fact in profile.context:
        if not fact.key.startswith('housing_'):continue
        if fact.key in facts and facts[fact.key].value!=fact.value:
            errors.append('서로 다른 가격 조회 조건이 있어. 한 조회 범위를 정해 줘.')
        facts[fact.key]=fact
    values={}
    for key,target in FIELDS.items():
        if key not in facts:continue
        value=facts[key].value
        if target in ('area_min_m2','area_max_m2'):
            try:
                value=float(value)
                if value not in [float(n) for n in re.findall(r'\d+(?:\.\d+)?',facts[key].source_quote)]:
                    raise ValueError('unquoted area')
            except ValueError:errors.append('전용면적 수치를 원문에서 확인하지 못했어.');continue
        if target=='area_max_inclusive':
            if value not in ('true','false'):
                errors.append('면적의 최대값 포함 여부를 확인하지 못했어.');continue
            value=value=='true'
        values[target]=value
    if 'housing_legal_area' in facts and re.sub(r'\s+','',facts['housing_legal_area'].value) not in re.sub(r'\s+','',facts['housing_legal_area'].source_quote):
        errors.append('법정동 이름을 원문에서 확인하지 못했어.')
    for key in ('housing_area_min_m2','housing_area_max_m2'):
        if key not in facts:continue
        quote=facts[key].source_quote
        if re.search(r'\d+(?:\.\d+)?\s*평|공급\s*면적',quote):errors.append('평·공급면적을 전용면적 ㎡로 임의 환산하지 않았어.')
        if key=='housing_area_min_m2' and '초과' in quote:errors.append('면적 최소값 초과 조건은 현재 지원하지 않아.')
        if key=='housing_area_max_m2':
            bounds=[end for n,end in re.findall(r'(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2|제곱미터)?\s*(이하|미만|까지)',quote)
                    if float(n)==values.get('area_max_m2')]
            if not bounds:errors.append('전용면적 최대값의 포함 여부를 원문에서 확인해야 해.')
            elif (bounds[-1]!='미만')!=values.get('area_max_inclusive',False):errors.append('면적 최대값 포함 여부와 원문이 달라.')
    if available and values.get('legal_area') and values['legal_area'] not in legal_areas:
        errors.append('요청 지역을 준비된 법정동 자료에서 확인하지 못했어. 다른 지역으로 넓혀 조회하지 않았어.')
    if 'housing_type' in facts and facts['housing_type'].value not in ('아파트','apartment'):
        errors.append('현재 실거래 참고는 아파트만 지원해. 요청한 주택유형으로 조회하지 않았어.')
    if 'housing_area' in facts:
        raw=facts['housing_area'].value
        if not any(key in facts for key in ('housing_area_min_m2','housing_area_max_m2')) or re.search(r'\d+(?:\.\d+)?\s*평|공급|초과',raw):
            errors.append('전용면적 ㎡ 범위를 확인해야 해. 평·공급면적을 임의 환산하지 않았어.')
        if '이하' in raw and 'housing_area_max_inclusive' not in facts:
            errors.append('면적 최대값 포함 여부가 빠졌어. 더 넓거나 좁은 범위로 대신 조회하지 않았어.')
    if 'housing_budget' in facts:
        errors.append('금액 조건으로 거래를 거르는 기능은 아직 지원하지 않아. 지역 분포로 예산 충족을 판단하지 않았어.')
    if 'housing_location' in facts and 'housing_legal_area' not in facts:
        errors.append('요청 지역의 법정동을 확인하지 못했어. 진주 전체로 대신 조회하지 않았어.')
    try:query=HousingQuery.model_validate(values)
    except ValueError:
        query=None;errors.append('거래 방식·면적·계약 구분을 지원하는 조회 형식으로 확인해야 해.')
    return query,list(dict.fromkeys(errors))
