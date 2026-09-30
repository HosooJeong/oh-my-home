# P0: 니즈·개인 가중치·모듈 실행 기반

메인 오케스트레이터 → 카테고리 모듈 → 메인 통합을 위한 Python 코어다. 후속 M1에서 실제 생활 데이터와 제품 입력 화면을 연결했다. [실행 안내](../README.md), [생활 모듈 규격](modules/README.md)을 따른다. `examples/p0_demo.py`의 모듈은 계산/통합 설명용 가상 자료이며 실제 주거 추천이 아니다.

## 실행

Python 3.11 이상, `pip install -r requirements.txt`. 검증 환경은 Windows/Python 3.13.3/Pydantic 2.12.5다. 지도 표본 도구의 기존 Python 표준 라이브러리 실행도 유지된다.

~~~powershell
python -X utf8 examples/p0_demo.py
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m app schema --output work/needs-schema.json
~~~

가상 예제는 같은 사실에서 교통/비용 중요도를 70/30→30/70으로 바꾼다. A/B 점수가 75/62→55/78로 달라진다. 모델/네트워크 호출은 없다.

현재 ChatGPT 계정으로 로그인된 Codex CLI를 사용해 가상 니즈를 정리하려면:

~~~powershell
codex login status
python -X utf8 -m app intake --request-file examples/intake-request.txt --output work/profile-1.json
~~~

별도 OpenAI API 키를 요구하지 않는다. 구독 사용량과 인터넷 연결은 필요하다. 실제 사용자 입력/응답 파일은 로컬 `work/` 등 Git 제외 경로에 두고 공유하지 않는다. 출력 파일이 이미 있으면 덮어쓰지 않으므로 다음 버전 이름을 쓴다.

인터뷰 답변 파일은 `[ {"question_id":"실제 질문 id", "answer":"사용자 답변"} ]` 형식이다. 답변에 원문 요청을 다시 써야 하는 것은 아니다.

~~~powershell
python -X utf8 -m app intake --request-file examples/intake-request.txt --previous work/profile-1.json --answers work/answers.json --output work/profile-2.json
~~~

가중치만 수정하려면 `weights.json`에 `{"group_weights":{"living":50.0,"transport":30.0,"housing":20.0},"confirm_weights":true}`처럼 **해당 프로필에 실제로 있는 ID**를 쓴다. `confirm_weights`는 제안된 나머지 가중치를 사용자가 확인했다는 명시적 입력이다. 일반 모델 응답을 자동 확인하는 기능이 아니다.

~~~powershell
python -X utf8 -m app preferences --profile work/profile-2.json --patch work/weights.json --output work/profile-3.json
~~~

이는 모델 호출 없이 가중치와 프로필 버전을 갱신한다. `reevaluate_preferences()`는 이전 실행의 프로필/후보 지문을 검사하고 같은 근거로 재계산한다. 후보 위치나 조건이 바뀌면 재조회를 요구한다. 시점이 지난 외부 자료를 자동 갱신하는 기능은 아직 없으며 자료 시점을 유지한다.

공식 문서의 실제 검색 지원만 확인하는 별도 진단:

~~~powershell
python -X utf8 -m app probe-search --output work/search-probe.json
~~~

이 명령은 검색 이벤트가 없으면 실패 처리한다. 분야별 웹검색 어댑터·검색 예산 집행·운영시간 검증을 구현한 것은 아니다. 검색 조회는 구독 사용량을 크게 늘릴 수 있어 일반 니즈 정리에서는 끈다.

## 코드 경계

M3 집·비용은 [과거 아파트 거래 참고 모듈](../docs/housing-reference.md)이다. `ReferenceResult`를 `references`로 메인에 합치며 점수 근거 `Evidence`와 분리한다. 현재 가격 점수 반영 0, 실제 매물/개별 집 가격/예산 통과 판정 없음. 명시된 예산·면적·유형은 보존하고 실제 집 조건이 필요하면 미지원 상태를 유지한다. 중요도만 수정할 때 참고 원본/조회 지문은 유지하고 프로필 지문만 갱신한다.

