# P0 Python dependencies

2026-09-30 설치된 배포 메타데이터와 LICENSE로 버전/라이선스를 확인했다. 직접 사용하는 라이브러리는 Pydantic이고 나머지는 해당 런타임의 의존성이다. 검증한 버전을 `requirements.txt`에 함께 고정했다. 외부 패키지 소스를 수정하거나 저장소 안에 복사하지 않았다.

| Package | Version | License | Upstream |
|---|---|---|---|
| pydantic | 2.12.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic_core | 2.41.5 | MIT | https://github.com/pydantic/pydantic-core |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |

패키지를 설치하거나 함께 배포할 때 해당 배포본의 LICENSE/저작권 고지를 유지한다. 이 표는 원본 라이선스를 대체하지 않는다. 기존 카카오 SDK와 공공데이터 출처는 루트 README 및 data/README.md에 따로 기록했다.
