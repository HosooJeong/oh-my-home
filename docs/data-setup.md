# 데이터 준비

Git은 수집·정규화 코드와 `data/reference/`의 메타데이터를 제공합니다. 원본 `data/raw/`와 전체 정규화 `data/processed/`는 제외합니다. 아래 명령은 저장소 루트에서 실행합니다. 공식 응답의 형식·고정 해시가 바뀌면 검토가 필요할 수 있습니다.

## 기본 시설 자료

```powershell
python -X utf8 tools/fetch_public_data.py
python -X utf8 tools/build_samples.py
```

상가·정류장·CCTV 원본과 manifest는 `data/raw/`, 진주 정규화·품질 자료는 `data/processed/`에 생성됩니다. 서버 시작에는 `inventory.json`이 필요합니다. `preview.json`은 지도 표본, `quarantine.json`은 오류 의심 원문입니다. 생활·교통·등록 의료/식사 조회는 기본 inventory를 사용합니다.

## 주소 없는 탐색

```powershell
python -m pip install -r requirements-data.txt
python -X utf8 tools/fetch_boundary.py
python -X utf8 tools/prepare_candidates.py --archive data/raw/boundary/sgis-2025.zip
```

`data/reference/jinju-boundary-2025.geojson`과 `data/processed/candidate-pool.json`을 준비합니다. 풀은 inventory/경계 해시를 검사하므로 inventory 갱신 후 다시 생성해야 합니다. 상가가 있는500m격자의 조사 지점이며 실제 매물이 아닙니다. [생성 규칙](candidate-generation.md). 전처리 의존성은 이미 준비된 파일을 읽는 런타임에는 필요하지 않습니다.

## 학교·학원

```powershell
python -X utf8 tools/fetch_education.py --raw-dir data/raw/education
python -X utf8 -m tools.prepare_education --raw-dir data/raw/education
```

`education.json`을 생성합니다. 학교·NEIS 자료를 사용하고 일부 학원 좌표를 inventory에 연결합니다. inventory가 바뀌면 다시 정규화합니다. [교육 범위](education-accessibility.md).

## 공원·도서관

```powershell
python -X utf8 tools/fetch_leisure.py --raw-dir data/raw/leisure/current
python -X utf8 -m tools.prepare_leisure --raw-dir data/raw/leisure/current
```

`leisure.json`을 생성합니다. 유형·자료 날짜·오래된 행을 보존합니다. [여가 범위](leisure-accessibility.md).

## 집값 참고

아파트 공개 CSV로 `housing.json`을 만들 수 있습니다. 기간과 파일/manifest 검사가 필요하므로 [준비 절차](housing-reference.md#준비-및-갱신)를 따릅니다. 기본 시설 비교에는 필요하지 않으며 개별 후보 가격·예산 충족 판정에 사용하지 않습니다.

## 누락과 갱신

| 없는 파일 | 영향 |
| --- | --- |
| `inventory.json` | 서버 시작 전 기본 자료 준비가 필요합니다. |
| 경계·`candidate-pool.json` | 자동 탐색을 사용할 수 없습니다. 직접 지정 지점 분석은 별도입니다. |
| `education.json` | 학교·학원 등록 근거가 미확인으로 남습니다. |
| `leisure.json` | 공원·도서관 근거가 미확인으로 남습니다. |
| `housing.json` | 집값 참고를 표시하지 않습니다. |

날짜·원본 행·URL·SHA-256을 보존합니다. 수집/정규화 명령은 reference 메타데이터를 갱신할 수 있으므로 diff를 확인하세요. 자료 부재를 시설 없음으로 바꾸지 않습니다.

제공된 소스 ZIP에 일부 processed 자료가 있으면 고정 파일로 먼저 실행할 수 있습니다. Git clone과 ZIP의 포함 범위는 다릅니다. 이용조건은 [data/README.md](../data/README.md)와 분야별 문서를 따릅니다.
