"""Opt-in local test transcripts. Never log credentials or model reasoning."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from threading import Lock
from uuid import uuid4


_SENSITIVE = re.compile(r'^(token|session_token|javascriptkey|api[_-]?key|authorization|cookie|password|secret|access_token|refresh_token)$', re.I)
_KST = timezone(timedelta(hours=9))


def safe_content(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if _SENSITIVE.match(k) else safe_content(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_content(v) for v in value]
    if isinstance(value, str):
        # Prompts are JSON plus instructions; mask credential assignments even in text.
        value = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~-]+', r'\1[REDACTED]', value)
        value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
        return re.sub(r'(?i)(["\']?(?:token|session_token|javascriptkey|api[_-]?key|appkey|access_token|refresh_token|authorization|cookie|password|secret)["\']?\s*[:=]\s*)(["\'][^"\']*["\']|[^\s,}\]]+)', r'\1"[REDACTED]"', value)
    return value


class DebugTranscripts:
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def start(self):
        name = datetime.now(_KST).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:12] + '.txt'
        path = self.directory / name
        self.append(path, '테스트 대화 시작', {'format': 'saljari-debug-v1', 'notice': '개인 입력 포함. 로컬 테스트 전용. 인증값·세션 토큰·AI 내부 추론 제외.'})
        return path

    def append(self, path, role, content, **details):
        stamp = datetime.now(_KST).isoformat(timespec='milliseconds')
        body = safe_content(content)
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False, indent=2)
        header = ' '.join(f'{key}={value}' for key, value in details.items())
        with self.lock, Path(path).open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(f'\n[{stamp}] {role} {header}\n{body}\n')

