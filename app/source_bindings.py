"""Bind separate original clauses to need fields without accepting arbitrary links.

These bounded checks cover supported distance metrics and explicit numeric fields.
They are not a general semantic classifier; uncertain links go to the interview.
"""
import re


TARGETS = {
    'grocery_straight_line_distance_m': r'마트|슈퍼|장보기',
    'house_to_grocery_straight_line_distance_m': r'마트|슈퍼|장보기',
    'convenience_straight_line_distance_m': r'편의점',
    'bus_stop_straight_line_distance_m': r'정류장',
    'school_straight_line_distance_m': r'학교|초등|중등|고등',
    'academy_count_within_radius': r'학원|교습소',
    'park_straight_line_distance_m': r'공원',
    'library_straight_line_distance_m': r'도서관',
    'meeting_straight_line_distance_m': r'모임|만남|지점',
    'pharmacy_straight_line_distance_m': r'약국',
    'clinic_straight_line_distance_m': r'내과|소아과|의원',
    'everyday_meal_straight_line_distance_m': r'백반|한정식|분식|김밥|국[·/]|식사',
    'restaurant_straight_line_distance_m': r'음식점|식당|외식',
}
SUBJECT = re.compile(r'마트|슈퍼|편의점|정류장|학교|학원|교습소|공원|도서관|필라테스|헬스|탁구|수영|가족\s*모임|약국|내과|소아과|의원|백반|분식|식사|음식점|식당|외식')
QUALIFIER = re.compile(r'비중|중요|두\s*(?:조건|곳)|둘|접근성|비슷|동일|거리|기준|이내|이상|이하|필수|상관\s*없|유형')
MANDATORY = re.compile(r'필수|반드시|무조건|해야|여야|넘지\s*않')
NUMBER = r'[-+]?\d+(?:,\d{3})*(?:\.\d+)?'


def numbers(text, unit=None):
    if unit == 'm':
        found = re.findall(r'(' + NUMBER + r')\s*(km|㎞|킬로미터|m|ｍ|미터)(?![a-z])', text, re.I)
        return {float(value.replace(',', '')) * (1000 if u.lower() in ('km', '㎞', '킬로미터') else 1)
                for value, u in found}
    return {float(value.replace(',', '')) for value in re.findall(NUMBER, text)}


def distance_values(text, criterion):
    """Named distances in a shared sentence still belong to their own facility."""
    pattern = TARGETS.get(criterion['metric'])
    if not pattern or not re.search(pattern, text):
        return numbers(text, 'm')
    values = set()
    for match in re.finditer(pattern, text):
        rest = text[match.end():]
        next_subject = SUBJECT.search(rest)
        if next_subject:
            prefix = rest[:next_subject.start()]
            if re.fullmatch(r'\s*(?:와|과|및|,|·|/)\s*', prefix):
                rest = rest[next_subject.end():]
                following = SUBJECT.search(rest)
                if following:rest = rest[:following.start()]
            else:
                rest = prefix
        values.update(numbers(rest, 'm'))
    return values


PARAMETER_WORDS = {
    'school_level': {'elementary':r'초등', 'middle':r'중학|중등', 'high':r'고등|고교', 'kindergarten':r'유치원'},
    'subject': {'math':r'수학', 'english':r'영어', 'korean':r'국어', 'science':r'과학', 'coding':r'코딩|프로그래밍'},
    'park_type': {'children':r'어린이', 'neighborhood':r'근린'},
    'library_type': {'public':r'공공|공립', 'small':r'작은'},
    'activity': {'gym':r'헬스|체육관', 'pilates':r'필라테스', 'table_tennis':r'탁구', 'swimming':r'수영',
                 'tennis':r'테니스', 'yoga':r'요가'},
}


def parameters_grounded(parameters, text):
    for key,value in parameters.items():
        if key in ('radius_m','meeting_latitude','meeting_longitude'):
            try:valid = float(value) in numbers(text, 'm' if key=='radius_m' else None)
            except (ValueError,TypeError):valid = False
            if not valid:return False
        elif key in PARAMETER_WORDS and value in PARAMETER_WORDS[key]:
            if not re.search(PARAMETER_WORDS[key][value],text):return False
        # any is the absence of a type filter, not an invented facility requirement.
    return True


