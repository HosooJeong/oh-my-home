"""Per-session AI configuration. Credentials never enter public JSON or files."""
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import re

from .codex_runner import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT, REASONING_EFFORTS, CodexRunner, RunnerError

API_EFFORTS = ('auto', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
MODEL_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}')


@dataclass(frozen=True)
class ModelSettings:
    provider: str = 'openai'
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_REASONING_EFFORT
    api_key: str = field(default='', repr=False)

    def public(self):
        return {'provider': self.provider, 'model': self.model, 'effort': self.effort,
                'key_configured': bool(self.api_key),
                'ready': self.provider == 'codex' or bool(self.api_key)}

    def updated(self, data):
        if not isinstance(data, dict) or set(data) - {'provider', 'model', 'effort', 'api_key', 'remove_key'}:
            raise RunnerError('invalid_model_settings')
        provider, model, effort = (data.get(k, getattr(self, k)) for k in ('provider', 'model', 'effort'))
        if provider not in ('codex', 'openai') or not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model):
            raise RunnerError('invalid_model_settings')
        if not isinstance(effort, str) or effort not in (REASONING_EFFORTS if provider == 'codex' else API_EFFORTS):
            raise RunnerError('unsupported_configuration')
        if provider == 'openai' and model == 'gpt-6.1-sol' and effort in ('none', 'minimal'):
            raise RunnerError('unsupported_configuration')
        key = data.get('api_key', '')
        remove = data.get('remove_key', False)
        if not isinstance(key, str) or not isinstance(remove, bool) or (remove and key):
            raise RunnerError('invalid_model_settings')
        if key and (not 16 <= len(key) <= 512 or any(not 33 <= ord(ch) <= 126 for ch in key)):
            raise RunnerError('invalid_api_key')
        return replace(self, provider=provider, model=model, effort=effort,
                       api_key='' if remove else key or self.api_key)

    def runner(self, default_factory=CodexRunner, *, timeout=120, codex=None):
        if self.provider == 'openai':
            if codex is not None:
                raise RunnerError('unsupported_configuration')
            from .openai_runner import OpenAIRunner
            return OpenAIRunner(self.api_key, self.model, self.effort, timeout=timeout)
        # An explicitly selected Codex connection may use an injected runner.
        if self.model == DEFAULT_MODEL and self.effort == DEFAULT_REASONING_EFFORT and timeout == 120 and codex is None:
            return default_factory()
        return CodexRunner(codex, timeout=timeout, model=self.model, reasoning_effort=self.effort)


def server_settings(path: Path):
    names = ('SALJARI_LLM_PROVIDER', 'SALJARI_LLM_MODEL', 'SALJARI_LLM_EFFORT', 'OPENAI_API_KEY')
    values = {}
    try:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip() in names:
                values[name.strip()] = value.strip()
    except FileNotFoundError:
        pass
    # Process settings override the local file, including a template's blank key.
    for name in names:
        if name in os.environ:
            values[name] = os.environ[name]
    data = {k: values[name] for k, name in zip(('provider', 'model', 'effort', 'api_key'), names) if values.get(name)}
    return ModelSettings().updated(data)
