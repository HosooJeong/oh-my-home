import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from app.contracts import Contract
from app.codex_runner import RunnerError
from app.openai_runner import OpenAIRunner, MAX_BYTES

KEY = 'sk-test-only-not-a-real-key'


class Tiny(Contract):
    answer: str


def response(text='{"answer":"확인"}', *extra):
    return {'status': 'completed', 'output': [*extra, {'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}],
            'usage': {'input_tokens': 12, 'output_tokens': 6, 'total_tokens': 18, 'secret': KEY}}


class APIAdapterTests(unittest.TestCase):
    def runner(self, document=None, effort='medium'):
        runner=OpenAIRunner(KEY,'gpt-6.1-sol',effort)
        self.call=None
        def request(method,path,payload=None,cancel=None):
            self.call=(method,path,payload)
            return document if document is not None else response()
        runner.request=request
        return runner

    def test_structured_request_and_no_credentials_in_metadata(self):
        r=self.runner();events=[];r.on_debug_event=lambda *a,**k:events.append((a,k))
        self.assertEqual(r.run('사용자 조건',Tiny).answer,'확인')
        method,path,payload=self.call
        self.assertEqual((method,path),('POST','/v1/responses'))
        self.assertFalse(payload['store']);self.assertNotIn('tools',payload)
        self.assertEqual(payload['reasoning'],{'effort':'medium'})
        self.assertEqual(payload['text']['format']['schema']['required'],['answer'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(r.last_metadata['usage']['total_tokens'],18)
        self.assertNotIn(KEY,json.dumps([payload, r.last_metadata, events],ensure_ascii=False))

    def test_auto_effort_omits_reasoning_and_search_is_bounded(self):
        r=self.runner(response('{"answer":"확인"}',{'type':'web_search_call','status':'completed'}),'auto')
        r.run('공개 시설 조사',Tiny,search=True,domains=['jinju.go.kr'])
        p=self.call[2]
        self.assertNotIn('reasoning',p)
        self.assertEqual(p['tools'],[{'type':'web_search','filters':{'allowed_domains':['jinju.go.kr']}}])
        self.assertEqual(p['tool_choice'],'required')
        self.assertEqual(r.last_metadata['web_search_count'],1)

    def test_search_disabled_and_non_web_tools_fail_closed(self):
        for item, code in [({'type':'web_search_call','status':'completed'},'unexpected_web_search'),
                           ({'type':'function_call','arguments':'secret'},'unexpected_tool_use')]:
            with self.subTest(code=code):
                r=self.runner(response('{"answer":"x"}',item))
                with self.assertRaisesRegex(RunnerError,code):r.run('test',Tiny)

    def test_refusal_incomplete_and_invalid_json_never_become_valid_answers(self):
        cases=[({'status':'incomplete','output':[]},'incomplete_response'),
               ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]},'response_refused'),
               (response('{"unknown":"x"}'),'invalid_response'),
               (response('not JSON'),'invalid_response')]
        for document,code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(RunnerError,code):self.runner(document).run('test',Tiny)

    def test_domains_and_implicit_retry_rejected_before_request(self):
        r=self.runner()
        with self.assertRaises(ValueError):r.run('x',Tiny,search=True,domains=['https://bad.invalid'])
        with self.assertRaises(ValueError):r.run('x',Tiny,retries=1)
        self.assertIsNone(self.call)

    def test_model_discovery_returns_only_bounded_valid_identifiers(self):
        r=self.runner({'data':[{'id':'gpt-6.1-sol'},{'id':'gpt-6.1-sol'}, {'id':'invalid\nheader'}, {'id':22}, None]})
        self.assertEqual(r.models(),['gpt-6.1-sol'])
        self.assertEqual(self.call[:2],('GET','/v1/models'))

    def test_pre_cancelled_request_makes_no_connection(self):
        cancel=threading.Event();cancel.set()
        with patch('app.openai_runner.http.client.HTTPSConnection') as factory:
            with self.assertRaisesRegex(RunnerError,'cancelled'):
                OpenAIRunner(KEY,'gpt-6.1-sol').request('POST','/v1/responses',{},cancel)
            factory.assert_not_called()


class FakeSocket:
    def __init__(self):self.closed=threading.Event()
    def settimeout(self,value):pass
    def shutdown(self,how):self.closed.set()


class FakeConnection:
    def __init__(self,status=200,document=None):
        self.sock=FakeSocket();self.status=status;self.document=document or response();self.calls=[];self.closed=False
    def connect(self):pass
    def request(self,method,path,body,headers):self.calls.append((method,path,body,headers))
    def getresponse(self):return self
    def read(self,limit):self.read_limit=limit;return json.dumps(self.document).encode()
    def close(self):self.closed=True


class HTTPBoundaryTests(unittest.TestCase):
    def test_only_official_https_endpoint_receives_authorization(self):
        conn=FakeConnection()
        with patch('app.openai_runner.http.client.HTTPSConnection',return_value=conn) as factory:
            OpenAIRunner(KEY,'gpt-6.1-sol').request('POST','/v1/responses',{'model':'gpt-6.1-sol'})
        self.assertEqual(factory.call_args.args,('api.openai.com',))
        self.assertEqual(conn.calls[0][3]['Authorization'],'Bearer '+KEY)
        self.assertEqual(conn.read_limit,MAX_BYTES+1);self.assertTrue(conn.closed)

    def test_auth_errors_never_echo_upstream_credentials(self):
        conn=FakeConnection(401,{'error':{'message':KEY}})
        with patch('app.openai_runner.http.client.HTTPSConnection',return_value=conn):
            with self.assertRaisesRegex(RunnerError,'authentication_required') as caught:
                OpenAIRunner(KEY,'gpt-6.1-sol').request('GET','/v1/models')
        self.assertNotIn(KEY,str(caught.exception));self.assertTrue(conn.closed)

    def test_redirect_is_rejected_without_second_request(self):
        conn=FakeConnection(302)
        with patch('app.openai_runner.http.client.HTTPSConnection',return_value=conn):
            with self.assertRaisesRegex(RunnerError,'connection_error'):
                OpenAIRunner(KEY,'gpt-6.1-sol').request('GET','/v1/models')
        self.assertEqual(len(conn.calls),1)

    def test_cancel_aborts_blocked_socket_and_does_not_return_answer(self):
        conn=FakeConnection();cancel=threading.Event()
        def read(limit):
            self.assertTrue(conn.sock.closed.wait(2))
            raise OSError('closed')
        conn.read=read
        timer=threading.Timer(.1,cancel.set);timer.start()
        try:
            with patch('app.openai_runner.http.client.HTTPSConnection',return_value=conn):
                with self.assertRaisesRegex(RunnerError,'cancelled'):
                    OpenAIRunner(KEY,'gpt-6.1-sol').request('GET','/v1/models',cancel=cancel)
        finally:timer.join()
        self.assertTrue(conn.closed)

    def test_total_deadline_aborts_response(self):
        conn=FakeConnection()
        def read(limit):
            conn.sock.closed.wait(2)
            raise OSError('closed')
        conn.read=read
        with patch('app.openai_runner.http.client.HTTPSConnection',return_value=conn):
            with self.assertRaisesRegex(RunnerError,'timeout'):
                OpenAIRunner(KEY,'gpt-6.1-sol',timeout=.1).request('GET','/v1/models')


if __name__=='__main__':unittest.main()
