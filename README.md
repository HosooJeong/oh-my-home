# oh-my-home

**개인의 생활맥락을 이해하는 주거 의사결정 AI Agent**

진주에 처음 정착하거나 생활권을 옮기는 개인과 가족이 자신의 생활 조건에 맞춰 주거지를 검토하도록 돕는 웹 앱입니다. 자연어 선호를 비교 기준으로 정리하고 같은 후보를 공공자료로 분석해, 확인된 근거와 추가 확인이 필요한 조건을 함께 보여줍니다.

Python 서버와 정적 HTML/JavaScript로 구성하며 **기본 AI 연결은 OpenAI Responses API**입니다. Codex CLI 설치나 프런트엔드 빌드 없이 실행할 수 있습니다. 현재 공공자료의 지원 지역은 진주시입니다.

## 주요 기능

| 기능 | 사용 방법 |
| --- | --- |
| 주소 없는 생활권 탐색 | 집을 정하기 전에 개인 조건에 맞는 조사 지점을 선별합니다. |
| 집 한 곳 분석 | 지도에서 확정한 한 지점의 생활 조건과 미확인을 확인합니다. |
| 여러 집 비교 | 2~6개 지점을 같은 기준으로 분석합니다. |
| 생활 선호 입력 | 3D 블록으로 분야 중요도를 표현하고 자연어·인터뷰로 조건을 정리합니다. |
| 근거가 연결된 결과 | 시설명·등록 직선거리·자료 기준일·원문을 분야별로 확인합니다. |
| 중요도 재계산 | 같은 근거에 가중치만 바꿔 비교합니다. 위치·기준 변경은 재조회합니다. |
| 공개 웹 보완 조사 | 요청한 학원 과목·학년·수업 형태, 의료기관 진료과 등을 별도 조사합니다. |
| 이동 경로 | 도보·대중교통 경로를 별도 화면에서 조회합니다. |

기본 분야는 **생활·장보기, 교통·동선, 교육·육아, 건강·의료, 여가·관계, 식사·외식**입니다. 집값과 CCTV는 추가 참고이고 웹 정보·이동 경로는 직선거리 점수와 분리합니다.

## 실행 환경

- Python **3.11 이상**. 기존 검증 환경은 Windows / Python 3.13.3입니다.
- OpenAI API 키와 모델 권한. 기본 모델은 `gpt-6.1-sol`, 추론 강도는 `medium`입니다.
- 지도·주소 검색: 카카오 Maps JavaScript 키와 접속 주소의 도메인 등록.
- 별도 경로: 해당 API 권한이 있는 카카오 REST API 키.
- 데이터 다운로드·AI·지도·웹 조사: 인터넷 연결.

API 호출은 API 계정의 사용량으로 과금됩니다. ChatGPT/Codex 로그인과 API 키는 별도 연결 방식입니다. 지원하지 않는 모델·도구·설정은 오류로 표시하며 다른 연결 방식이나 모델로 자동 전환하지 않습니다.

## 빠른 시작

아래는 Windows PowerShell 기준입니다. macOS/Linux에서는 가상환경 활성화를 `source .venv/bin/activate`, 파일 복사를 `cp .env.example .env`로 바꿉니다.

### 1. 설치

```powershell
git clone https://github.com/HosooJeong/oh-my-home.git
cd oh-my-home
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

PowerShell 실행 정책 때문에 활성화가 막히면 정책을 변경하는 대신 `.\.venv\Scripts\python.exe`를 아래 명령의 `python` 대신 사용할 수 있습니다.

### 2. 키와 모델 설정

`.env`를 열어 본인 키를 입력합니다. 화면에서 등록하려면 `OPENAI_API_KEY`는 비워 두고 앱의 **AI 설정**을 사용합니다.

```dotenv
SALJARI_LLM_PROVIDER=openai
SALJARI_LLM_MODEL=gpt-6.1-sol
SALJARI_LLM_EFFORT=medium
OPENAI_API_KEY=
KAKAO_MAP_JAVASCRIPT_KEY=
KAKAO_MAP_REST_API_KEY=
```

카카오 웹 도메인에 `http://localhost:5173`을 등록합니다. 다른 장치에서는 실제 접속 주소도 등록해야 합니다. JavaScript 키는 지도 표시를 위해 브라우저에 제공되고 REST/OpenAI 키는 서버에서 사용합니다. `.env`는 Git에서 제외됩니다.

