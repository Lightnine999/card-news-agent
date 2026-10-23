# 제출 자료

"사용자와 함께 만드는 카드뉴스 에이전트" 구현 결과예요. 기준 시점은 2026-10-23, 구현 3단계까지(실제 조사 연결)예요.

| 항목 | 위치 |
|---|---|
| 실행법 | [../README.md](../README.md) |
| 요구사항(PRD) | [../PRD.md](../PRD.md) |
| 결정 기록 | [../DECISIONS.md](../DECISIONS.md) |
| API 명세 | [../API_SPEC.md](../API_SPEC.md) |
| 화면 흐름 | [../SCREEN_FLOW.md](../SCREEN_FLOW.md) |
| 화면 캡처 | [screens/](screens/) |
| 결과 파일 | [results/](results/) |
| 검증 기록 (수용 조건별 상태, 테스트, 실패 사례와 수정) | [VERIFICATION.md](VERIFICATION.md) |
| 상황 재현 검증 (5가지 상황, 기대·실제·수정 후 결과) | [../VALIDATION.md](../VALIDATION.md) |
| 커밋 전 개인정보·비밀값 점검 | [COMMIT_REVIEW.md](COMMIT_REVIEW.md) |

## 화면 캡처

| 파일 | 내용 | 데이터 |
|---|---|---|
| `01-home.png` | 시작 화면: 주제 입력, 도구 상태, 이전 프로젝트 | 실제 |
| `02-real-candidates.png` | 후보 선택: 기준 시각·기간, 출처 종류, "출처 미확인" 배지 | 실제 (기간 거르기 넣기 전 조사) |
| `03-real-storyboard.png` | 조사 기록, 편집 제안, 스토리보드 6장 | 실제 |
| `04-mock-question.png` | 독자 질문 상자(추천은 표시만, 미리 선택 안 함) | 모의 |
| `05-mock-excluded.png` | 조사 기간 밖 후보를 뺀 안내 | 모의 |
| `06-mock-error-card.png` | 스토리보드 승인 → 제작 미연결 오류 카드 | 모의 |

"모의"는 실제 검색 없이 모의 엔진으로 만든 화면이에요. 화면 위에 노란 "모의 데이터" 띠가 있어요.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/research-prj_137e35bf7e7b.json` | 실제 조사 → 심층 조사 → 스토리보드까지 간 프로젝트의 API 응답 (후보 7개, 조사 기록 2개, 스토리보드 6장) |
| `results/research-prj_ba7c431b0193.json` | 출처 열어 봄 표시를 켠 뒤 실제 조사한 프로젝트의 API 응답 (후보 6개) |
| 카드 PNG·ZIP·출처 기록·이미지 사용 기록 | **아직 없음** — 이미지 제작·카드 렌더링·내보내기(구현 4~5단계) 후 추가해요 |

결과 JSON의 엔진 세션 ID는 지웠어요.
