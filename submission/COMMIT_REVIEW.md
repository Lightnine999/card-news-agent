# 커밋 전 점검 (2026-10-23)

대상: `card-news-workflow-kit/` 폴더(아직 저장소에 하나도 올라가 있지 않음)
저장소: `Lightnine999/aiffel_work` — **공개(PUBLIC)**
커밋 작성자·커미터 이메일: GitHub noreply 주소 — 개인 이메일 노출 없음

## 정한 것 (사용자 결정)
- 앱 코드는 그대로 올리고, 제출 자료는 `submission/`에 모아요.
- 제출 자료 범위: README · PRD · DECISIONS · API_SPEC · 화면과 결과 파일 · 검증 기록.
- 화면과 결과 파일은 지금 있는 것으로 채우고, 아직 없는 카드 PNG·ZIP은 "아직 없음"으로 적어요.
- 그 밖의 강의 키트 원본과 이 컴퓨터 전용 설정은 `.gitignore`로 빼요.

## 빠지는 것 (.gitignore)
| 대상 | 이유 |
|---|---|
| `data/` (DB·조사 기록·엔진 로그) | 실행 데이터 |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.omc/` | 실행 환경·도구 상태 |
| `.claude/launch.json` | 이 컴퓨터의 사용자 경로와 세션 ID가 들어 있어요 |
| 따라하기 HTML, `ACCEPTANCE.md`, `ENGINE_GUIDE.md`, `EXAMPLE_RUN.md`, `REFERENCES.md`, `assets/` | 강의 키트 원본. 공개 저장소 게시 여부 확인 전 |

## 최종 검사 결과 (커밋 대상 55개, 약 1.3MB)
| 검사 | 결과 |
|---|---|
| API 키·토큰·비밀번호·개인 키 모양 | 없음 |
| 이메일 주소 | 없음 |
| 내 컴퓨터 경로·계정 이름 | 없음 (이 문서의 저장소 이름·검사 패턴 설명만 걸림) |
| 전화번호·주민번호 모양 | 없음 (uv.lock의 패키지 해시 오탐 제외) |
| 세션·대화 ID | 테스트의 가짜 ID만 있어요. 결과 JSON의 엔진 세션 ID는 지웠어요. DECISIONS.md에 Claude 세션 ID 앞 8자리(`33593ea1…`)가 남아 있어요 — 이 컴퓨터의 대화 기록을 가리키는 값이라 남이 쓸 수 없어요 |
| 화면 캡처 6장 | 직접 열어 봤어요. 앱 화면과 공개 뉴스 내용뿐이에요. 이미지 메타데이터에 경로·계정 없음 |

## 검사 방법
- 대상 목록: `git ls-files --others --exclude-standard` (.gitignore 적용 후)
- 패턴: `sk-…`, `sk-ant-…`, `AKIA…`, `ghp_…`, `xox…`, `AIza…`, 개인 키 머리말, `Bearer …`, `api_key/secret/password/token = "…"`, 이메일, 사용자 폴더 경로·계정 이름·임시 폴더 이름, 전화번호·주민번호, UUID
- 한계: 문자열 패턴 검사라 모양이 다른 비밀값은 못 잡아요. 강의 자료를 공개해도 되는지는 검사로 알 수 없어요.