서버 설정 우선순위는 **프로세스 환경변수 → env 파일 → 앱 기본값**입니다. CLI의 명시적 AI 옵션은 이 값보다 우선합니다. 화면 설정은 해당 세션의 다음 요청부터 적용합니다. [AI 연결·키 관리 안내](docs/llm-settings.md).

### 3. 기본 데이터 준비

Git에는 원본·전체 정규화 자료를 포함하지 않습니다. 새 clone은 다음 두 명령을 먼저 실행합니다. 전국 상가 파일은 대용량이므로 다운로드에 시간이 걸릴 수 있습니다.

```powershell
python -X utf8 tools/fetch_public_data.py
python -X utf8 tools/build_samples.py
```

`data/processed/inventory.json`이 생성되면 기본 시설 조회를 시작할 수 있습니다. **주소 없는 탐색에는 경계·후보 풀이, 학교·학원과 공원·도서관에는 추가 파일이 필요합니다.** [기능별 데이터 준비](docs/data-setup.md)를 참고하세요. 자료 누락을 시설 없음이나 조건 충족으로 처리하지 않습니다.

### 4. 앱 실행

```powershell
python -B -X utf8 -m app.web --env-file .env
```

[http://localhost:5173](http://localhost:5173)에서 시작합니다. 기본 바인딩은 `0.0.0.0:5173`입니다. 같은 로컬/Tailscale 네트워크에서도 접속할 수 있습니다. 다른 포트는 `--port 5174`로 지정하고 지도 도메인도 맞춥니다.

| 화면 | 주소 |
| --- | --- |
| 시작·후보 확정·블록 배치 | `/` |
| AI 연결·키·모델 설정 | `/settings` |
| 조건 승인·분석·결과 | `/analysis` |
| 상세 조건 편집 | `/workspace` |
| 별도 이동 경로 | `/routes` |
| 공공자료 지도 표본 | `/samples` |

## 사용 흐름

1. **주소 없는 탐색 / 집 한 곳 / 여러 집**을 선택합니다. 집을 정했다면 지도·주소 검색 또는 좌표로 위치를 먼저 확정합니다.
2. 분야 블록을 배치하고 생활 선호를 입력합니다. 블록 거리는 중요도이며 지리적 거리가 아닙니다.
3. AI가 정리한 조건과 필요한 인터뷰를 확인하고 기준을 승인합니다.
4. 같은 후보의 공공자료 분석과 요청한 공개 웹 조사를 진행합니다.
5. 분야별 이유·시설·출처·미확인을 확인합니다. 근거가 부족하면 전체 순위를 보류합니다.
6. 중요도만 바꾸면 같은 근거로 재계산하고 위치·기준을 바꾸면 다시 분석합니다.

## AI 연결

서버는 `https://api.openai.com/v1/responses`를 호출합니다. 조건 해석·인터뷰·보완 조사·별도 의미 검토에는 같은 작업 설정을 사용하고 구조화 출력과 로컬 검사를 함께 적용합니다. 검색은 조사 요청에만 허용합니다.

화면에서 **AI 설정 → API 키 입력 → 모델/추론 강도 확인 → 적용** 순서로 등록합니다. **모델 불러오기**는 해당 계정의 모델 목록을 조회하는 API 요청입니다. 목록에 있어도 웹 검색·구조화 출력 지원을 보장하지는 않습니다.

Codex는 선택 옵션입니다. 화면에서 직접 선택하거나 `.env`에 `SALJARI_LLM_PROVIDER=codex`를 지정하고 Codex CLI에 로그인합니다. API 실패를 Codex로 자동 대체하지 않습니다. [설정 상세](docs/llm-settings.md).

## 검사와 명령행 사용

```powershell
python -X utf8 examples/p0_demo.py
python -X utf8 -m unittest discover -s tests -v
```

예제는 합성 자료이며 자동 검사는 모의 모델/HTTP 응답을 사용합니다. 실제 API 성공과 구분합니다. 실제 데이터 대조 검사는 해당 파일을 준비한 환경에서 실행합니다. Node.js가 있으면 `node --test tests/*.test.mjs`로 프런트엔드 검사도 실행할 수 있습니다. 앱 실행에는 Node.js가 필요하지 않습니다.

CLI 니즈 정리도 같은 API 기본값을 사용합니다. 다음 명령은 실제 API 사용량을 발생시킵니다.

```powershell
python -X utf8 -m app intake --env-file .env --request-file examples/intake-request.txt --output work/profile-1.json
```

[코어·CLI 안내](app/README.md)에서 인터뷰 이어가기, JSON Schema, 모델 없는 중요도 수정을 확인할 수 있습니다.

## 구성

```text
app/
  web.py                 서버·세션·작업 상태
  llm_settings.py         연결·모델·키 설정
  openai_runner.py        기본 Responses API 어댑터
  codex_runner.py         선택적 Codex CLI 어댑터
  intake.py              조건·인터뷰 정리
  orchestrator.py         같은 후보의 분야 분석 통합
  evaluation.py          충족도·가중치·미확인 평가
  modules/               분야별 공공자료 조회
  static/                Three.js·지도·결과·설정
data/reference/          출처·스냅샷·경계
docs/                    기능·설정·데이터 안내
tools/                   공식 자료 수집·정규화
tests/                   Python·JavaScript 검사
examples/                합성 평가·니즈 예제
```

LLM은 조건과 공개 웹 정보를 해석하고 Python은 공공자료 조회와 수치 평가를 수행합니다. 선택한 모듈을 순차 실행해 동일 후보·조건 버전으로 합칩니다. [분석 흐름](docs/analysis-flow.md), [여섯 분야](docs/six-category-access.md), [원문 검사](docs/response-validation.md).

## 운영 범위

- 로컬·같은 네트워크용 시제품입니다. 공개 서비스의 사용자 인증·HTTPS·운영 기능은 포함하지 않습니다.
- 세션과 화면에 입력한 API 키는 서버 메모리에 보관합니다. 약1시간 미사용 또는 서버 종료 시 소멸합니다. 파일/환경변수의 기본 키는 새 세션에 다시 적용됩니다.
- 키를 공개 응답·브라우저 저장소·일반 로그에 넣지 않습니다. 테스트 대화 기록은 기본 꺼짐이고, 개인 입력이 포함될 수 있어 별도 로컬 경로에서 관리합니다.
- 지도·주소·경로의 원시 응답은 LLM/분석 근거 저장소로 보내지 않습니다. OpenAI에는 조건 해석·조사에 필요한 입력을 전송합니다.
- 등록 거리와 현재 영업·진료 수준·학교 배정·통학 안전·매물 여부를 구분합니다. 탐색 지점은 실제 집이나 거주 가능성이 확인된 매물이 아닙니다.
- 자료 시점과 결측·오래된 행을 보존하고 미지원은 미확인으로 남깁니다. 사용자 만족도·시간 절감 효과는 아직 측정하지 않았습니다.

## 문제 해결

| 증상 | 확인할 사항 |
| --- | --- |
| `inventory.json` 없음 | 기본 수집·정규화 두 명령을 먼저 실행합니다. |
| API 키 미등록 | AI 설정 또는 `.env`에 본인 키를 등록합니다. |
| 인증·한도·모델 오류 | API 프로젝트 권한·결제/한도·모델 ID·추론 강도를 확인합니다. |
| 지도·주소 검색 실패 | JavaScript 키·실제 접속 도메인을 확인합니다. 좌표 입력도 사용할 수 있습니다. |
| 경로 조회 실패 | REST 키·해당 API 권한·쿼터를 확인합니다. 지도 성공과 별도입니다. |
| 탐색·학교·공원 미확인 | [추가 데이터](docs/data-setup.md)를 준비합니다. |
| 서버 설정 미적용 | 프로세스 환경변수의 우선순위를 확인하고 서버를 재시작합니다. 화면 설정은 해당 세션만 적용됩니다. |

## 출처와 라이선스

제공처·시점·SHA-256은 `data/reference/`와 수집 manifest에 남깁니다. 주요 원천은 [공공데이터포털](https://www.data.go.kr/), [NEIS](https://open.neis.go.kr/), [국토교통부 실거래가](https://rt.molit.go.kr/), [카카오 Maps](https://apis.map.kakao.com/web/)입니다. 자료별 이용조건과 재배포 범위를 구분합니다.

외부 의존성과 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다. 프로젝트 자체 코드에는 별도 LICENSE 파일이 아직 지정되어 있지 않습니다. 외부 라이브러리의 MIT/OFL 고지가 프로젝트 전체에 적용되지는 않습니다.

API 안내는 [OpenAI 빠른 시작](https://developers.openai.com/api/docs/quickstart), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [웹 검색](https://developers.openai.com/api/docs/guides/tools-web-search)을 참고합니다. 유효 키·계정 권한의 실호출은 각 환경에서 확인해야 합니다.
