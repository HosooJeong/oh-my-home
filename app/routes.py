"""Live Kakao routes for display only; never cached, logged, or sent to a model."""
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import socket
from threading import BoundedSemaphore, Lock
import time
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field, model_validator

from .contracts import Contract

SOURCE = 'https://developers.kakao.com/docs/ko/kakaomap/rest-api'
MAX_BYTES = 2_000_000
MESSAGES = {
    'route_key_missing': '경로 API의 서버 키를 설정해야 해요.',
    'route_key_invalid': '경로 API의 서버 키 설정을 확인해 주세요.',
    'route_auth': '카카오 REST API 키와 허용 IP 설정을 확인해 주세요.',
    'route_permission': '카카오맵 API 활성화와 사용 권한을 확인해 주세요.',
    'route_quota': '카카오 경로 API의 사용 한도에 도달했어요.',
    'route_local_limit': '잠시 후 다시 조회해 주세요. 서버 호출 한도에 도달했어요.',
    'route_busy': '다른 경로를 조회하고 있어요. 잠시 후 다시 시도해 주세요.',
    'route_timeout': '경로 조회가 지연됐어요. 다시 시도해 주세요.',
    'route_network': '카카오 경로 API에 연결하지 못했어요.',
    'route_not_found': '두 위치 사이의 경로를 찾지 못했어요.',
    'route_bad_response': '경로 응답을 확인하지 못했어요. 다시 시도해 주세요.',
    'route_upstream': '카카오 경로 API가 요청을 처리하지 못했어요.',
}


class RouteError(Exception):
    def __init__(self, code, http_status=502, provider_status=None):
        super().__init__(code)
        self.code, self.http_status, self.provider_status = code, http_status, provider_status

    def public(self):
        return {'error': self.code, 'message': MESSAGES[self.code],
                'provider_http_status': self.provider_status}


class Point(Contract):
    latitude: Annotated[float, Field(ge=33, le=39, allow_inf_nan=False)]
    longitude: Annotated[float, Field(ge=124, le=132, allow_inf_nan=False)]


class RouteInput(Contract):
    start: Point
    end: Point
    mode: Literal['walk', 'transit'] = 'walk'
    walk_option: Literal['BROAD_FIRST', 'SHORTEST', 'ACCESSIBLE'] = 'BROAD_FIRST'

    @model_validator(mode='after')
    def distinct(self):
        if self.start == self.end:
            raise ValueError('same_route_points')
        return self


