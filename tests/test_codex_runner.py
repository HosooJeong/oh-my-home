import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.codex_runner import CodexRunner, RunnerError, classify_error, discover_executable
from app.contracts import Contract, InterviewTurn
from app.intake import prepare_profile
from app.preferences import reevaluate_preferences, update_preferences
from test_agent_core import profile, candidates, evidence, FixtureModule
from app.orchestrator import Orchestrator


class Tiny(Contract):
    answer: str


FAKE = '''import json, pathlib, subprocess, sys, time
mode,out,marker=sys.argv[1:]
prompt=sys.stdin.buffer.read()
if mode in ('sleep','child'):
    if mode == 'child':
        code="import pathlib,sys,time;time.sleep(1.5);pathlib.Path(sys.argv[1]).write_text('orphan')"
        subprocess.Popen([sys.executable,'-c',code,marker])
    time.sleep(30)
if mode == 'auth':
    print('401 authentication required',file=sys.stderr);sys.exit(1)
if mode == 'quota':
    print('429 usage limit',file=sys.stderr);sys.exit(1)
if mode == 'tool':
    print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'private'}}))
if mode == 'web':
    print(json.dumps({'type':'item.completed','item':{'type':'web_search'}}))
print(json.dumps({'type':'item.completed','item':{'type':'reasoning','text':'PRIVATE_NOT_TO_PERSIST'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':2}}))
data={'answer':'ok'} if mode != 'invalid' else {'answer':3,'surprise':True}
pathlib.Path(out).write_text(json.dumps(data),encoding='utf-8')
'''


class Harness(CodexRunner):
    def __init__(self, script, mode="ok", timeout=5, marker=None):
        super().__init__(sys.executable, timeout=timeout)
        self.script, self.mode = script, mode
        self.marker = marker or script.with_name("orphan.txt")

    def command(self, directory, schema_file, output_file, search=False, domains=None):
        self.last_directory = directory
        return [sys.executable, str(self.script), self.mode, str(output_file), str(self.marker)]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.script = Path(self.temp.name) / "fake.py"
        self.script.write_text(FAKE, encoding="utf-8")

    def test_structured_result_and_private_event_filter(self):
        runner = Harness(self.script)
        result = runner.run('input with quotes; $() and ` remain stdin', Tiny)
        self.assertEqual(result.answer, "ok")
        self.assertEqual(runner.last_metadata["usage"]["input_tokens"], 1)
        self.assertEqual(runner.last_metadata["requested_model"], "gpt-6.1-sol")
        self.assertEqual(runner.last_metadata["requested_reasoning_effort"], "medium")
        self.assertNotIn("PRIVATE", json.dumps(runner.last_metadata))
        self.assertFalse(runner.last_directory.exists())

    def test_invalid_final_json_fails_after_schema_request(self):
        with self.assertRaisesRegex(RunnerError, "invalid_response"):
            Harness(self.script, "invalid").run("test", Tiny)

    def test_auth_and_quota_classified_without_raw_message(self):
        for mode, code in [("auth", "authentication_required"), ("quota", "usage_limit")]:
            with self.subTest(mode=mode), self.assertRaisesRegex(RunnerError, code):
                Harness(self.script, mode).run("test", Tiny)

    def test_timeout_terminates_child_tree(self):
        marker = Path(self.temp.name) / "orphan.txt"
        runner = Harness(self.script, "child", timeout=.5, marker=marker)
        with self.assertRaisesRegex(RunnerError, "timeout"):
            runner.run("test", Tiny)
        time.sleep(1.7)
        self.assertFalse(marker.exists(), "child survived timeout")

    def test_cancellation_interrupts_running_process(self):
        cancel = threading.Event()
        timer = threading.Timer(.3, cancel.set)
        timer.start()
        try:
            with self.assertRaisesRegex(RunnerError, "cancelled"):
                Harness(self.script, "sleep").run("test", Tiny, cancel=cancel)
        finally:
            timer.cancel()

    def test_concurrent_call_is_rejected_as_busy(self):
        CodexRunner._slot.acquire()
        try:
            with self.assertRaisesRegex(RunnerError, "busy"):
                Harness(self.script).run("test", Tiny)
        finally:
            CodexRunner._slot.release()

    def test_unexpected_tools_or_search_are_rejected(self):
        for mode, code in [("tool", "unexpected_tool_use"), ("web", "unexpected_web_search")]:
            with self.subTest(mode=mode), self.assertRaisesRegex(RunnerError, code):
                Harness(self.script, mode).run("test", Tiny)
        runner = Harness(self.script, "web")
        runner.run("test", Tiny, search=True)
        self.assertEqual(runner.last_metadata["web_search_count"], 1)

    def test_configuration_uses_arguments_and_no_api_key_environment(self):
        runner = CodexRunner(sys.executable)
        args = runner.command(Path("work"), Path("schema.json"), Path("out.json"))
        self.assertIn('--ignore-user-config', args)
        self.assertIn('web_search="disabled"', args)
        self.assertIn('features.shell_tool=false', args)
        self.assertEqual(args[args.index('--model') + 1], 'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort="medium"', args)
        with patch.dict('os.environ', {'OPENAI_API_KEY':'private','CODEX_THREAD_ID':'private'}):
            self.assertNotIn('OPENAI_API_KEY', runner.environment())
            self.assertNotIn('CODEX_THREAD_ID', runner.environment())
        with self.assertRaises(ValueError):
            runner.command(Path("work"), Path("schema"), Path("out"), True, ["site.com;bad"])

    def test_explicit_model_effort_override_and_invalid_effort(self):
        runner = CodexRunner(sys.executable, model='gpt-6-sol', reasoning_effort='high')
        args = runner.command(Path('work'), Path('schema'), Path('out'))
        self.assertEqual(args[args.index('--model') + 1], 'gpt-6-sol')
        self.assertIn('model_reasoning_effort="high"', args)
        self.assertEqual(CodexRunner(sys.executable, model=None).model, 'gpt-6.1-sol')
        with self.assertRaisesRegex(ValueError, 'unsupported reasoning effort'):
            CodexRunner(sys.executable, reasoning_effort='unknown')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows runtime selection')
    def test_newest_installed_cli_selected_instead_of_stale_npm_shim(self):
        desktop = 'C:/codex-desktop/codex.exe'
        npm = Path('C:/npm/codex-native/codex.exe')
        paths = {'codex.exe':desktop, 'codex.cmd':'C:/npm/codex.cmd'}
        self.addCleanup(discover_executable.cache_clear)
        for desktop_version, expected in [('0.159.2',desktop),('0.140.0',str(npm))]:
            discover_executable.cache_clear()
            def version(args, **_kwargs):
                value = desktop_version if args[0] == desktop else '0.155.1'
                return subprocess.CompletedProcess(args,0,('codex-cli '+value).encode(),b'')
            with self.subTest(desktop_version=desktop_version), \
                    patch('app.codex_runner.shutil.which',side_effect=paths.get), \
                    patch('app.codex_runner.Path.glob',return_value=[npm]), \
                    patch('app.codex_runner.subprocess.run',side_effect=version):
                self.assertEqual(discover_executable(),expected)


