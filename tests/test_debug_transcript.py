import json
from pathlib import Path
import tempfile
import time
import unittest

from app.codex_runner import RunnerError
from app.debug_transcript import DebugTranscripts, safe_content
from app.modules.living import ShopIndex
from app.web import AppState, IntakeInput
from test_codex_runner import Harness, FAKE, Tiny


class DebugTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_utf8_session_file_masks_nested_and_inline_credentials(self):
        store = DebugTranscripts(self.directory)
        path = store.start()
        store.append(path, '사용자 답변', {'answer':'큰 마트가 좋아', 'token':'SESSION_SECRET',
                     'child':{'api_key':'API_SECRET'}, 'text':'{"javascriptKey":"KEY_SECRET", "refresh_token":"REFRESH_SECRET"} Bearer BEARER_SECRET'})
        content = path.read_text(encoding='utf-8')
        self.assertIn('큰 마트가 좋아', content)
        for value in ('SESSION_SECRET','API_SECRET','KEY_SECRET','REFRESH_SECRET','BEARER_SECRET'):
            self.assertNotIn(value,content)

    def test_invalid_ai_final_is_recorded_before_rejection_without_reasoning(self):
        script = self.directory / 'fake.py'; script.write_text(FAKE,encoding='utf-8')
        runner = Harness(script,'invalid')
        store = DebugTranscripts(self.directory / 'logs');path=store.start()
        runner.on_debug_event=lambda role,content,**details:store.append(path,role,content,**details)
        with self.assertRaisesRegex(RunnerError,'invalid_response'):runner.run('검증용 사용자 입력',Tiny)
        content=path.read_text(encoding='utf-8')
        self.assertIn('검증용 사용자 입력',content);self.assertIn('"surprise": true',content)
        self.assertNotIn('PRIVATE_NOT_TO_PERSIST',content)

    def test_failed_job_keeps_error_elapsed_and_validation_location(self):
        class FailedRunner:
            def __init__(self):self.last_metadata={'elapsed_seconds':1.2,'validation_errors':[{'location':['criteria',0],'type':'value_error'}]}
        state=AppState(ShopIndex({'generated_at':'fixture','records':[]}),runner_factory=FailedRunner,debug_transcripts=DebugTranscripts(self.directory))
        token,session=state.session()
        def fail(runner,cancel):
            runner.on_debug_event('AI 최종 응답', '{"answer":null}')
            raise RunnerError('invalid_response')
        data=IntakeInput(request_id='debug_fixture',request='테스트 입력')
        state.start_job(session,data,'intake',fail)
        deadline=time.monotonic()+3
        while '작업 종료' not in session['debug_path'].read_text(encoding='utf-8') and time.monotonic()<deadline:time.sleep(.01)
        content=session['debug_path'].read_text(encoding='utf-8')
        self.assertIn('invalid_response',content);self.assertIn('elapsed_seconds',content);self.assertIn('validation_errors',content)
        self.assertNotIn(token,content);self.assertEqual(session['jobs']['debug_fixture']['status'],'failed')

    def test_default_session_has_no_file_and_reasoning_events_are_ignored(self):
        state=AppState(ShopIndex({'generated_at':'fixture','records':[]}))
        _,session=state.session();self.assertIsNone(session['debug_path'])
        script=self.directory/'fake.py';script.write_text(FAKE,encoding='utf-8');runner=Harness(script)
        events=[];runner.on_debug_event=lambda *args,**kw:events.append(args)
        runner.debug_cli_events(json.dumps({'type':'item.completed','item':{'type':'reasoning','text':'HIDDEN'}}).encode(),True)
        self.assertEqual(events,[])


if __name__=='__main__':unittest.main()
