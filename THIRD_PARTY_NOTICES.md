# Third-party notices

## P0 Python dependencies

2026-09-30 설치된 배포 메타데이터와 LICENSE로 버전/라이선스를 확인했다. 직접 사용하는 라이브러리는 Pydantic이고 나머지는 해당 런타임의 의존성이다. 검증한 버전을 `requirements.txt`에 함께 고정했다. 외부 패키지 소스를 수정하거나 저장소 안에 복사하지 않았다.

| Package | Version | License | Upstream |
|---|---|---|---|
| pydantic | 2.12.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic_core | 2.41.5 | MIT | https://github.com/pydantic/pydantic-core |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |

패키지를 설치하거나 함께 배포할 때 해당 배포본의 LICENSE/저작권 고지를 유지한다. 이 표는 원본 라이선스를 대체하지 않는다. 기존 카카오 SDK와 공공데이터 출처는 루트 README 및 data/README.md에 따로 기록했다.

## Three.js 0.180.0 (r180)

Authors: Three.js authors, copyright 2010–2025. License: MIT; the full notice is preserved in [LICENSE](app/static/vendor/three/LICENSE).

Official source: https://github.com/mrdoob/three.js/tree/r180

Package: https://www.npmjs.com/package/three/v/0.180.0

`build/three.module.min.js`, `build/three.core.min.js` and `LICENSE` were copied unchanged to `app/static/vendor/three/` on 2026-10-01 KST. The installed official package in the local 3DGame workspace was reused after checking package.json version. That project's game code, models, textures and UI were not reused. No global installation or CDN runtime request was added.

| File | SHA-256 |
|---|---|
| three.module.min.js | e2b5ee6bccd38fd6d8a2428546b83c5f2426d84b152ef82be8055556e3b40eb6 |
| three.core.min.js | 61ba0df005b05991361d040d8ff670e1aadfd0ce7aeebd1fdb0725957a8957de |
| LICENSE | bfe119ea4fd413f5f7ca3fcd63adb0c4a073ed39daa2fe7d3e6b769e21272601 |

The house, buildings, trees, benches, bus and people are newly written procedural geometry in `village.mjs`. No branded LEGO asset, logo, downloaded model or generated bitmap is included. The town represents priorities, not actual facilities or geographic coordinates.
