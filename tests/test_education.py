from datetime import date, timedelta
from threading import Event
import time
import unittest
from unittest.mock import patch

from app.contracts import Criterion, UtilityRule, output_schema, NeedProfile
from app.education_preferences import EducationInput, education_profile
from app.evaluation import utility
from app.modules.education import EducationIndex, EducationModule, SCHOOL_SOURCE, ACADEMY_SOURCE
from app.orchestrator import Orchestrator
from app.research_policy import today, SourcePage, publication_dates, admissible
from app.web import AppState, CompareInput, PreferenceInput
from test_living import index, profile, candidates
from test_reviews import excerpt


def settings(**changes):
    return EducationInput(**(dict(profile=None, school_level='elementary', include_school=True,
        school_ideal=0.0, school_limit=1500.0, school_importance=70.0, include_academy=True,
        subject='math', radius_m=1000.0, sufficient_count=2.0, academy_importance=30.0,
        group_weight=30.0, travel_mode='alone', qualitative_research=False) | changes))


def facility(identity, kind='academy', **changes):
    row = dict(id=identity, kind=kind, name='가상학원' if kind == 'academy' else '가상학교',
        address='경상남도 진주시 가상로 1', source_url=ACADEMY_SOURCE if kind == 'academy' else SCHOOL_SOURCE,
        source_row=1, date=today().isoformat(), lat=35.18, lon=128.1, level='elementary',
        subjects=['math'], subject_levels={'math': ['elementary']}, coordinate_date=today().isoformat())
    return row | changes


def education(*rows):
    return EducationIndex(dict(retrieved_at=today().isoformat(), excluded={}, records=list(rows)))


class EducationTests(unittest.TestCase):
    def run_profile(self, rows, p=None):
        return Orchestrator({'education': EducationModule(education(*rows))}).run(
            p or education_profile(settings()), candidates())

    def test_grade_specific_school_and_subject_unique_counts(self):
        rows = [facility('school:a', 'school'), facility('school:b', 'school', level='middle', lon=128.11),
                facility('academy:a'), facility('academy:b', subjects=['english'], subject_levels={'english':['elementary']})]
        run = self.run_profile(rows)
        first = [e for e in run['modules'][0]['evidence'] if e['candidate_id'] == 'a']
        self.assertEqual([e['value'] for e in first], [0.0, 1.0])
        self.assertEqual(first[0]['source_record'], 'school:a')
        self.assertEqual(run['report']['ranking'][0], 'a')
        with self.assertRaises(ValueError): education(facility('academy:a'), facility('academy:a'))

    def test_counts_saturate_and_do_not_replace_class_size_or_safety(self):
        p = education_profile(settings(include_school=False))
        rule = p.criteria[0].utility
        self.assertEqual([utility(n, rule) for n in (0,1,2,5)], [0.0,.5,1.0,1.0])
        p.criteria.append(Criterion(**(p.criteria[0].model_dump() | dict(id='route', metric='safe_school_route',
            utility=UtilityRule(direction='boolean', ideal=1.0, limit=0.0, unit='bool'), parameters={}))))
        run = self.run_profile([facility('academy:a')], p)
        self.assertIn('route', run['modules'][0]['unsupported_criterion_ids'])
        self.assertIsNone(run['report']['assessments'][0]['score'])

    def test_unlocated_unknown_grade_and_stale_coordinates_withhold_count_score(self):
        for changes in [dict(lat=None,lon=None), dict(subject_levels={'math':[]}),
                        dict(coordinate_date=(today()-timedelta(days=366)).isoformat())]:
            run = self.run_profile([facility('school:a','school'), facility('academy:a'), facility('academy:b',**changes)])
            fact = next(e for e in run['modules'][0]['evidence'] if e['candidate_id']=='a' and e['unit']=='count')
            self.assertEqual(fact['value'], 1.0)
            self.assertEqual(fact['status'], 'missing')
            self.assertIsNone(run['report']['assessments'][0]['score'])

    def test_fresh_zero_differs_from_absent_snapshot_and_outside_scope(self):
        p = education_profile(settings(include_school=False))
        run = self.run_profile([facility('academy:a',lon=128.4)],p)
        self.assertEqual(run['modules'][0]['evidence'][0]['value'],0.0)
        self.assertEqual(run['modules'][0]['evidence'][0]['status'],'verified')
        run = self.run_profile([],p)
        self.assertIsNone(run['modules'][0]['evidence'][0]['value'])
        c = candidates()[0]; c.latitude=37.5
        result = education(facility('academy:a')).observe(p.criteria[0],c)
        self.assertIsNone(result['value'])
        for d in [(today()-timedelta(days=366)).isoformat(), (today()+timedelta(days=1)).isoformat()]:
            result=education(facility('school:a','school',date=d)).observe(education_profile(settings()).criteria[0],candidates()[0])
            self.assertEqual(result['status'],'missing'); self.assertIsNone(result['value'])

    def test_explicit_edit_preserves_other_needs_and_weights_without_automatic_hard(self):
        old=profile(); p=education_profile(settings(profile=old))
        self.assertEqual(p.criteria[:2],old.criteria)
        self.assertEqual(p.groups[0],old.groups[0])
        self.assertTrue(all(c.hard is None for c in p.criteria[2:]))
        changed=education_profile(settings(profile=p,school_level='middle',include_academy=False))
        self.assertEqual(changed.criteria[2].parameters,{'school_level':'middle'})
        self.assertEqual(changed.criteria[3].importance,0.0)
        self.assertEqual(changed.criteria[2].id,p.criteria[2].id)

    def test_strict_model_schema_keeps_scope_fields_and_drops_nulls(self):
        schema=output_schema(NeedProfile)
        params=schema['$defs']['MetricParameters']
        self.assertTrue({'school_level','school_id','subject','radius_m'} <= set(params['properties']))
        self.assertFalse(params['additionalProperties'])
        p=education_profile(settings())
        c=Criterion.model_validate(p.criteria[0].model_dump() | {'parameters':{'school_level':'elementary','subject':None}})
        self.assertEqual(c.parameters,{'school_level':'elementary'})
        c.utility.unit='min'
        p.criteria[0]=c
        run=self.run_profile([facility('school:a','school')],p)
        self.assertIn(c.id,run['modules'][0]['unsupported_criterion_ids'])

    def test_conditional_search_follows_facts_and_reweight_reuses_results(self):
        class Runner:
            last_metadata={'fixture':True}
        state=AppState(index(), Runner, education_index=education(facility('school:a','school'),facility('academy:a')))
        _,session=state.session()
        p=education_profile(settings())
        with patch('app.web.research_reviews',return_value={'items':[],'score_eligible':False}) as search:
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            self.assertNotIn('research_job',run); self.assertEqual(search.call_count,0)
            p=education_profile(settings(qualitative_research=True))
            run=state.compare(session,CompareInput(profile=p,candidates=candidates()))
            deadline=time.monotonic()+3
            while state.active_job and time.monotonic()<deadline: time.sleep(.01)
            self.assertIsNone(state.active_job)
            self.assertEqual(session['review_job']['status'],'completed')
            self.assertEqual(search.call_count,1)
            self.assertEqual([r['id'] for r in search.call_args.args[1]],['academy:a'])
            revised=state.preferences(session,PreferenceInput(run_id=run['run_id'],group_weights={},
                criterion_importance={p.criteria[0].id:40.0},confirm_weights=True))
            self.assertEqual(revised['run']['modules'],run['modules'])
            self.assertEqual(search.call_count,1)