def read_rest_key(path: Path):
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except FileNotFoundError:
        return ''
    except OSError:
        raise RouteError('route_key_invalid', 503) from None
    for line in lines:
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'KAKAO_MAP_REST_API_KEY':
            value = value.strip()
            if value and not re.fullmatch(r'[a-fA-F0-9]{32}', value):
                raise RouteError('route_key_invalid', 503)
            return value
    return ''


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def number(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('invalid_route_number')
    return value


def normalize(document, mode):
    """Keep verified response fields only; unavailable routes never become zero distances."""
    if document.get('status') != 'OK':
        if document.get('status') in {'NO_RESULTS', 'ROUTE_RESULT_NOT_FOUND', 'STARTNODES_NULL',
                                     'ENDNODES_NULL', 'START_LINK_NOT_FOUND', 'END_LINK_NOT_FOUND',
                                     'TOO_FAR_AWAY', 'TOO_MANY_SEARCH_LINK'}:
            raise RouteError('route_not_found', 404)
        raise ValueError('invalid_route_status')
    routes = [document['route']] if mode == 'walk' else document['routes']
    if not isinstance(routes, list) or not 1 <= len(routes) <= 100:
        raise ValueError('invalid_route_count')
    result = []
    for route in routes:
        properties = route['properties']
        steps = [s for leg in route['legs'] for s in leg['steps']] if mode == 'walk' else route['steps']
        segments = []
        total_points = 0
        for step in steps:
            points = step['path']['points']
            if not isinstance(points, list):
                raise ValueError('invalid_route_geometry')
            segment = []
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError('invalid_route_point')
                longitude, latitude = number(point[0], 180), number(point[1], 90)
                if not 124 <= longitude <= 132 or not 33 <= latitude <= 39:
                    raise ValueError('route_geometry_outside_korea')
                segment.append([longitude, latitude])
            total_points += len(segment)
            if total_points > 50_000:
                raise ValueError('route_geometry_too_large')
            if segment:
                segments.append({'points': segment, 'mode': step['properties'].get('type', 'WALKING')
                                 if mode == 'transit' else 'WALKING'})
        if not segments:
            raise ValueError('missing_route_geometry')
        transfers = number(properties['transfers'], 100) if mode == 'transit' else None
        if transfers is not None and not isinstance(transfers, int):
            raise ValueError('invalid_transfers')
        if any(s['mode'] not in ('BUS', 'SUBWAY', 'WALKING') for s in segments):
            raise ValueError('invalid_segment_mode')
        result.append({'distance_m': number(properties['totalDistance'], 20_000_000),
                       'duration_s': number(properties['totalTime'], 604_800),
                       'transfers': transfers, 'segments': segments})
    return sorted(result, key=lambda r: (r['duration_s'], r['distance_m']))[:3]


class KakaoRoutes:
    def __init__(self, env_path, opener=None):
        self.env_path = Path(env_path)
        self.opener = opener or build_opener(NoRedirect())
        self.lock, self.active = Lock(), BoundedSemaphore(2)
        self.calls, self.day, self.daily_count = deque(), None, 0

    def status(self):
        try:
            ready = bool(read_rest_key(self.env_path))
            error = None if ready else 'route_key_missing'
        except RouteError as issue:
            ready, error = False, issue.code
        return {'configured': ready, 'error': error, 'modes': ['walk', 'transit'],
                'purpose': 'live_display_only', 'llm_transfer': False, 'cached': False}

    def _reserve(self):
        with self.lock:
            now = time.monotonic()
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            day = datetime.now(timezone.utc).date()
            if day != self.day:
                self.day, self.daily_count = day, 0
            # Small local-test budget; provider quota/paid settings are separate.
            if len(self.calls) >= 12 or self.daily_count >= 100:
                raise RouteError('route_local_limit', 429)
            self.calls.append(now)
            self.daily_count += 1

    def query(self, data: RouteInput):
        key = read_rest_key(self.env_path)
        if not key:
            raise RouteError('route_key_missing', 503)
        if not self.active.acquire(blocking=False):
            raise RouteError('route_busy', 409)
        try:
            self._reserve()
            parameters = {'start_x': format(data.start.longitude, '.8f'),
                          'start_y': format(data.start.latitude, '.8f'),
                          'end_x': format(data.end.longitude, '.8f'),
                          'end_y': format(data.end.latitude, '.8f'),
                          'input_coord': 'WGS84', 'output_coord': 'WGS84'}
            if data.mode == 'walk':
                parameters['route_mode'] = data.walk_option
            endpoint = 'walk' if data.mode == 'walk' else 'publictraffic'
            request = Request('https://dapi.kakao.com/v2/routing/' + endpoint + '?' + urlencode(parameters),
                              headers={'Authorization': 'KakaoAK ' + key, 'Accept': 'application/json'})
            try:
                with self.opener.open(request, timeout=8) as response:
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise RouteError('route_bad_response')
                    routes = normalize(json.loads(raw), data.mode)
            except HTTPError as issue:
                status = issue.code
                issue.close()
                code = {401: 'route_auth', 403: 'route_permission', 429: 'route_quota'}.get(status, 'route_upstream')
                raise RouteError(code, 429 if status == 429 else 502, status) from None
            except (TimeoutError, socket.timeout):
                raise RouteError('route_timeout', 504) from None
            except URLError as issue:
                code = 'route_timeout' if isinstance(issue.reason, (TimeoutError, socket.timeout)) else 'route_network'
                raise RouteError(code, 504 if code == 'route_timeout' else 502) from None
            except (ValueError, KeyError, TypeError, OverflowError, AttributeError):
                raise RouteError('route_bad_response') from None
            return {'provider': 'kakao', 'mode': data.mode, 'routes': routes,
                    'retrieved_at': datetime.now(timezone.utc).isoformat(), 'source_url': SOURCE,
                    'purpose': 'live_display_only', 'llm_transfer': False,
                    'notice': '조회 시점의 예상 경로예요. 안전성·운행 보장·실제 이동 시간은 별도 확인이 필요해요.'}
        finally:
            self.active.release()