- `contracts.py`: 배경/평가 조건 분리, 필수조건·선호·가중치·모듈 요청/결과·근거 규격. 6개 밖의 확장 그룹/조건도 보존한다. Pydantic은 외부 필드·NaN·잘못된 단위 규칙·중복 ID 등을 검증한다.
- `intake.py`: 요청과 필요한 인터뷰 답변을 구조화. 명시된 값/추정값과 원문 인용 검증. 모델이 원문을 바꿔 인용하면 수용하지 않는다.
- `evaluation.py`: 개인별 적합도와 가중 기여 계산. 필수조건 실패는 다른 장점으로 상쇄하지 않는다. 미확인 값은 점수 구간과 근거 충족 범위로 반환하고 확정 순위는 유보한다.
- `preferences.py`: 사용자 중요도 변경과 검증된 이전 실행의 근거 재사용. 제안 가중치는 자동 확정하지 않는다.
- `orchestrator.py`: 필요한 모듈을 중요도에 따라 순차 호출하고 동일 후보/조건 버전의 결과만 통합. 실패한 모듈이 성공한 모듈 결과를 지우지 않는다. 등록되지 않은 모듈은 미지원으로 남긴다.
- `codex_runner.py`: 구독 인증 CLI 호출, JSON Schema와 최종 JSON 검사, 제한 시간/취소·자식 프로세스 종료, 동시 실행 거절, 인증/한도/형식 오류 구분.

모듈은 `id`, `version`, `run(ModuleRequest, cancel_event)`를 구현해 `CategoryResult`를 반환한다. 입력에는 동일 후보·니즈·개인별 조건 가중치와 요청 지문이 들어 있다. `unsupported_criterion_ids`와 `questions`로 미지원/추가 질문을 메인에 전달한다. 모듈은 취소 신호를 확인하고 자체 네트워크 요청에 시간 제한을 설정해야 한다. 임의의 블로킹 모듈을 메인이 강제로 종료하는 격리 실행은 아직 없다.

## Codex 실행 범위

Windows에서는 npm `codex.cmd` 패키지의 네이티브 실행 파일을 우선 찾는다. 데스크톱 앱의 별도 구버전 실행 파일과 혼동하지 않게 한다. 자동 탐색이 안 되면 `--codex`로 네이티브 실행 파일 경로를 지정할 수 있다. 현재 기본 모델을 임의로 고정하지 않으며 명시적 변경이 필요하면 `--model`을 사용한다. 실제 응답의 정확한 모델 ID가 노출되지 않으면 미확인으로 기록한다.

`--ignore-user-config`, 임시 작업 폴더, 읽기 전용, 검색 기본 비활성, 셸/MCP 사용자 설정/플러그인/서브에이전트 등 불필요한 기능 제외를 사용한다. `OPENAI_API_KEY`·현재 대화 식별자는 자식 환경에 전달하지 않는다. 인증 위치는 기존 계정을 사용하며 인증 파일을 복사하거나 로그에 적지 않는다. JSONL 이벤트와 최종 출력 파일은 분리하고, 메타데이터에 이벤트 종류·검색 횟수·토큰 수·시간만 저장한다. 내부 사고 내용·일반 이벤트 원문은 저장하지 않는다.

이는 앱 호출 설정이며 OS 전체의 보안 격리를 보장하지 않는다. 예상하지 못한 실행/파일변경/MCP 이벤트를 발견하면 결과를 거절하지만 그 검사가 이미 일어난 도구 동작을 되돌리지는 않는다. 아직 공개 HTTP 모델 실행 API를 노출하지 않는다. 카카오 키와 Local 응답을 모델 입력에 넣지 않는다.

실측·실패/수정 이력은 상위 프로젝트의 `docs/project-records/validation.md`와 `work/saljari-evidence/20260930/`에서 관리한다. 기준 문서를 코드 저장소에 중복 복사하지 않는다.

## 공식 참고

- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex 설정](https://learn.chatgpt.com/docs/config-file/config-reference), [웹검색](https://learn.chatgpt.com/docs/web-search)
- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/), [엄격한 검증](https://docs.pydantic.dev/latest/concepts/strict_mode/)

2026-09-30 문서와 로컬 설치본을 확인했다. 새 CLI로 변경할 때는 옵션·스키마·검색 진단을 다시 검증한다.