class ResearchPolicyTests(unittest.TestCase):
    def test_publication_date_not_modified_date_and_conflicting_dates_withheld(self):
        html='<script type="application/ld+json">{"@type":"BlogPosting","datePublished":"2018-01-01","dateModified":"2026-01-01"}</script>'
        self.assertEqual(publication_dates(html),('2018-01-01',))
        page=SourcePage('가상학원 가상로 1 작지만 품목은 다양했어요.',('2026-01-01','2026-02-01'))
        self.assertEqual(admissible(excerpt(),page,facility('academy:a')),'publication_unverified')

    def test_name_address_quote_date_and_promotional_checks(self):
        f=facility('academy:a'); q=excerpt()
        text='가상학원 가상로 1 작지만 품목은 다양했어요.'
        page=lambda value:SourcePage(value,('2026-01-01',))
        self.assertIsNone(admissible(q,page(text),f))
        for value,reason in [(text.replace('가상학원','다른학원'),'identity_unverified'),
                             (text.replace('가상로 1','다른로 2'),'address_unverified'),
                             (text+' 체험단','promotional_source')]:
            self.assertEqual(admissible(q,page(value),f),reason)
        self.assertEqual(admissible(excerpt(published_date='2026-02-01'),page(text),f),'publication_unverified')

    def test_unknown_old_future_and_invented_quotes_never_enter_pipeline(self):
        f=facility('academy:a'); page=SourcePage('가상학원 가상로 1 실제 문장',('2026-01-01',))
        for value,reason in [(None,'date_unknown'),('2018-01-01','outdated_or_future'),('2099-01-01','outdated_or_future')]:
            self.assertEqual(admissible(excerpt(published_date=value),page,f),reason)
        self.assertEqual(admissible(excerpt(),page,f),'quote_unverified')
