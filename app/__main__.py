"""P0 command-line entrypoints. No public model-execution HTTP endpoint."""
import argparse
import json
from pathlib import Path
import sys

from .codex_runner import CodexRunner, RunnerError, DEFAULT_MODEL, DEFAULT_REASONING_EFFORT, REASONING_EFFORTS
from .contracts import Contract, InterviewTurn, NeedProfile, output_schema
from .intake import prepare_profile
from .preferences import update_preferences


class SearchProbe(Contract):
    answer: str
    urls: list[str]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    intake = sub.add_parser("intake", help="요청과 선택적 인터뷰 답변을 니즈 규격으로 변환")
    intake.add_argument("--request-file", type=Path, required=True)
    intake.add_argument("--previous", type=Path)
    intake.add_argument("--answers", type=Path)
    for p in (intake, sub.add_parser("probe-search", help="공식 문서 검색 지원 확인용; 카테고리 검색 구현 아님")):
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--timeout", type=float, default=120)
        p.add_argument("--model", default=DEFAULT_MODEL)
        p.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, choices=REASONING_EFFORTS)
        p.add_argument("--codex", default=None)
    schema = sub.add_parser("schema")
    schema.add_argument("--output", type=Path, required=True)
    preferences = sub.add_parser("preferences", help="가중치 편집/확인; 모델을 호출하지 않음")
    preferences.add_argument("--profile", type=Path, required=True)
    preferences.add_argument("--patch", type=Path, required=True,
                             help="group_weights, criterion_importance, confirm_weights의 JSON 객체")
    preferences.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output exists; choose a new file to retain previous evidence")
        if args.command == "schema":
            result = output_schema(NeedProfile)
        elif args.command == "preferences":
            profile = NeedProfile.model_validate_json(args.profile.read_text(encoding="utf-8"))
            patch = json.loads(args.patch.read_text(encoding="utf-8"))
            if not isinstance(patch, dict) or set(patch) - {"group_weights", "criterion_importance", "confirm_weights"}:
                raise ValueError("invalid preference patch")
            result = update_preferences(profile, **patch).model_dump()
        else:
            runner = CodexRunner(args.codex, timeout=args.timeout, model=args.model,
                                 reasoning_effort=args.reasoning_effort)
            if args.command == "intake":
                request = args.request_file.read_text(encoding="utf-8").strip()
                previous = NeedProfile.model_validate_json(args.previous.read_text(encoding="utf-8")) if args.previous else None
                answers = [InterviewTurn.model_validate(a) for a in json.loads(args.answers.read_text(encoding="utf-8"))] if args.answers else []
                result = prepare_profile(runner, request, answers, previous).model_dump()
            else:
                result = runner.run(
                    "Use live web search now to find OpenAI's official Codex non-interactive documentation. "
                    "Read it and briefly explain --output-schema in Korean with the actual page URL. "
                    "Use only learn.chatgpt.com and developers.openai.com. Do not use shell or any other tools.",
                    SearchProbe, search=True, domains=["learn.chatgpt.com", "developers.openai.com"]).model_dump()
                if runner.last_metadata.get("web_search_count", 0) < 1:
                    raise RunnerError("search_not_observed")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.with_suffix(args.output.suffix + ".metadata.json").write_text(
                json.dumps(runner.last_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "completed", "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (RunnerError, ValueError, OSError) as error:
        code = error.code if isinstance(error, RunnerError) else "invalid_input_or_io"
        if isinstance(error, RunnerError) and "runner" in locals():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.with_suffix(args.output.suffix + ".error.json").write_text(
                json.dumps(runner.last_metadata | {"error_code": code}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "failed", "error_code": code}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
