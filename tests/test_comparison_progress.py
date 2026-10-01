import unittest
from app.orchestrator import Orchestrator
from app.web import AppState, CompareInput
from test_agent_core import FixtureModule, profile, candidates
from test_living import index


class ComparisonProgressTests(unittest.TestCase):
    def test_start_is_observable_while_module_is_running(self):
        observed=[]
        class Watched(FixtureModule):
            def run(self,request,cancel):
                self.assert_started=observed[-1]=={'stage':'module_started','module_id':self.id}
                return super().run(request,cancel)
        module=Watched('transport')
        run=Orchestrator({'transport':module}).run(profile(100,0),candidates(),on_event=observed.append)
        self.assertTrue(module.assert_started)
        self.assertEqual(observed,run['events'])
        self.assertEqual([e['stage'] for e in observed],['planned','module_started','module_finished','evaluated'])

    def test_session_progress_contains_only_the_current_actual_run(self):
        app=AppState(index());_,session=app.session()
        app.orchestrator=Orchestrator({'transport':FixtureModule('transport')})
        for id in ('first','second'):
            result=app.compare(session,CompareInput(profile=profile(100,0),candidates=candidates(),progress_id=id))
            progress=session['comparison_progress']
            self.assertEqual(progress['id'],id)
            self.assertEqual(progress['events'],result['events'])
            self.assertFalse(any('candidates' in e or 'profile' in e for e in progress['events']))


if __name__=='__main__':unittest.main()
