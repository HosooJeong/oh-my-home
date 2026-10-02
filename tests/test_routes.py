import io
import json
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import unittest
from urllib.error import HTTPError, URLError
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from app.routes import KakaoRoutes, RouteError, RouteInput, MAX_BYTES, NoRedirect, read_rest_key
from app.web import AppState, make_handler
from test_living import index


def request(mode='walk', **changes):
    return RouteInput.model_validate({'start': {'latitude': 35.18, 'longitude': 128.11},
                                     'end': {'latitude': 35.15, 'longitude': 128.12},
                                     'mode': mode, **changes})


def route(distance=500, duration=480, transfers=0):
    step = {'properties': {'type': 'WALKING'}, 'path': {'points': [[128.11, 35.18], [128.12, 35.15]]}}
    return {'properties': {'totalDistance': distance, 'totalTime': duration, 'transfers': transfers},
            'legs': [{'steps': [step]}], 'steps': [step]}


def document(mode='walk'):
    return {'status': 'OK', **({'route': route()} if mode == 'walk' else {'routes': [route(duration=900), route(duration=600, transfers=1)]})}


class RouteTests(unittest.TestCase):
    def test_env_uses_rest_key_only_and_rejects_malformed_values(self):
        path = Mock()
        path.read_text.return_value = 'KAKAO_MAP_JAVASCRIPT_KEY=' + 'b' * 32 + '\nKAKAO_MAP_REST_API_KEY=' + 'a' * 32
        self.assertEqual(read_rest_key(path), 'a' * 32)
        path.read_text.assert_called_with(encoding='utf-8-sig')
        path.read_text.return_value = 'KAKAO_MAP_REST_API_KEY=not-a-key'
        with self.assertRaises(RouteError) as raised:
            read_rest_key(path)
        self.assertEqual(raised.exception.code, 'route_key_invalid')

    def client(self, body=None, failure=None):
        opener = MagicMock()
        if failure:
            opener.open.side_effect = failure
        else:
            response = Mock()
            response.read.return_value = json.dumps(document() if body is None else body).encode()
            opener.open.return_value.__enter__.return_value = response
        return KakaoRoutes(Path('missing-env'), opener), opener

    @patch('app.routes.read_rest_key', return_value='a' * 32)
    def test_walk_auth_coordinates_options_and_display_boundary(self, _):
        client, opener = self.client()
        result = client.query(request(walk_option='ACCESSIBLE'))
        call = opener.open.call_args
        sent = call.args[0]
        self.assertIn('/v2/routing/walk?', sent.full_url)
        self.assertIn('start_x=128.11000000', sent.full_url)
        self.assertIn('start_y=35.18000000', sent.full_url)
        self.assertIn('route_mode=ACCESSIBLE', sent.full_url)
        self.assertEqual(sent.get_header('Authorization'), 'KakaoAK ' + 'a' * 32)
        self.assertNotIn('a' * 32, sent.full_url)
        self.assertEqual(call.kwargs['timeout'], 8)
        self.assertEqual(result['routes'][0]['distance_m'], 500)
        self.assertEqual(result['routes'][0]['duration_s'], 480)
        self.assertIsNone(result['routes'][0]['transfers'])
        self.assertFalse(result['llm_transfer'])
        self.assertNotIn('a' * 32, json.dumps(result))

    @patch('app.routes.read_rest_key', return_value='a' * 32)
    def test_transit_uses_separate_endpoint_and_preserves_transfers(self, _):
        client, opener = self.client(document('transit'))
        result = client.query(request('transit'))
        self.assertIn('/v2/routing/publictraffic?', opener.open.call_args.args[0].full_url)
        self.assertNotIn('route_mode', opener.open.call_args.args[0].full_url)
        self.assertEqual([r['duration_s'] for r in result['routes']], [600, 900])
        self.assertEqual(result['routes'][0]['transfers'], 1)

    @patch('app.routes.read_rest_key', return_value='a' * 32)
    def test_missing_routes_bad_numbers_and_invalid_geometry_do_not_become_scores(self, _):
        for body, code in [({'status': 'NO_RESULTS'}, 'route_not_found'),
                           ({'status': 'OK', 'route': route(distance=-1)}, 'route_bad_response'),
                           ({'status': 'OK', 'route': route(duration=float('nan'))}, 'route_bad_response'),
                           ({'status': 'OK', 'route': route(distance=True)}, 'route_bad_response')]:
            with self.subTest(code=code):
                client, _ = self.client(body)
                with self.assertRaises(RouteError) as raised:
                    client.query(request())
                self.assertEqual(raised.exception.code, code)
        body = document()
        body['route']['legs'][0]['steps'][0]['path']['points'] = [[35.18, 128.11]]
        client, _ = self.client(body)
        with self.assertRaises(RouteError) as raised:
            client.query(request())
        self.assertEqual(raised.exception.code, 'route_bad_response')

    @patch('app.routes.read_rest_key', return_value='a' * 32)
    def test_auth_permission_quota_timeout_and_network_are_distinct_and_redacted(self, _):
        for failure, code in [(HTTPError('https://secret.invalid', 401, 'secret', {}, io.BytesIO(b'secret')), 'route_auth'),
                              (HTTPError('https://secret.invalid', 403, 'secret', {}, io.BytesIO(b'secret')), 'route_permission'),
                              (HTTPError('https://secret.invalid', 429, 'secret', {}, io.BytesIO(b'secret')), 'route_quota'),
                              (URLError(TimeoutError('secret')), 'route_timeout'),
                              (URLError('secret'), 'route_network')]:
            client, opener = self.client(failure=failure)
            with self.assertRaises(RouteError) as raised:
                client.query(request())
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn('secret', json.dumps(raised.exception.public()))
            self.assertEqual(opener.open.call_count, 1)

    @patch('app.routes.read_rest_key', return_value='a' * 32)
    def test_payload_cap_budget_and_no_redirect(self, _):
        client, opener = self.client()
        opener.open.return_value.__enter__.return_value.read.return_value = b' ' * (MAX_BYTES + 1)
        with self.assertRaises(RouteError) as raised:
            client.query(request())
        self.assertEqual(raised.exception.code, 'route_bad_response')
        client, opener = self.client()
        for _ in range(12):
            client.query(request())
        with self.assertRaises(RouteError) as raised:
            client.query(request())
        self.assertEqual(raised.exception.code, 'route_local_limit')
        self.assertEqual(opener.open.call_count, 12)
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_missing_key_does_not_call_provider_and_inputs_reject_extra_nonfinite_or_same_points(self):
        client, opener = self.client()
        self.assertFalse(client.status()['configured'])
        with self.assertRaises(RouteError) as raised:
            client.query(request())
        self.assertEqual(raised.exception.code, 'route_key_missing')
        opener.open.assert_not_called()
        for changes in [{'url': 'https://evil.invalid'}, {'mode': 'driving'},
                        {'end': {'latitude': 35.18, 'longitude': 128.11}},
                        {'start': {'latitude': float('nan'), 'longitude': 128.11}},
                        {'start': {'latitude': 35.18, 'longitude': 35.18}}]:
            with self.assertRaises(ValueError):
                request(**changes)


