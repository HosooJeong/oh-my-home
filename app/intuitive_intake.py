"""Optional app comparison scales for qualitative preferences, with visible provenance."""
import re
from .contracts import NeedProfile
from .source_bindings import TARGETS, SUBJECT, distance_values, numbers

DISTANCE_METRICS = set(TARGETS) - {'academy_count_within_radius'}
COUNT_METRIC = 'academy_count_within_radius'

CLOSE_PATTERN = re.compile(r'코앞|바로\s*앞|바로\s*(?:가까이|가까운|근처|곁)|(?:아주|매우)\s*가까')
CLOSE_NEGATED = re.compile(r'(?:' + CLOSE_PATTERN.pattern + r').{0,12}(?:아니|않아도|없어도|부담|필요\s*없)')


def very_close_preference(criterion, quotes):
    """Read the facility's original clause, independent of model paraphrasing."""
    for quote in quotes:
        for match in re.finditer(TARGETS[criterion['metric']], quote):
            rest = re.split(r'[.!?;\n]', quote[match.end():], maxsplit=1)[0]
            next_subject = SUBJECT.search(rest)
            if next_subject:
                prefix = rest[:next_subject.start()]
                if re.fullmatch(r'\s*(?:와|과|및|,|·|/)\s*', prefix):
                    rest = rest[next_subject.end():]
                    following = SUBJECT.search(rest)
                    if following:
                        rest = rest[:following.start()]
                else:
                    rest = prefix
            if CLOSE_PATTERN.search(rest) and not CLOSE_NEGATED.search(rest):
                return True
    return False


def restore_proposal_inputs(profile, previous, sources=None, needs=()):
    """A prior app scale must not be reinterpreted as a user's numeric answer."""
    if not previous:
        return profile
    doc = profile.model_dump()
    old = {c.id: c for c in previous.criteria}
    for c in doc['criteria']:
        prior = old.get(c['id'])
        def explicit(field, values, unit):
            return any(n.field==field and c['id'] in n.criterion_ids and values <= numbers(
                (sources or {}).get(n.resolution_source_id or n.source_id,''),unit) for n in needs or [])
        if (prior and prior.metric==c['metric'] and prior.importance_proposal is not None and c['importance']==prior.importance_proposal==prior.importance
                and not explicit('importance',{prior.importance_proposal},None)):
            c['importance_source']='proposed'
            c['importance_proposal']=prior.importance_proposal
        proposal = prior.comparison_proposal if prior else None
        if not proposal or c['metric'] != prior.metric or c['hard']:
            continue
        if (prior.utility and c['utility'] == proposal.utility.model_dump() == prior.utility.model_dump()
                and not explicit('utility',{proposal.utility.ideal,proposal.utility.limit},proposal.utility.unit)):
            c['utility'] = None
        if (proposal.radius_m is not None
                and c['parameters'].get('radius_m') == prior.parameters.get('radius_m')
                and float(prior.parameters['radius_m']) == proposal.radius_m
                and not explicit('parameters',{proposal.radius_m},'m')):
            c['parameters'].pop('radius_m', None)
        c['comparison_proposal'] = None
    return NeedProfile.model_validate(doc)


def add_comparison_proposals(profile):
    """Fill only missing soft scales. Explicit numeric and mandatory requests stay intact."""
    doc = profile.model_dump()
    count = 0
    for c in doc['criteria']:
        if c['importance_source']=='proposed':
            c['importance_proposal']=c['importance']
        if c['utility'] is not None or c['hard'] or c['importance'] <= 0:
            continue
        quotes = [c['source_quote'], *(q for b in c['source_evidence'] for q in b['quotes'])]
        text = ' '.join(quotes)
        if c['metric'] in DISTANCE_METRICS:
            # Do not complete a partly specified numeric request with silent defaults.
            if any(distance_values(q, c) for q in quotes):
                continue
            # Use the extracted single need, avoiding a combined clause's other facility.
            flexible = bool(re.search(r'멀어도|멀어져도|가까움보다|가까운 것보다', c['need']))
            very_close = not flexible and very_close_preference(c, quotes)
            label = ('조금 멀어도 괜찮아요' if flexible else
                     '집 바로 가까이에 있으면 좋아요' if very_close else '가까우면 좋아요')
            ideal, limit = (600.0, 2500.0) if flexible else (100.0, 800.0) if very_close else (300.0, 1500.0)
            rule = dict(direction='lower', ideal=ideal, limit=limit, unit='m')
            radius = None
        elif c['metric'] == COUNT_METRIC:
            if re.search(r'\d+(?:\.\d+)?\s*(?:개소|곳|개)', text):
                continue
            rule = dict(direction='higher', ideal=3.0, limit=0.0, unit='count')
            label = '학원 선택지가 다양하면 좋아요'
            radius = None
            if not c['parameters'].get('radius_m'):
                c['parameters']['radius_m'] = '1500'
                radius = 1500.0
        else:
            continue
        c['utility'] = rule
        c['comparison_proposal'] = dict(label=label, utility=rule, radius_m=radius)
        count += 1
    return NeedProfile.model_validate(doc), count