def scope_matches(text, criterion, primary, source_id, sources, previous, answers):
    if text == primary:
        return True
    pattern = TARGETS.get(criterion['metric'])
    if pattern and re.search(pattern, text):
        return True
    if SUBJECT.search(text):
        return False
    if previous:
        for answer in answers:
            if answer.answer == text and any(q.id == answer.question_id and criterion['id'] in q.criterion_ids
                                           for q in previous.questions):
                return True
    # A bare qualifier may continue the same local clause, but never across a category heading.
    if not QUALIFIER.search(text) and not numbers(text, 'm'):
        return False
    keys = list(sources)
    position = keys.index(source_id)
    paired_weight = bool(re.search(r'(비중|중요도|두\s*조건)', text) and re.search(r'\d\s*:\s*\d', text))
    for key in reversed(keys[max(0, position - (6 if paired_weight else 3)):position]):
        preceding = sources[key]
        if re.match(r'(생활·건강|교통·동선|교육·육아|안전·환경|여가·관계|집·비용):', preceding):
            return False
        if preceding == primary or pattern and re.search(pattern, preceding):
            return True
        if SUBJECT.search(preceding) and not paired_weight:
            return False
    return False


def importance_values(text, criterion, criteria, sources):
    if not re.search(r'%|퍼센트|비중|중요도|\d\s*:\s*\d', text) and not re.fullmatch(NUMBER, text.strip()):
        return set()
    pattern = TARGETS.get(criterion['metric'])
    if pattern and re.search(pattern, text):
        # Separate "마트 70%, 편의점 30%" rather than accepting either number for either need.
        values = set()
        for match in re.finditer(pattern, text):
            rest = text[match.end():]
            next_subject = SUBJECT.search(rest)
            if next_subject:
                rest = rest[:next_subject.start()]
            values.update(numbers(rest))
        return values
    ratio = re.search(r'(' + NUMBER + r')\s*:\s*(' + NUMBER + r')', text)
    if ratio:
        # A local "두 조건 70:30" follows the order of the two original named needs.
        group = [c for c in criteria.values() if c['group_id'] == criterion['group_id'] and c['importance'] > 0]
        if len(group) == 2:
            def order(c):
                position=next((i for i,t in enumerate(sources.values()) if t==c['source_quote']),len(sources))
                match=re.search(TARGETS.get(c['metric'],r'(?!)'),c['source_quote'])
                return position,match.start() if match else len(c['source_quote'])
            group.sort(key=order)
            return {float(ratio.group(group.index(criterion) + 1).replace(',', ''))}
        return set()
    return numbers(text)


