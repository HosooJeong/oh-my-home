import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.__main__ import main
from app.llm_settings import ModelSettings


KEY='sk-test-only-not-a-real-key'


class CLISettingsTests(unittest.TestCase):
    def invoke(self, options, key=KEY):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);env=root/'.env';request=root/'request.txt';output=root/'profile.json'
            env.write_text('OPENAI_API_KEY='+key+'\n',encoding='utf-8')
            request.write_text('초등학생 자녀와 진주에서 생활할 집을 비교하고 싶어.',encoding='utf-8')
            args=['app','intake','--env-file',str(env),'--request-file',str(request),
                  '--output',str(output),*options]
            seen=[]
            def runner(settings,**kwargs):
                seen.append((settings,kwargs))
                return SimpleNamespace(last_metadata={'provider':settings.provider})
            with patch('sys.argv',args),patch.dict('os.environ',{},clear=True),\
                 patch.object(ModelSettings,'runner',runner),\
                 patch('app.__main__.prepare_profile',return_value=SimpleNamespace(model_dump=lambda:{'fixture':True})),\
                 contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=main()
            content=json.loads(output.read_text(encoding='utf-8')) if output.exists() else None
            return result,seen,content

    def test_cli_defaults_to_api_and_reads_key_from_env_file(self):
        result,seen,content=self.invoke([])
        self.assertEqual((result,content),(0,{'fixture':True}))
        self.assertEqual(seen[0][0].provider,'openai')
        self.assertEqual(seen[0][0].api_key,KEY)
        self.assertEqual(seen[0][1],{'timeout':120,'codex':None})

    def test_cli_explicit_codex_and_timeout_override_defaults(self):
        result,seen,_=self.invoke(['--provider','codex','--model','gpt-6-sol',
                                  '--reasoning-effort','high','--timeout','30'])
        self.assertEqual(result,0)
        self.assertEqual((seen[0][0].provider,seen[0][0].model,seen[0][0].effort),
                         ('codex','gpt-6-sol','high'))
        self.assertEqual(seen[0][1]['timeout'],30)

    def test_missing_key_cli_fails_without_network_or_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);request=root/'request.txt';output=root/'profile.json'
            request.write_text('생활 조건',encoding='utf-8')
            args=['app','intake','--env-file',str(root/'missing.env'),
                  '--request-file',str(request),'--output',str(output)]
            errors=io.StringIO()
            with patch('sys.argv',args),patch.dict('os.environ',{},clear=True),\
                 patch('app.openai_runner.http.client.HTTPSConnection') as network,\
                 patch('app.llm_settings.CodexRunner') as codex,contextlib.redirect_stderr(errors):
                self.assertEqual(main(),1)
            self.assertEqual(json.loads(errors.getvalue())['error_code'],'api_key_missing')
            self.assertFalse(output.exists());network.assert_not_called();codex.assert_not_called()

    def test_api_timeout_and_invalid_codex_hint_do_not_change_provider(self):
        from app.openai_runner import OpenAIRunner
        settings=ModelSettings(api_key=KEY)
        api=settings.runner(timeout=30)
        self.assertIsInstance(api,OpenAIRunner);self.assertEqual(api.timeout,30)
        from app.codex_runner import RunnerError
        with self.assertRaisesRegex(RunnerError,'unsupported_configuration'):
            settings.runner(codex='unexpected.exe')


if __name__=='__main__':unittest.main()
