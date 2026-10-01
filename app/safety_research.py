"""Bounded official local-board research; never a risk prediction or score input."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser
from pydantic import Field

from .codex_runner import RunnerError
from .contracts import Contract
from .modules.safety import TOPICS
from .research_policy import SourcePage, admissible_excerpt, normalize, prompt_rules, MAX_AGE_DAYS
from .reviews import NoRedirect

DOMAINS = ['www.jinju.go.kr']  # First provider, not an exhaustive safety/environment search.
AGENT = 'SaljariOfficialResearch/0.1'
Text = Annotated[str, Field(min_length=1, max_length=300)]


class SafetyExcerpt(Contract):
    source_url: Annotated[str, Field(min_length=1, max_length=1000)]
    title: Text
    published_date: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')] | None
    topic: Literal['night', 'traffic', 'flood', 'noise', 'air']
    quote: Annotated[str, Field(min_length=1, max_length=160)]
    interpretation: Text


class AreaResearch(Contract):
    area_code: Text
    excerpts: Annotated[list[SafetyExcerpt], Field(max_length=2)]


class SafetyResearchResponse(Contract):
    items: Annotated[list[AreaResearch], Field(min_length=1, max_length=3)]


def official_url(value):
    try:
        u = urlsplit(value)
        q = parse_qs(u.query)
        if (u.scheme != 'https' or u.hostname not in DOMAINS or u.username or u.password
                or u.port not in (None,443) or re.search(r'[\s\\\x00-\x1f]', value)
                or not re.fullmatch(r'/(?:[0-9]+/)*[0-9]+\.web', u.path)
                or q.get('amode') != ['view'] or not re.fullmatch(r'[0-9]+', q.get('idx', [''])[0])
                or len(q.get('idx', [])) != 1):
            return None
        params = {'amode': 'view', 'idx': q['idx'][0]}
        if 'gcode' in q:
            if len(q['gcode']) != 1 or not q['gcode'][0].isdigit(): return None
            params['gcode'] = q['gcode'][0]
        return 'https://www.jinju.go.kr' + u.path + '?' + urlencode(params)
    except (ValueError, IndexError): return None


class OfficialArticleParser(HTMLParser):
    """Read only the official board info and article body, never navigation/footer area names."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.body, self.info, self.title = [], [], [], []
        self.body_count, self.info_count = 0, 0

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs); classes = attr.get('class', '').split()
        scope = 'body' if 'substanceautolink' in classes else 'info' if 'info1' in classes else 'title' if attr.get('id') == 'sns_bbs_title' else None
        if scope == 'body': self.body_count += 1
        if scope == 'info': self.info_count += 1
        if tag not in ('br','hr','img','input','meta','link','source','wbr'):
            self.stack.append((tag, scope))
        if tag == 'br' and any(s == 'body' for _,s in self.stack): self.body.append(' ')

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]; break

    def handle_data(self, data):
        if any(t in ('script','style','noscript') for t,_ in self.stack): return
        for scope in ('body','info','title'):
            if any(s == scope for _,s in self.stack): getattr(self, scope).append(data)

    def page(self):
        if self.body_count != 1 or self.info_count != 1 or not self.body: return None
        info = normalize(' '.join(self.info))
        dates = tuple(sorted(set(re.findall(r'작성일\s*[:：]?\s*(\d{4}-\d{2}-\d{2})', info))))
        return SourcePage(normalize(' '.join(self.title + self.body)), dates)


def parse_official_article(html):
    parser = OfficialArticleParser(); parser.feed(html); return parser.page()


def fetch_official_article(url, cancel):
    if official_url(url) != url or cancel.is_set(): return None
    opener = build_opener(NoRedirect())
    def read(target, cap):
        if cancel.is_set(): raise RunnerError('cancelled')
        with opener.open(Request(target, headers={'User-Agent':AGENT}), timeout=5) as r:
            raw = r.read(cap+1)
            if len(raw)>cap: raise ValueError('oversized source')
            return raw.decode('utf-8')
    try:
        robots = RobotFileParser(); robots.parse(read('https://www.jinju.go.kr/robots.txt',64000).splitlines())
        if not robots.can_fetch(AGENT,url): return None
        return parse_official_article(read(url,1_000_000))
    except RunnerError: raise
    except Exception: return None