class PreferencesAndIntakeTests(unittest.TestCase):
    def test_weight_edit_reuses_facts_and_keeps_previous_revision(self):
        previous = profile()
        revised = update_preferences(previous, {"transport":30.0,"housing":70.0})
        self.assertEqual(previous.revision, 1)
        self.assertEqual(previous.groups[0].weight, 70)
        self.assertEqual(revised.revision, 2)
        run = Orchestrator({id: FixtureModule(id) for id in ("transport", "housing")}).run(previous, candidates())
        result = reevaluate_preferences(previous, revised, candidates(), run)
        self.assertEqual(result["ranking"], ["b", "a"])

    def test_changed_query_cannot_silently_reuse_old_facts(self):
        p = profile()
        revised = update_preferences(p, {"transport":30.0})
        revised.criteria[0].utility.unit = "minutes"
        with self.assertRaises(ValueError):
            reevaluate_preferences(p, revised, candidates(), {})

    def test_moved_candidate_cannot_reuse_previous_geographic_facts(self):
        p = profile()
        run = Orchestrator({id: FixtureModule(id) for id in ("transport", "housing")}).run(p, candidates())
        moved = candidates()
        moved[0].latitude = 35.3
        with self.assertRaises(ValueError):
            reevaluate_preferences(p, update_preferences(p), moved, run)

    def test_unknown_weight_target_rejected(self):
        with self.assertRaises(ValueError):
            update_preferences(profile(), {"unknown":20.0})
        with self.assertRaises(ValueError):
            update_preferences(profile(), confirm_weights="false")

    def test_bad_model_identity_or_invented_quote_rejected(self):
        class Fake:
            def run(self, *_args, **_kwargs):
                return profile()
        with self.assertRaisesRegex(RunnerError, "invalid_intake_identity"):
            prepare_profile(Fake(), "different request")
        p = profile()
        p.criteria[0].source_quote = "not present in request"
        class BadQuote:
            def run(self, *_args, **_kwargs):
                return p
        with self.assertRaisesRegex(RunnerError, "unsupported_source_quote"):
            prepare_profile(BadQuote(), p.request)

    def test_interview_without_previous_or_with_unknown_question_rejected(self):
        answer = InterviewTurn(question_id="unknown", answer="가상 답변")
        with self.assertRaises(ValueError):
            prepare_profile(None, "request", [answer])
        p = profile()
        with self.assertRaises(ValueError):
            prepare_profile(None, p.request, [answer], p)

    def test_interview_cannot_silently_drop_an_existing_need(self):
        p = profile()
        data = p.model_dump()
        data['revision'] = 2
        data['groups'] = data['groups'][:1]
        data['criteria'] = data['criteria'][:1]
        class Dropped:
            def run(self, *_args, **_kwargs):
                return type(p).model_validate(data)
        with self.assertRaisesRegex(RunnerError, 'lost_existing_criterion'):
            prepare_profile(Dropped(), p.request, previous=p)


if __name__ == "__main__":
    unittest.main()
