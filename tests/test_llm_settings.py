from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.codex_runner import RunnerError
from app.llm_settings import ModelSettings, server_settings
from app.web import AppState, IntakeInput, make_handler
from test_living import index

KEY='sk-test-only-not-a-real-key'


class SettingsTests(unittest.TestCase):
    def test_default_api_has_no_implicit_codex_fallback_without_a_key(self):
        settings=ModelSettings()
        self.assertEqual(settings.public(), {'provider':'openai','model':'gpt-6.1-sol',
            'effort':'medium','key_configured':False,'ready':False})
        with patch('app.openai_runner.http.client.HTTPSConnection') as network:
            with patch('app.llm_settings.CodexRunner') as codex:
                with self.assertRaisesRegex(RunnerError,'api_key_missing'):
                    settings.runner(codex)
                codex.assert_not_called();network.assert_not_called()

    def test_server_template_preserves_process_key_and_explicit_codex_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('SALJARI_LLM_PROVIDER=openai\nOPENAI_API_KEY=\n',encoding='utf-8')
            with patch.dict('os.environ',{'OPENAI_API_KEY':KEY},clear=True):
                settings=server_settings(path)
                self.assertTrue(settings.public()['ready'])
                self.assertEqual(settings.api_key,KEY)
                self.assertNotIn(KEY,json.dumps(settings.public()))
            path.write_text('SALJARI_LLM_PROVIDER=codex\n',encoding='utf-8')
            with patch.dict('os.environ',{},clear=True):
                self.assertEqual(server_settings(path).provider,'codex')
            with patch.dict('os.environ',{'SALJARI_LLM_PROVIDER':'openai'},clear=True):
                self.assertEqual(server_settings(path).provider,'openai')

    def test_default_intake_job_uses_api_and_validates_structured_response(self):
        from app.contracts import Contract
        class Tiny(Contract):answer:str
        app=AppState(index(),llm_settings=ModelSettings(api_key=KEY));_,session=app.session()
        response={'status':'completed','output':[{'type':'message','role':'assistant',
            'content':[{'type':'output_text','text':'{"answer":"확인"}'}]}]}
        with patch('app.openai_runner.OpenAIRunner.request',return_value=response) as request:
            with patch.object(app,'runner_factory') as codex:
                job=app.start_job(session,IntakeInput(request_id='api_default',request='조건'),
                    'intake',lambda runner,cancel:runner.run('조건',Tiny,cancel=cancel).model_dump())
                for _ in range(100):
                    if session['jobs'][job['id']]['status']!='running':break
                    time.sleep(.01)
                actual=session['jobs'][job['id']]
                self.assertEqual(actual['status'],'completed')
                self.assertEqual(actual['profile'],{'answer':'확인'})
                self.assertEqual(actual['metadata']['provider'],'openai')
                self.assertEqual(request.call_args.args[:2],('POST','/v1/responses'))
                codex.assert_not_called()
                self.assertNotIn(KEY,json.dumps(app.public_job(actual)))

    def test_key_is_neither_public_nor_in_repr_and_deletion_is_explicit(self):
        a=ModelSettings().updated({'provider':'openai','api_key':KEY})
        self.assertTrue(a.public()['ready'])
        self.assertNotIn(KEY,json.dumps(a.public()));self.assertNotIn(KEY,repr(a))
        self.assertEqual(a.updated({'api_key':''}).api_key,KEY)
        b=a.updated({'remove_key':True})
        self.assertFalse(b.public()['ready']);self.assertEqual(a.api_key,KEY)

    def test_no_custom_destination_or_header_injection(self):
        for data in [{'base_url':'https://untrusted.invalid'}, {'api_key':KEY+'\n'},
                     {'model':'x\nheader'}, {'effort':'ultra','provider':'openai'},
                     {'provider':'openai','model':'gpt-6.1-sol','effort':'none'},
                     {'remove_key':'true'}]:
            with self.subTest(data=data):
                with self.assertRaises(RunnerError):ModelSettings().updated(data)

    def test_selection_is_session_local_and_running_job_retains_snapshot(self):
        app=AppState(index());_,a=app.session();_,b=app.session()
        app.model_settings(a,{'provider':'openai','api_key':KEY,'model':'custom-api-model','effort':'auto'})
        self.assertEqual(app.model_settings(b)['provider'],'openai')
        begun=threading.Event();release=threading.Event();seen=[]
        class Runner:
            last_metadata={'provider':'openai','requested_model':'custom-api-model'}
        def make(settings,factory):seen.append(settings);return Runner()
        def execute(runner,cancel):begun.set();release.wait(2);return {'fixture':True}
        with patch.object(ModelSettings,'runner',make):
            job=app.start_job(a,IntakeInput(request_id='test_job',request='fixture'),'intake',execute)
            self.assertTrue(begun.wait(1))
            with self.assertRaisesRegex(RunnerError,'busy'):app.model_settings(a,{'provider':'codex'})
            app.model_settings(b,{'model':'different-model'})
            release.set()
            for _ in range(100):
                if a['jobs'][job['id']]['status']!='running':break
                time.sleep(.01)
        self.assertEqual(seen[0].model,'custom-api-model')
        self.assertEqual(a['jobs'][job['id']]['status'],'completed')
        self.assertNotIn(KEY,json.dumps(app.public_job(a['jobs'][job['id']])))

    def test_intake_and_supplement_use_selected_runner_factory(self):
        # Every job type shares start_job, including the separate response review call.
        app=AppState(index());_,session=app.session()
        app.model_settings(session,{'provider':'openai','api_key':KEY})
        seen=[]
        class R:last_metadata={'provider':'openai'}
        def make(settings,factory):seen.append(settings.provider);return R()
        for kind in ('intake','reviews','supplement'):
            session['review_key']='run'
            with patch.object(ModelSettings,'runner',make):
                job=app.start_job(session,IntakeInput(request_id='job_'+kind,request='fixture'),kind,
                                  lambda runner,cancel:{'fixture':True},review_key='run')
                for _ in range(100):
                    if session['jobs'][job['id']]['status']!='running':break
                    time.sleep(.01)
            self.assertEqual(session['jobs'][job['id']]['status'],'completed')
        self.assertEqual(seen,['openai','openai','openai'])

    def test_api_intake_keeps_fresh_source_role_contract(self):
        from app.intake import IntakeDraft, prepare_profile
        draft=IntakeDraft.model_validate(dict(groups=[dict(id='housing',weight=0.0,source='user')],
            criteria=[],context=[dict(key='housing_reference',value='requested',source_id='s1')],
            questions=[],needs=[dict(source_id='s1',group_id='housing',aspect='housing',handling='reference',
                criterion_ids=[],context_keys=['housing_reference'],resolution_source_id=None)]))
        from app.openai_runner import OpenAIRunner
        runner=OpenAIRunner(KEY,'gpt-6.1-sol')
        runner.run=lambda *args,**kwargs:draft
        with self.assertRaisesRegex(RunnerError,'invalid_intake_contract'):
            prepare_profile(runner,'실거래 참고만')


class SettingsHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state=AppState(index())
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.state,Path('missing.env')))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def request(self,path,data=None,token='',origin=None):
        headers={'X-Session':token,'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        req=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urlopen(req,timeout=5) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)

    def test_configuration_roundtrip_keeps_key_out_of_bootstrap_and_other_session(self):
        _,first=self.request('/api/bootstrap');_,second=self.request('/api/bootstrap')
        token=first['token']
        code,data=self.request('/api/llm/settings',{'provider':'openai','api_key':KEY},token)
        self.assertEqual(code,200);self.assertTrue(data['key_configured'])
        _,boot=self.request('/api/bootstrap',token=token)
        self.assertEqual(boot['llm']['provider'],'openai');self.assertNotIn(KEY,json.dumps(boot))
        _,other=self.request('/api/llm/settings',token=second['token'])
        self.assertFalse(other['key_configured']);self.assertEqual(other['provider'],'openai')
        _,deleted=self.request('/api/llm/settings',{'remove_key':True},token)
        self.assertFalse(deleted['ready'])

    def test_settings_require_session_and_same_origin(self):
        code,_=self.request('/api/llm/settings',{'api_key':KEY})
        self.assertEqual(code,403)

    def test_key_settings_endpoint_is_excluded_from_transcripts(self):
        _,boot=self.request('/api/bootstrap')
        with patch.object(self.state,'record') as record:
            code,body=self.request('/api/llm/settings',{'provider':'openai','api_key':KEY},boot['token'])
            self.assertEqual(code,200)
            self.assertNotIn(KEY,json.dumps(body))
            record.assert_not_called()

    def test_model_list_uses_this_sessions_key_without_echoing_it(self):
        _,boot=self.request('/api/bootstrap')
        self.request('/api/llm/settings',{'provider':'openai','api_key':KEY},boot['token'])
        with patch('app.openai_runner.OpenAIRunner.models',return_value=['gpt-6.1-sol']):
            code,body=self.request('/api/llm/models',{},boot['token'])
        self.assertEqual((code,body),(200,{'models':['gpt-6.1-sol']}))
        self.assertNotIn(KEY,json.dumps(body))
        _,boot=self.request('/api/bootstrap')
        code,_=self.request('/api/llm/settings',{'api_key':KEY},boot['token'],'https://foreign.invalid')
        self.assertEqual(code,403)


if __name__=='__main__':unittest.main()