INSTRUCTIONS = '''살자리의 안전·환경 공식 지역자료 보완 조사기다.
입력에는 공개 행정동 이름/코드, 문제 종류와 비식별 기능 questions가 있다.
각 행정동의 questions에 담긴 실제 요청 문제를 직접 웹검색하고 원문을 읽어라. 이를 범용 안전 소개로 대신하지 마라.
제공처는 진주시청 www.jinju.go.kr의 개별 게시글이다. 전체 4회 이내 검색을 목표로 하라.
작성일이 확인되는 최신 게시글 중 본문이 해당 읍면동과 요청 문제를 직접 다루는 경우만 선택하라.
사이트 메뉴에 동 이름이 있다는 이유로 그 동의 자료로 연결하지 마라. 시 전체 집계/다른 동은 해당 동 근거가 아니다.
사고/피해 사례, 현장 점검, 정책과 실제 완료된 조치를 구분하라. 예방 공사 계획은 안전 보장이 아니다.
사례나 보도자료가 없다고 안전/사고 없음으로 해석하지 마라. 범죄율/재해 확률/소음/미세먼지 수치를 추정하지 마라.
각 area_code를 정확히 한 번 반환하라. 지역당 최대 2개 인용이며 없는 경우 excerpts=[]다.
source_url은 amode=view와 idx가 있는 개별 게시글 URL이다. 원문을 못 읽으면 인용하지 마라.
published_date는 본문 위 작성일(수정일 아님), quote는 연속된 짧은 원문 그대로 출처당 총20단어/160자 이하.
topic은 입력 topics 중 하나, interpretation은 해당 인용에 한정한 설명이다. 집/통학로 위험도나 안전도 결론을 내리지 마라.
'''


def research_safety(runner, targets, *, cancel, fetcher=fetch_official_article):
    if not 1 <= len(targets) <= 3 or len({t['area_code'] for t in targets}) != len(targets):
        raise ValueError('invalid area scope')
    if cancel.is_set(): raise RunnerError('cancelled')
    payload = [{'area_code':t['area_code'], 'area_name':t['area_name'],
                'topics': {k:TOPICS[k] for k in t['topics']},'questions':t.get('questions',[])} for t in targets]
    answer = runner.run(prompt_rules() + INSTRUCTIONS + '\n공개 조사 범위 JSON:\n' + json.dumps(payload,ensure_ascii=False),
                        SafetyResearchResponse, search=True, domains=DOMAINS, cancel=cancel, retries=0)
    expected = {t['area_code']:t for t in targets}
    if len(answer.items) != len(expected) or {i.area_code for i in answer.items} != set(expected):
        raise RunnerError('invalid_response')
    pages, used, items = {}, {}, []
    keywords = {'night':('야간','방범','안심','조명'), 'traffic':('사고','횡단','보행','어린이보호','교통안전'),
                'flood':('침수','홍수','집중호우','재해','재난'), 'noise':('소음',), 'air':('미세먼지','대기질','대기환경','대기오염')}
    for item in answer.items:
        accepted, reasons = [], {}
        target = expected[item.area_code]
        for excerpt in item.excerpts:
            if cancel.is_set(): raise RunnerError('cancelled')
            url = official_url(excerpt.source_url); words = len(excerpt.quote.split())
            reason = None
            if not url or words > 20 or used.get(url,0)+words > 20 or excerpt.topic not in target['topics']:
                reason = 'invalid_source_or_topic_or_quote_budget'
            elif runner.last_metadata.get('web_search_count',0) < 1:
                reason = 'search_unverified'
            else:
                if url not in pages: pages[url] = fetcher(url,cancel)
                page = pages[url]; reason = admissible_excerpt(excerpt,page)
                if not reason:
                    compact = re.sub(r'\s+', '', page.text)
                    # Both region and issue must occur in article content; no city-wide fallback.
                    if target['area_name'] not in compact: reason = 'area_unverified'
                    elif not any(k in excerpt.quote for k in keywords[excerpt.topic]): reason = 'topic_unverified'
            if reason:
                reasons[reason] = reasons.get(reason,0)+1; continue
            used[url] = used.get(url,0)+words
            accepted.append({**excerpt.model_dump(), 'source_url':url, 'quote_verified':True,
                'publication_verified':True, 'score_eligible':False, 'kind':'official_statement'})
        found = {e['topic'] for e in accepted}
        items.append({'area_code':item.area_code,'area_name':target['area_name'],'requested_topics':target['topics'],
            'unconfirmed_topics':[k for k in target['topics'] if k not in found], 'excerpts':accepted,
            'rejection_reasons':reasons, 'status':'found' if accepted else 'unverified' if reasons else 'not_found'})
    if cancel.is_set(): raise RunnerError('cancelled')
    return {'items':items, 'checked_at':datetime.now(timezone.utc).isoformat(), 'score_eligible':False,
        'policy':{'max_age_days':MAX_AGE_DAYS, 'source_scope':DOMAINS, 'max_areas':3,
                  'numeric_scores':'unchanged', 'absence_of_report':'unknown'}}