def bind_fields(doc, sources, needs, previous=None, answers=()):
    """Return accepted rows and uncertain clauses; keep exact quotes in the profile."""
    criteria = {c['id']: c for c in doc['criteria']}
    bindings = {id: {'need': [c['source_quote']]} for id, c in criteria.items()}
    field_protocol = any('field' in n.model_fields_set for n in needs)
    old = {c.id: c for c in previous.criteria} if previous else {}
    for id, c in criteria.items():
        if id not in old or old[id].metric != c['metric']:
            continue
        for binding in old[id].source_evidence:
            # An interview can change one field without losing the others' exact original sources.
            if binding.field != 'context' and old[id].model_dump()[binding.field] == c[binding.field]:
                bindings[id][binding.field] = list(binding.quotes)

    accepted, uncertain, issues = [], {}, []
    for n in needs:
        texts = [sources[n.source_id]]
        if n.resolution_source_id:
            texts.append(sources[n.resolution_source_id])
        bad = []
        for id in n.criterion_ids:
            c = criteria[id]
            linked = scope_matches(texts[0], c, c['source_quote'], n.source_id, sources, previous, answers)
            # A resolution cannot launder an unrelated original clause. It must answer this need's question.
            if not linked and id in old and texts[0] == old[id].source_quote:
                linked = old[id].metric == c['metric'] or bool(n.resolution_source_id and any(
                    answer.answer == sources[n.resolution_source_id] and any(
                        q.id == answer.question_id and id in q.criterion_ids for q in previous.questions)
                    for answer in answers))
            if not linked:
                bad.append(id)
        for key in n.context_keys:
            facts = [c for c in doc['context'] if c['key'] == key]
            linked = any(c['source_quote'] in t or t in c['source_quote'] or t in c['source_quotes']
                         for c in facts for t in texts)
            if not linked and n.field == 'context':
                # Repeated explicit housing instructions can share one context value.
                # Keep both original quotes; never use this for criteria or arbitrary context keys.
                intent = {
                    ('housing_reference', 'requested'): r'실거래[^.!?\n]{0,30}참고',
                    ('housing_price_scoring', 'excluded'): r'(?:집값|가격)[^.!?\n]{0,30}(?:점수|순위)[^.!?\n]{0,30}(?:제외|반영하지\s*않)',
                }
                linked = any((pattern := intent.get((key, c['value'])))
                             and re.search(pattern, c['source_quote'])
                             and any(re.search(pattern, t) for t in texts) for c in facts)
            if not linked:
                # Shared research flags can have separate requests concerning the same facility type.
                linked = n.field == 'context' and any(
                    set(SUBJECT.findall(c['source_quote'])) & set(SUBJECT.findall(t))
                    and re.search(r'검색|조사|후기|인용|참고', t) for c in facts for t in texts)
            if not linked:
                bad.extend(n.criterion_ids)
                uncertain.setdefault(n.source_id, set()).update(n.criterion_ids)
                issues.append({'source_id': n.source_id, 'field': 'context', 'code': 'unrelated_context'})
                break
        else:
            if not bad:
                accepted.append(n)
                for id in n.criterion_ids:
                    field = n.field if n.field != 'context' else 'need'
                    quotes = bindings[id].setdefault(field, [])
                    for t in texts:
                        if t not in quotes:
                            quotes.append(t)
                for key in n.context_keys:
                    for c in doc['context']:
                        if c['key'] == key:
                            c['source_quotes'] = list(dict.fromkeys([c['source_quote'], *c['source_quotes'], *texts]))[:12]
                continue
        uncertain.setdefault(n.source_id, set()).update(bad)
        issues.append({'source_id': n.source_id, 'field': n.field, 'code': 'unrelated_condition'})

    for id, c in criteria.items():
        fields = bindings[id]
        if field_protocol:
            primary = fields['need']
            checks = []
            if c['utility'] and c['utility']['unit'] != 'bool':
                quotes = fields.get('utility', []) or primary
                values = set().union(*(distance_values(t,c) if c['utility']['unit']=='m' else numbers(t)
                                       for t in quotes))
                if not {c['utility']['ideal'], c['utility']['limit']} <= values:
                    checks.append(('utility', quotes))
                else:
                    fields['utility'] = quotes
            if c['importance_source'] == 'user':
                quotes = fields.get('importance', []) or primary
                values = set().union(*(importance_values(t, c, criteria, sources) for t in quotes))
                excluded = c['importance'] == 0 and any(re.search(r'제외|필요\s*없|상관\s*없', t) for t in quotes)
                if c['importance'] not in values and not excluded:
                    checks.append(('importance', quotes))
                else:
                    fields['importance'] = quotes
            if c['hard']:
                quotes = fields.get('hard', []) or primary
                joined = ' '.join(quotes)
                values=set().union(*(distance_values(t,c) if c['utility']['unit']=='m' else numbers(t)
                                     for t in quotes))
                if not MANDATORY.search(joined) or (c['utility']['unit'] != 'bool'
                        and c['hard']['value'] not in values):
                    checks.append(('hard', quotes))
                else:
                    fields['hard'] = quotes
            if c['parameters']:
                # A school-level answer refines, rather than replaces, the original subject.
                quotes=list(dict.fromkeys([*primary,*fields.get('parameters',[])]))
                if not parameters_grounded(c['parameters'],' '.join(quotes)):
                    checks.append(('parameters',quotes))
                else:
                    fields['parameters']=quotes
            for field, quotes in checks:
                source_id = next((key for key, text in sources.items() if text == quotes[0]), None)
                if source_id:
                    uncertain.setdefault(source_id, set()).add(id)
                    issues.append({'source_id': source_id, 'criterion_id': id, 'field': field,
                                   'code': 'ungrounded_field'})
        c['source_evidence'] = [{'field': field, 'quotes': quotes[:12]} for field, quotes in fields.items()]
    return accepted, uncertain, issues
