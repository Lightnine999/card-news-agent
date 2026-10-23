# 카드뉴스 워크플로 제작 키트

## 앱 실행하기 (구현 3단계: 실제 조사 연결)

주제를 넣으면 **Claude CLI가 실제로 웹을 검색**해요(sonnet, effort medium). 이미지 제작(agy)과 카드 렌더링은 다음 단계에서 연결해요.

필요한 것:
- [uv](https://docs.astral.sh/uv/) (Python 3.12 이상은 uv가 알아서 준비해요)
- Claude Code CLI(`claude`)에 로그인돼 있어야 해요. 터미널에서 `claude`를 한 번 실행해 확인해 주세요.
- 조사 한 번에 Claude 사용량이 들어요(시험 때 CLI가 알려 준 추정: 조사·심층 조사·수정 합쳐 약 $1.5).

```bash
uv sync
```

```bash
uv run cardnews
```

브라우저에서 http://127.0.0.1:8765 를 열어요. 8765 포트를 이미 쓰고 있으면 실행이 멈추고 다른 포트를 안내해요.

```bash
uv run cardnews --port 8766
```

### 지금 해 볼 수 있는 것
1. 주제 입력 → 실제 검색어가 진행 화면에 보여요 → 후보 7~12개 (조사 기준 시각·기간 표시, 1분 안팎)
2. 후보 1~3개 체크 (새로고침해도 남아요) → 다음 단계
3. 심층 조사 → 독자·방향이 갈릴 때만 질문해요. 판단할 수 있으면 추천 이유와 함께 편집 제안·스토리보드로 바로 가요.
4. 스토리보드 변경 요청 또는 승인. 승인하면 "이미지 제작은 아직 연결하지 않았어요" 오류 카드가 떠요(일부러 성공한 척하지 않아요).

사용량 없이 화면만 보려면 모의 엔진으로 실행해요. 화면 위에 노란 "모의 데이터" 띠가 보여요.

```bash
CARDNEWS_ENGINE=mock uv run cardnews
```

모의 엔진에서 다른 경우를 보려면 주제에 이 말을 넣어요.
- `적음` → 후보 3개만 나와서 "30일로 넓힐까요?" 질문
- `실패` → 검색 실패 오류 카드와 재시도
- `기간밖` → 조사 기간보다 오래된 후보가 섞여서, 앱이 빼고 "조사 기간 밖 후보 1개를 뺐어요"를 보여 줘요

### 테스트

```bash
uv run pytest
```

### 파일 구성
- `cardnews/app.py` 웹 API · `service.py` 요청 규칙 · `pipeline.py` 엔진 결과 반영 · `worker.py` 작업 프로세스
- `cardnews/engines/` 엔진 연결: `claude_cli.py`(실행), `claude_prompts.py`(지시문), `claude_schema.py`(결과 형식·거르기), `mock.py`
- `static/` 화면 (빌드 단계 없는 HTML/JS)
- `data/` 실행 데이터. 커밋하지 않아요(.gitignore).
- 설계 문서: `DECISIONS.md`(결정 기록), `API_SPEC.md`, `SCREEN_FLOW.md`, `DESIGN.md`

---

이 자료는 원래 완성 앱이 아니라, 코딩 AI와 앱을 만들기 위한 PRD와 검수 자료입니다. 아래는 키트 원래 안내예요.

> 키트에 있던 ACCEPTANCE.md·REFERENCES.md·ENGINE_GUIDE.md·EXAMPLE_RUN.md와 따라하기 HTML·배경 이미지는 공개 저장소에 올리지 않았어요(강의 자료 게시 여부 확인 전). 수용 조건별 확인 상태는 [submission/VERIFICATION.md](submission/VERIFICATION.md)에 있어요.

1. 압축을 풀고 폴더를 Claude Code 또는 OpenCode로 엽니다.
2. 아래 요청을 입력하고 AI의 질문에 답합니다.

> PRD.md를 읽고 카드뉴스 에이전트를 만들어 줘. 미정인 부분은 먼저 물어보고, 브라우저에서 후보를 고르고 질문에 답하는 흐름부터 보여 줘.

3. AI가 작성한 README에 따라 실행하고 안내받은 로컬 주소를 엽니다. 이 키트에는 실행 서버가 아직 없으므로 공통 실행 명령은 없습니다.
4. `AI 최신소식`을 입력하고 ACCEPTANCE.md를 확인합니다.
5. 만든 흐름을 자신의 주제로 바꾸고 달라져야 할 판단·도구·검수 조건을 PRD에 반영합니다.

실행 엔진은 Claude Agent SDK, Claude CLI, OpenCode CLI 중 하나로 시작합니다. 이미지 생성에는 공식 Antigravity CLI `agy`를 사용합니다. 설치되어 있다는 것과 실제 로그인·검색·이미지 생성 권한이 있다는 것은 다릅니다. 사용할 계정에서 각 기능을 확인하세요.

공식 사용법과 카드 형식 레퍼런스는 REFERENCES.md를 참고하세요.
