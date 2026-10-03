"""Bounded Responses API adapter. Fixed HTTPS host, typed output, no credential logs."""
import http.client
import json
import math
import socket
import threading
import time

from pydantic import ValidationError

from .codex_runner import RunnerError
from .contracts import output_schema

MAX_BYTES = 4_000_000


def api_error(status, document):
    error = document.get('error', {}) if isinstance(document, dict) else {}
    code = error.get('code') if isinstance(error, dict) else None
    if status == 401:
        return 'authentication_required'
    if status == 403:
        return 'api_permission'
    if status == 429:
        return 'usage_limit'
    if status == 404 or code == 'model_not_found':
        return 'model_unavailable'
    if status == 400:
        return 'unsupported_configuration'
    return 'connection_error' if status >= 500 else 'execution_failed'


class OpenAIRunner:
    requires_explicit_need_fields = True

    def __init__(self, api_key, model, reasoning_effort='medium', timeout=120):
        if not api_key:
            raise RunnerError('api_key_missing')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('positive finite timeout required')
        self._api_key = api_key
        self.model, self.reasoning_effort, self.timeout = model, reasoning_effort, timeout
        self.last_metadata = {}
        self.on_debug_event = None

    def debug_event(self, role, content, **details):
        if self.on_debug_event:
            self.on_debug_event(role, content, **details)

    def request(self, method, path, payload=None, cancel=None):
        """No redirects/proxy override/custom host; cancellation closes the active socket."""
        cancel = cancel or threading.Event()
        if cancel.is_set():
            raise RunnerError('cancelled')
        finished = threading.Event()
        started = time.monotonic()
        connection = http.client.HTTPSConnection('api.openai.com', timeout=min(self.timeout, 10))
        sockets = []
        stop_code = []

        def monitor():
            while not finished.wait(.1):
                code = 'cancelled' if cancel.is_set() else 'timeout' if time.monotonic() - started >= self.timeout else None
                if code:
                    stop_code.append(code)
                    for sock in sockets:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    connection.close()
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            connection.connect()
            sockets.append(connection.sock)
            if stop_code or cancel.is_set():
                raise RunnerError(stop_code[0] if stop_code else 'cancelled')
            connection.sock.settimeout(self.timeout)
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8') if payload is not None else None
            connection.request(method, path, body, {'Authorization': 'Bearer ' + self._api_key,
                               'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            # Reject redirection without forwarding credentials or reading its location.
            if 300 <= response.status < 400:
                raise RunnerError('connection_error')
            raw = response.read(MAX_BYTES + 1)
            if stop_code or cancel.is_set():
                raise RunnerError(stop_code[0] if stop_code else 'cancelled')
            if len(raw) > MAX_BYTES:
                raise RunnerError('output_too_large')
            try:
                document = json.loads(raw)
            except (ValueError, UnicodeError):
                raise RunnerError('invalid_response') from None
            if response.status >= 400:
                # Provider messages can echo inputs/credentials; expose only mapped codes.
                raise RunnerError(api_error(response.status, document))
            if not isinstance(document, dict):
                raise RunnerError('invalid_response')
            return document
        except RunnerError:
            raise
        except (TimeoutError, socket.timeout):
            raise RunnerError(stop_code[0] if stop_code else 'timeout') from None
        except (OSError, http.client.HTTPException):
            raise RunnerError(stop_code[0] if stop_code else 'connection_error') from None
        finally:
            finished.set()
            connection.close()
            watcher.join(timeout=.3)

    def models(self):
        from .llm_settings import MODEL_PATTERN
        document = self.request('GET', '/v1/models')
        if not isinstance(document.get('data'), list):
            raise RunnerError('invalid_response')
        # Availability is not a promise of Responses/tools/reasoning support.
        return sorted({row['id'] for row in document['data'] if isinstance(row, dict)
                       and isinstance(row.get('id'), str) and MODEL_PATTERN.fullmatch(row['id'])})[:500]

    def run(self, prompt, response_type, *, cancel=None, search=False, domains=None, retries=0):
        if retries != 0:
            raise ValueError('API requests are not automatically retried')
        if domains and (not search or any(not d or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for ch in d) for d in domains)):
            raise ValueError('invalid search domain')
        started = time.monotonic()
        self.last_metadata = {'provider': 'openai', 'search_mode': 'live' if search else 'disabled',
                              'requested_model': self.model, 'requested_reasoning_effort': self.reasoning_effort,
                              'model_setting_source': 'explicit_api_argument', 'effort_setting_source': 'api_default' if self.reasoning_effort == 'auto' else 'explicit_api_argument',
                              'web_search_count': 0, 'usage': None}
        payload = {'model': self.model, 'input': prompt, 'store': False, 'max_output_tokens': 12000,
                   'text': {'format': {'type': 'json_schema', 'name': response_type.__name__,
                                       'strict': True, 'schema': output_schema(response_type)}}}
        if self.reasoning_effort != 'auto':
            payload['reasoning'] = {'effort': self.reasoning_effort}
        if search:
            tool = {'type': 'web_search'}
            if domains:
                tool['filters'] = {'allowed_domains': domains}
            payload.update(tools=[tool], tool_choice='required', include=['web_search_call.action.sources'])
        self.debug_event('AI 요청', prompt, response_type=response_type.__name__, search=search,
                         provider='openai', model=self.model, reasoning_effort=self.reasoning_effort)
        try:
            document = self.request('POST', '/v1/responses', payload, cancel)
            if document.get('status') == 'incomplete':
                raise RunnerError('incomplete_response')
            if document.get('status') != 'completed' or not isinstance(document.get('output'), list):
                raise RunnerError('invalid_response')
            texts = []
            for item in document['output']:
                if not isinstance(item, dict):
                    raise RunnerError('invalid_response')
                kind = item.get('type')
                if kind == 'web_search_call':
                    if not search:
                        raise RunnerError('unexpected_web_search')
                    if item.get('status') == 'completed':
                        self.last_metadata['web_search_count'] += 1
                elif kind == 'message':
                    if item.get('role') != 'assistant':
                        raise RunnerError('invalid_response')
                    content = item.get('content')
                    if not isinstance(content, list):
                        raise RunnerError('invalid_response')
                    for part in content:
                        if not isinstance(part, dict):
                            raise RunnerError('invalid_response')
                        if part.get('type') == 'refusal':
                            raise RunnerError('response_refused')
                        if part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                            texts.append(part['text'])
                        else:
                            raise RunnerError('invalid_response')
                elif kind != 'reasoning':
                    raise RunnerError('unexpected_tool_use')
            # Keep usage counters only, not arbitrary upstream metadata/auth material.
            usage = document.get('usage') or {}
            if not isinstance(usage, dict):
                raise RunnerError('invalid_response')
            self.last_metadata['usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')
                                          if isinstance(usage.get(k), int) and not isinstance(usage[k], bool)}
            raw = ''.join(texts)
            self.debug_event('AI 최종 응답', raw, response_type=response_type.__name__)
            try:
                result = response_type.model_validate_json(raw)
            except (ValidationError, ValueError):
                raise RunnerError('invalid_response') from None
            if cancel and cancel.is_set():
                raise RunnerError('cancelled')
            return result
        except RunnerError as error:
            self.last_metadata['error_code'] = error.code
            raise
        finally:
            self.last_metadata['elapsed_seconds'] = round(time.monotonic() - started, 3)