class RouteHttpTests(unittest.TestCase):
    def test_session_guard_display_only_and_no_transcript_or_comparison_persistence(self):
        client = Mock()
        client.query.return_value = {'provider': 'fixture', 'routes': [], 'llm_transfer': False}
        state = AppState(index(), route_client=client)
        state.record = Mock()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state, Path('missing-env')))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def call(path, data=None, headers=None):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('POST' if data is not None else 'GET', path,
                               json.dumps(data) if data is not None else None,
                               {'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse()
            status, body = response.status, json.loads(response.read())
            connection.close()
            return status, body
        try:
            payload = request().model_dump()
            self.assertEqual(set(call('/api/config')[1]), {'javascriptKey'})
            self.assertEqual(call('/api/routes', payload)[0], 403)
            _, bootstrap = call('/api/bootstrap')
            headers = {'X-Session': bootstrap['token']}
            self.assertEqual(call('/api/routes', payload, {**headers, 'Origin': 'http://evil.invalid'})[0], 403)
            self.assertEqual(call('/api/routes', {**payload, 'url': 'https://evil.invalid'}, headers)[0], 400)
            status, result = call('/api/routes', payload, headers)
            self.assertEqual(status, 200)
            self.assertEqual(result['provider'], 'fixture')
            client.query.assert_called_once()
            state.record.assert_not_called()
            self.assertIsNone(state.sessions[bootstrap['token']]['comparison'])
            client.query.side_effect = RouteError('route_timeout', 504)
            status, result = call('/api/routes', payload, headers)
            self.assertEqual((status, result['error']), (504, 'route_timeout'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
