# 실시간 경로 API 연결

2026-10-02. `/routes`에서 출발지·도착지를 지도에서 선택하고 도보 또는 대중교통 경로를 조회한다. `시청 → 진주역 예시`는 카카오 주소 변환으로 공개 장소를 선택한다. 지도 클릭과 예시 선택만으로 경로를 자동 호출하지 않는다. 조회는 버튼을 누른 때 한 번 실행하고 대중교통 결과는 예상 소요시간 순으로 최대3개를 표시하며 선택하면 지도 경로가 바뀐다. 직접 분석 화면의 기존 직선거리 지표와 후보 순위는 유지한다.

## 설정과 실행

지도 SDK의 JavaScript 키와 경로 조회의 REST API 키는 서로 다르다. `.env.example`의 `KAKAO_MAP_REST_API_KEY`에 기존 카카오 앱의 REST 키를 설정하고 같은 env 파일로 앱을 실행한다. 비밀키를 채팅/화면/저장소에 넣지 않는다. REST 키는 서버가 호출할 때 env 파일에서 읽으며 `/api/config`에는 JavaScript 키만 반환한다.

```powershell
python -B -X utf8 -m app.web --host 0.0.0.0 --port 5173 --env-file ../work/map-api-setup/.env --debug-transcripts
python -B -X utf8 -m tools.check_routes --env-file ../work/map-api-setup/.env
```

확인 도구는 진주시청/진주역 인근 공개 시험 좌표로 도보·대중교통 API를 각각1회 호출하고 성공 여부/경로 개수만 출력한다. 건물 출입구 접근성·사용자 주택/매물 검증은 아니다. 외부 연결 실패는 키 오류와 구분하며 테스트 성공을 계정별 실제 무료 사용량/비용 영수증으로 간주하지 않는다.

## 서버 경계

- `GET /api/routes/status`: 서버 키 설정 여부·지원 이동수단을 반환한다. 키 유효성/상위 API 정상 응답을 확인하는 요청은 아니다.
- `POST /api/routes`: 기존 동일 Origin/Host·세션 검사 뒤 `start/end`의 `latitude/longitude`, `mode`(`walk`/`transit`), `walk_option`(`BROAD_FIRST`/`SHORTEST`/`ACCESSIBLE`)만 받는다. 유한한 국내 좌표·동일 지점/추가 필드 검사를 적용한다.
- Kakao 공식 `https://dapi.kakao.com/v2/routing/walk` 또는 `publictraffic`만 요청한다. 임의 URL/리다이렉트·자동 재시도 없음. 8초 네트워크 timeout·2MB 응답 제한·최대 동시2요청, 서버 전체 분당12/UTC일간100회 제한. 이 제한은 프로세스 메모리 기반이며 재시작 시 초기화되고 제공자 쿼터/결제 한도 설정을 대체하지 않는다.
- 상태 OK·거리/시간 유한수·경로 좌표·환승 등 응답을 검증한다. 경로 없음/좌표 실패·401·403·429·시간초과·네트워크·잘못된 응답을 구분하고 원시 오류/키를 응답하지 않는다. 조회 실패를 거리0/만족도0이나 대체 직선 경로로 만들지 않는다.
- 응답은 실시간 지도 표시 전용이다. 서버 DB/세션/대화 로그/파일/캐시·제품 LLM·기존 comparison/report에는 넣지 않는다. 브라우저도 localStorage/sessionStorage에 경로 응답을 저장하지 않는다. 일반 HTTP 응답은 no-store이며 화면/탭 종료 시 소멸한다.
- 서버 부트스트랩은 기존 디버그 옵션에서 세션 개시 정보만 남길 수 있지만 경로 API의 요청 좌표/응답은 기록하지 않는다.

## 확인한 제공 범위와 후속

카카오 REST 문서(조회일2026-10-02)는 도보 거리/소요시간/단계 경로, 대중교통 거리/소요시간/환승을 제공한다. 도보의 편안한 길 옵션을 장애물 없음/휠체어 접근성/통학로 안전 보장으로 해석하지 않는다. 대중교통 조회는 사용자 출발 시간대를 입력하는 파라미터가 없으며 미래 시간대 통근·실시간 운행 보장을 평가하지 않는다. 횡단 횟수·유동인구·조명·안전성 점수는 이번 연결에 포함하지 않는다.

기존 앱1591975의 카카오맵 ON/무료 쿼터 배지를 실제 콘솔에서 확인했다. 공식 안내상 첫 활성화 앱의 도보/대중교통 무료 쿼터는 각각일간1,000건이며 유료 추가 쿼터 활성화·결제 설정을 변경하지 않았다. API 외부 LLM 전송/가공 허용 조건은 미확인으로 남긴다. 기존 카카오 Local 응답의 외부 LLM 전송 불가를 요약/가공으로 우회하지 않는다. 따라서 현재 CodexRunner에 지도/경로 도구를 열어주는 변경도 하지 않는다. 후속은 허용 범위 확인 후 선호 평가에 쓸 지표·시간대·조회 대상/예산을 정하는 단계다.

출처:

- [카카오 REST API](https://developers.kakao.com/docs/ko/kakaomap/rest-api)
- [카카오맵 활성화·무료 쿼터](https://developers.kakao.com/docs/ko/kakaomap/common)
- [쿼터](https://developers.kakao.com/docs/ko/getting-started/quota)
- [Local 응답 저장/LLM 전송에 대한 공식 답변](https://devtalk.kakao.com/t/api-llm-place-url-webview/151545)
