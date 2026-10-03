# AI 연결과 모델 설정

첫 화면·분석 결과·기존 워크스페이스의 **AI 설정**에서 연결 방식을 선택한다. 웹 앱과 명령행 니즈 정리의 기본값은 **OpenAI API / `gpt-6.1-sol` / `medium`**이다. Codex 설치·로그인은 기본 실행에 필요하지 않다. 키가 없으면 `api_key_missing`으로 실패하며 Codex나 다른 모델로 자동 전환하지 않는다. API 사용 권한·결제/한도는 실행 계정에서 준비한다.

OpenAI API를 선택해 API 키·모델 ID·추론 강도를 입력하고 적용하면 **다음 AI 요청**부터 사용한다. API와 Codex 모델명은 사용 계정의 실제 권한이 필요하다. API의 `모델 불러오기`는 입력한 설정을 적용하고 `/v1/models`에서 계정의 모델 목록을 조회한다. 목록 조회 성공이 모든 모델의 Responses·웹 검색·구조화 출력 지원을 보장하지 않는다. 지원하지 않는 조합은 오류로 표시하며 모델/강도/연결 방식의 자동 대체는 없다. 모델 기본값을 선택하면 API `reasoning` 필드를 생략한다. GPT-6.1 Sol은 공식 문서상 none/minimal을 지원하지 않으므로 해당 조합을 차단한다.

설정과 키는 기존 `X-Session`이 가리키는 **서버 메모리**에만 보관한다. 입력란은 비밀번호 형식이며 적용·오류 후 비운다. API 키를 localStorage/sessionStorage, HTML, 응답 JSON, 로그/디버그 대화, Git에 저장하지 않는다. 조회는 키 등록 여부만 반환한다. 입력을 비우면 등록된 키를 유지하며 `키 삭제`를 누르면 해당 세션 키를 제거한다. 다른 브라우저 세션과 공유하지 않는다. 세션은 마지막 요청 이후 약1시간, 서버 재시작 시 사라진다. 진행 중인 세션 작업이 있으면 설정 변경을 거절하고, 각 작업은 시작할 때의 불변 설정을 끝까지 사용한다. 여러 단계의 조사/응답 검토도 그 작업의 동일 runner를 이용한다.

서버 기본값을 별도 관리하려면 Git 밖 `--env-file` 또는 프로세스 환경에 아래 변수를 설정할 수 있다. UI는 이 파일을 쓰지 않는다. 파일로 제공한 기본 키는 서버 재시작 후에도 파일에서 다시 읽는다. UI의 키 삭제는 서버 기본 파일을 수정하지 않으며 새 세션은 서버 기본값을 다시 받는다.

```dotenv
SALJARI_LLM_PROVIDER=openai
SALJARI_LLM_MODEL=gpt-6.1-sol
SALJARI_LLM_EFFORT=medium
OPENAI_API_KEY=
```

설정 우선순위는 프로세스 환경변수 → env 파일 → 앱 기본값이다. 프로세스에 명시한 값은 빈 값도 파일보다 우선하며 템플릿의 빈 키가 환경변수의 키를 지우지는 않는다. 서버 파일/환경변수를 바꾸면 재시작한다. CLI의 명시적 `--provider`, `--model`, `--reasoning-effort`는 이 값보다 우선한다. 키를 명령행 인자로 받거나 출력하지 않는다. 기존 데이터 처리·오프라인 점수 계산·카카오 SDK/경로 조회는 AI 모델 설정의 영향을 받지 않는다. 웹/CLI는 같은 API 기본값을 사용한다.

```powershell
python -B -X utf8 -m app.web --env-file .env
python -X utf8 -m app intake --env-file .env --request-file examples/intake-request.txt --output work/profile-1.json
```

Codex를 쓰려면 화면에서 선택하거나 `SALJARI_LLM_PROVIDER=codex`로 명시한다. CLI는 `--provider codex --model gpt-6.1-sol --reasoning-effort medium`을 지정하고 Codex 설치·로그인이 필요하다. `--codex` 실행파일 지정은 이 연결에서만 유효하며 API와 함께 지정하면 거절한다.

API runner는 고정된 `https://api.openai.com/v1/responses`로 서버에서 호출한다. 사용자 니즈 입력·공개 보완 조사·별도 응답 검토의 기존 프롬프트/계약을 유지한다. `store:false`, JSON Schema strict 출력과 로컬 Pydantic 검증을 사용한다. 조건 정리와 별도 응답 검토는 웹 검색 도구를 제공하지 않으며 조사 요청만 `web_search`를 허용하고 실제 완료 검색 호출 수를 확인한다. 기존 원문 연결·신선도·원문 접속/인용 대조·AI 검토·점수와 정성 보완의 경계는 유지한다. 카카오 지도·경로 원시 응답은 보내지 않는다.

요청은 기본120초·최대응답4MB·출력토큰 상한12000으로 제한하고, 취소/제한 시간에는 활성 소켓을 닫는다. 검색 도메인 허용목록을 전달하며 쉘·파일·MCP·다른 도구 출력을 거절한다. HTTP 리다이렉트를 따르지 않으며 임의 API 주소 입력은 지원하지 않는다. 인증/권한/사용한도/모델 미지원/설정 오류·거절·미완료 응답을 구분한다. 비용이 발생할 수 있는 요청을 자동 재시도하거나 실패 시 Codex로 돌리지 않는다. 사용량과 요청 모델/강도/연결 방식을 작업 metadata에 남기며 API 키·내부 추론·원시 에러 메시지는 남기지 않는다. `store:false`는 OpenAI의 모든 서버 로그 보관 정책을 없애는 설정이라고 주장하지 않는다.

검증은 합성 키·모의 HTTP 응답을 이용한 계약/보호 검사와 실제 로컬 UI 조작을 구분한다. 실제 유효한 사용자 키의 Responses 호출, 결제·모델 권한 및 웹 검색 결과 수용은 해당 계정으로 별도 확인해야 한다. 기존 시험·시연은 Codex 연결의 기록이며 기본값 변경을 API 실호출 성공으로 바꾸어 기록하지 않는다.

공식 형식 확인(2026-10-04): [Responses API](https://developers.openai.com/api/reference/resources/responses), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [웹 검색](https://developers.openai.com/api/docs/guides/tools-web-search), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol). 다른 회사/임의 호환 API는 이번 범위 밖이다.
