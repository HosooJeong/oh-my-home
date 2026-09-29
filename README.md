# oh-my-home

살자리: 개인의 생활맥락을 이해하는 주거 의사결정 AI Agent.

현재는 **진주 공공데이터 수집·품질 점검·카카오 지도 표본 화면**을 구현했다. 주거 추천, GPT 연결, 시간대별 경로 비교는 아직 구현하지 않았다. Python 표준 라이브러리와 정적 HTML/JavaScript를 사용하며 최종 제품 프레임워크를 확정한 것은 아니다.

## 실행

Python 3.11 이상이 필요하다. 아래 명령은 저장소 루트에서 실행한다.

1. 공식 원본을 내려받는다. 상가 전국 ZIP은 확인 당시 약 353 MB다.

~~~powershell
python tools/fetch_public_data.py
~~~

2. 진주 행을 선별하고 품질 결과와 지도 표본을 만든다.

~~~powershell
python tools/build_samples.py
~~~

3. .env.example을 .env로 복사하고 카카오 **JavaScript** 키를 설정한다. 허용 도메인에 http://localhost:5173 을 등록한 뒤 실행한다.

~~~powershell
python tools/preview/server.py
~~~

http://localhost:5173 에서 연다. 기본 바인딩은 0.0.0.0이다. 다른 장치 접속은 해당 주소의 카카오 SDK 도메인 설정과 별도 확인이 필요하다.

기존 AIcontest 작업공간의 원본과 키를 재사용할 때:

~~~powershell
python tools/fetch_public_data.py --raw-dir ../work/dataset-samples-20260929/raw --reuse
python tools/build_samples.py --raw-dir ../work/dataset-samples-20260929/raw
python tools/preview/server.py --env-file ../work/map-api-setup/.env
~~~

--reuse는 기존 파일 재사용을 manifest에 명시한다. 새 자료를 확인할 때는 새로운 raw 폴더로 내려받아 비교한다. 원본 파일·정규화 전체 자료·키는 Git에서 제외한다.

## 생성 파일

- raw/manifest.json: 제공처·버전·공식 다운로드 URL·조회 시각·파일 크기·SHA-256
- processed/inventory.json: 진주에서 좌표 범위 검사를 통과한 행
- processed/quarantine.json: 좌표 오류 의심 행과 수정하지 않은 원문
- processed/quality.json: 진주 행 수·좌표·주소·중복·자료 시점 점검
- processed/preview.json: 충무공동·가호동·평거동 주변의 27개 지도 표본

기본 위치는 data/ 아래이며 경로를 인자로 바꿀 수 있다. 지도 화면은 지역 전환, 유형 필터, 목록/마커 선택, 원문 출처와 자료 시점 표시를 지원한다. 카카오 Local/REST API나 GPT에 장소 자료를 보내지 않는다.

## 2026-09-29 확인 결과

| 자료 | 진주 행 | 좌표 범위 통과 | 별도 보관 | 자료 시점 |
|---|---:|---:|---:|---|
| 상가 | 19,577 | 19,577 | 0 | 2026-06-30 분기 자료 |
| 버스정류장 | 1,968 | 1,968 | 0 | 2025-10-31 정보수집일 |
| CCTV | 5,531 | 5,528 | 3 | 2026-09-16 공개본 수정일 |

CCTV 3행은 위도 32.216844로 진주 주변 범위를 벗어나므로 제외했다. 35도로 임의 보정하지 않는다. 나머지 CCTV 행에는 완전히 같은 내용의 추가 행 1,314개가 있지만, 여러 카메라 표현 여부가 불명확하므로 원본·정규화 자료에서 삭제하지 않는다. 지도 표본에서만 같은 좌표 중복을 피한다.

좌표 검사는 넓은 주변 범위(위도 34.9~35.5, 경도 127.8~128.5)의 이상값 탐지다. 정확한 행정경계 포함·각 지번의 위치 정확성·현재 영업·버스 운행·CCTV 작동 검증은 아니다. 별도 행정경계 자료를 사용하지 않았다. 위도/경도를 Kakao LatLng에 그대로 표시해 비교하며 원본의 지리 기준계 명세 전체는 미확인이다.

상가 자료의 분기와 표본 기준 상가 ID는 이번 검증 버전에 고정했다. 다음 분기 자료로 바뀌면 자동 추정하지 않고 build_samples.py가 재검토를 요구한다. 기준 상가는 지리적 표본 선택용이며 추천 매장이나 주택 후보가 아니다.

## 검증

~~~powershell
python -m unittest discover -s tests -v
~~~

6개 검사는 좌표 오류/NaN/빈 값, 원본 보존, 지역 필터, 표본 거리 제한, 실제 표본과 정규화 원본의 일치를 확인한다. 원본 기반 검사는 processed 자료 생성 후 실행한다.

실제 브라우저에서 3개 지역·종류별 표본·필터·목록/마커 선택·빈 필터·로드 실패/복구·390/820/1440px 화면을 확인했다. 지도 SDK 내부 부동소수점 변환을 고려해 원본과 마커 좌표 비교 허용 오차는 1e-9도다. 개발 데이터 표본 검증이며 Agent E2E 또는 실제 휴대폰 검증은 아니다.

## 출처

- [소상공인시장진흥공단 상가(상권)정보](https://www.data.go.kr/data/15083033/fileData.do)
- [국토교통부 전국 버스정류장 위치정보](https://www.data.go.kr/data/15067528/fileData.do)
- [경상남도 진주시 CCTV위치정보](https://www.data.go.kr/data/15143299/fileData.do)
- [카카오 지도 JavaScript SDK](https://apis.map.kakao.com/web/)

세 공공파일은 확인 시점에 이용허락범위 제한 없음으로 표시됐다. 카카오 지도 표시와 공공파일의 출처를 구분하고 지도 저작권 표시를 유지한다. API 일반 인증키 없이 공식 파일 다운로드 경로로 확보했다.

버스 자료 페이지의 JSON-LD contentUrl에서 PNG가 내려오는 불일치를 발견해 다운로드 버튼의 공식 파일 선택 경로를 사용했다. 수집기는 ZIP/CSV의 실제 형식·필수 좌표 헤더와 전송 크기를 확인한다.
