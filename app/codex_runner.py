"""Subscription-authenticated CLI adapter: isolated calls, typed output, no shell interpolation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import TypeVar

from pydantic import ValidationError
from .contracts import Contract, output_schema

T = TypeVar("T", bound=Contract)


def discover_executable() -> str | None:
    if os.name == "nt":
        # The desktop binary may be older than the npm CLI used by `codex` in PowerShell.
        shim = shutil.which("codex.cmd")
        if shim:
            package = Path(shim).parent / "node_modules/@openai/codex/node_modules/@openai"
            matches = list(package.glob("codex-win32-*/vendor/*/bin/codex.exe"))
            if len(matches) == 1:
                return str(matches[0])
        return shutil.which("codex.exe")
    return shutil.which("codex")


class RunnerError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def classify_error(text: str) -> str:
    text = text.lower()
    if any(s in text for s in ("usage limit", "rate limit", "quota", "429")):
        return "usage_limit"
    if any(s in text for s in ("not logged in", "unauthorized", "401", "authentication", "refresh token")):
        return "authentication_required"
    if "schema" in text:
        return "schema_rejected"
    if any(s in text for s in ("unknown field", "unknown configuration", "unrecognized", "invalid config", "unexpected argument")):
        return "unsupported_configuration"
    if any(s in text for s in ("connection", "stream disconnected", "network", "502", "503")):
        return "connection_error"
    return "execution_failed"


class CodexRunner:
    _slot = threading.Lock()

    def __init__(self, executable: str | None = None, timeout: float = 120, model: str | None = None):
        path = executable or discover_executable()
        if not path:
            raise RunnerError("codex_not_found")
        self.executable = str(Path(path).resolve())
        if os.name == "nt" and Path(self.executable).suffix.lower() != ".exe":
            raise RunnerError("native_executable_required")
        if timeout <= 0:
            raise ValueError("positive timeout required")
        self.timeout = timeout
        self.model = model
        self.last_metadata = {}

    def version(self) -> str:
        try:
            result = subprocess.run([self.executable, "--version"], capture_output=True,
                env=self.environment(), timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return result.stdout.decode("utf-8", errors="replace").strip()[:120]
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"

    def command(self, directory: Path, schema_file: Path, output_file: Path,
                search: bool = False, domains: list[str] | None = None) -> list[str]:
        args = [self.executable, "exec", "--ignore-user-config", "--strict-config",
                "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                "--json", "--color", "never", "-C", str(directory),
                "--output-schema", str(schema_file), "-o", str(output_file)]
        settings = {
            "approval_policy": '"never"', "project_doc_max_bytes": "0",
            "web_search": '"live"' if search else '"disabled"',
            "history.persistence": '"none"', "agents.enabled": "false",
        }
        # Native features present in the installed CLI. No user MCP/plugin config is loaded.
        for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins",
                        "remote_plugin", "hooks", "memories", "goals", "browser_use",
                        "browser_use_external", "computer_use", "in_app_browser",
                        "image_generation", "view_image", "skill_search", "workspace_dependencies"):
            settings[f"features.{feature}"] = "false"
        settings["features.skip_host_skill_discovery"] = "true"
        if domains:
            if not search or any(not d or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in d) for d in domains):
                raise ValueError("invalid search domain")
            settings["tools.web_search.allowed_domains"] = json.dumps(domains)
        for key, value in settings.items():
            args.extend(["-c", f"{key}={value}"])
        if self.model:
            args.extend(["--model", self.model])
        return args + ["-"]

    @staticmethod
    def environment() -> dict[str, str]:
        # Keep OS/auth-location and network transport settings; do not forward API keys or thread metadata.
        allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE",
                   "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "CODEX_HOME",
                   "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "LANG", "LC_ALL"}
        return {k: v for k, v in os.environ.items() if k.upper() in allowed}

    @staticmethod
    def _stop(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def run(self, prompt: str, response_type: type[T], *, cancel: threading.Event | None = None,
            search: bool = False, domains: list[str] | None = None, retries: int = 0) -> T:
        if retries not in (0, 1):
            raise ValueError("at most one explicit retry")
        if not self._slot.acquire(blocking=False):
            raise RunnerError("busy")
        try:
            for attempt in range(retries + 1):
                try:
                    return self._run(prompt, response_type, cancel or threading.Event(), search, domains)
                except RunnerError as error:
                    self.last_metadata["error_code"] = error.code
                    if attempt == retries or error.code != "connection_error":
                        raise
        finally:
            self._slot.release()

    def _run(self, prompt, response_type, cancel, search, domains):
        started = time.monotonic()
        self.last_metadata = {"search_mode": "live" if search else "disabled",
                              "requested_model": self.model, "cli_version": self.version()}
        if cancel.is_set():
            raise RunnerError("cancelled")
        with tempfile.TemporaryDirectory(prefix="saljari-codex-") as temp:
            folder = Path(temp)
            schema_file, output_file = folder / "schema.json", folder / "result.json"
            schema_file.write_text(json.dumps(output_schema(response_type), ensure_ascii=False), encoding="utf-8")
            args = self.command(folder, schema_file, output_file, search, domains)
            try:
                process = subprocess.Popen(args, cwd=folder, env=self.environment(),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt")
            except OSError as error:
                raise RunnerError("launch_failed") from error
            payload = prompt.encode("utf-8")
            try:
                while True:
                    if cancel.is_set():
                        raise RunnerError("cancelled")
                    if time.monotonic() - started > self.timeout:
                        raise RunnerError("timeout")
                    try:
                        stdout, stderr = process.communicate(input=payload, timeout=0.1)
                        break
                    except subprocess.TimeoutExpired as pending:
                        payload = None
                        if len(pending.output or b"") + len(pending.stderr or b"") > 4_000_000:
                            raise RunnerError("output_too_large")
            except BaseException:
                self._stop(process)
                raise
            finally:
                self.last_metadata["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if cancel.is_set():
                raise RunnerError("cancelled")
            self.last_metadata["exit_code"] = process.returncode
            self.last_metadata.update(self._events(stdout, search))
            if process.returncode != 0:
                raise RunnerError(classify_error((stderr + stdout).decode("utf-8", errors="replace")))
            if not output_file.exists() or output_file.stat().st_size > 1_000_000:
                raise RunnerError("missing_or_oversized_result")
            try:
                return response_type.model_validate_json(output_file.read_text(encoding="utf-8"))
            except (ValidationError, ValueError, UnicodeError) as error:
                if isinstance(error, ValidationError):
                    self.last_metadata['validation_errors'] = [
                        {'location':list(item['loc']), 'type':item['type']}
                        for item in error.errors(include_input=False, include_context=False)[:10]]
                raise RunnerError("invalid_response") from error

    @staticmethod
    def _events(raw: bytes, search: bool) -> dict:
        summary = {"event_types": [], "web_search_count": 0, "usage": None}
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind and kind not in summary["event_types"]:
                summary["event_types"].append(kind)
            item = event.get("item", {})
            item_type = item.get("type")
            if item_type in ("command_execution", "mcp_tool_call", "file_change"):
                raise RunnerError("unexpected_tool_use")
            if item_type == "web_search" and kind == "item.completed":
                if not search:
                    raise RunnerError("unexpected_web_search")
                summary["web_search_count"] += 1
            if kind == "turn.completed":
                summary["usage"] = event.get("usage")
        # Never persist reasoning, full event text, stderr, user prompts or auth material.
        return summary
