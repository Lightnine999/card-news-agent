# 글자 배치·모바일 미리보기 구현 계획

> 실행 방식: 사용자가 "설치하고 구현을 시작해 주세요"라고 해서 이 세션에서 바로 구현해요(Native). 끝나면 독립 검토 한 번.

**목표:** agy 배경 그림 위에 제목·핵심·본문을 HTML/CSS로 올려 1080×1350 PNG를 만들고, 가독성 점검·자동 고침·직접 조정·휴대폰 미리보기를 붙여요.
**구조:** `cardnews/render/`가 HTML 만들기(html.py)·판정과 자동 고침 규칙(layout.py, 순수 함수)·Chromium 실행(chromium.py)·카드 한 장 렌더링(card.py)을 맡아요. 제작 run이 그림 다음에 바로 렌더링하고, 직접 조정·글자만 다시 올리기는 새 run 종류 `render`예요.
**기술:** Playwright 1.64(Chromium headless shell), Pillow 13, Pretendard 1.3.9 woff2(`static/fonts/`).
**설계:** [2026-10-23-text-render-design.md](2026-10-23-text-render-design.md)

## 전체 제약
- 카드 1080×1350, `deviceScaleFactor=1`. 본문 최소 32px, 대비 4.5:1, 얼룩짐(밝기 표준편차) 28 이상이면 겹침 주의.
- 글자 크기 한 단계 = 8%. 표지: 제목 72·핵심 40. 본문·요약: 제목 64·핵심 44·본문 32. 본문은 32px 밑으로 내리지 않아요.
- 여백 좌우 88px, 위아래 96px. 글자 상자 최대 높이 700px **[AI 기본안]**.
- 글자 색 어둡게 #151515 / 밝게 #f4f2ee. 깔개: 어두운 글자면 흰색 70%, 밝은 글자면 검정 55% 그라디언트.
- 자동 고침은 다시 재기 최대 3번. 사용자가 정한 항목(auto가 아닌 값)은 건드리지 않아요.
- 카드에 출처 줄 없음. 오른쪽 아래 "AI 생성 이미지" 20px(점검 제외, none 배경이면 없음).
- 직접 고치는 문구 제한: 제목 30자, 핵심 60자, 본문 160자.
- PNG `results/cards/card_N.v{cardVersion}.png`, HTML은 옆에 남기고 파일 엔드포인트로 내주지 않아요.

## 검토 초점 (테스트로 묶을 것)
1. 아주 긴 문구 → 자동으로 줄이고, 그래도 넘치면 점검 실패로 남고 PNG는 만들어져요(카드 `done`).
2. 어두운 배경 → 글자 색이 자동으로 밝게.
3. 사용자가 크기를 "크게"로 정했는데 넘침 → 크기는 그대로, 점검 실패 + 안내.
4. 조정 요청은 그 카드만 버전이 오르고 agy를 부르지 않아요. 다른 카드 PNG는 그대로.
5. 렌더러 실패(Chromium 없음) → 카드 `failed`(`RENDER_FAILED`), [이 카드 다시 만들기]는 그림을 다시 만들지 않고 글자만 다시 올려요.

## 작업
1. **판정·자동 고침 규칙** `cardnews/render/layout.py` + `tests/test_render_layout.py`
   - `settings_from(layout, role) -> dict`, `evaluate(measure, settings) -> checks`, `next_fix(checks, settings, layout) -> (settings, message) | None`, `contrast_ratio(a, b) -> float`, `pick_color(mean_luminance) -> 'dark'|'light'`.
2. **HTML·Chromium·카드 렌더링** `html.py`, `chromium.py`, `card.py` + `tests/test_render_chromium.py`(Chromium 없으면 건너뜀)
   - `build_html(texts, settings, bg, role, disclose) -> str`, `Browser`(with 문, `render_card(...) -> record`).
3. **제작 흐름 연결** `production.py`, `service.py`, `pipeline.py`, `app.py`, `views.py`, `config.py` + 흐름 테스트
   - 카드 상태 `rendering`·`done`, 전부 done이면 `reviewing`. `POST .../cards/{cardId}/layout`, `POST .../render`, 렌더 실패 카드 재시도는 글자만.
   - `CARDNEWS_RENDERER=chromium|fake` (테스트는 fake).
4. **검수 화면** `static/views.js`·`app.js`·`style.css`: PNG 격자·점검 배지·하나 보기(원본+360px 휴대폰 틀)·조정 칸.
5. **문서** API_SPEC·SCREEN_FLOW·DECISIONS(D18)·README 설치 안내. 실제 6장으로 확인.
