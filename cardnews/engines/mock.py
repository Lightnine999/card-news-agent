"""모의 엔진. 화면 흐름을 먼저 만들 때만 써요 (PRD 구현 순서 2).

여기서 나오는 후보·조사 기록·스토리보드는 실제 검색 결과가 아니에요.
프로젝트에는 isMock=true가 붙고 화면에 "모의 데이터" 띠가 보여요.

주제에 넣는 말로 다른 경우를 시험할 수 있어요:
- "적음": 후보 3개만 돌려줘요 → 30일 확장 질문
- "실패": 검색 실패(SEARCH_FAILED)
- "기간밖": 조사 기간보다 오래된 후보 1개를 더 넣어요 → 앱이 빼고 화면에 이유를 보여 줘요
"""

import time
from datetime import datetime, timedelta

from cardnews import config
from cardnews.engines.base import EngineEvent, RunContext

_SAMPLES = [
    ("모델", "새 언어 모델 공개", "released", "official", 2),
    ("제품", "업무용 AI 비서에 새 기능 추가", "released", "press", 3),
    ("연구", "추론 효율을 높인 논문 발표", "released", "paper", 4),
    ("개발 도구", "코딩 에이전트 CLI 업데이트", "released", "official", 1),
    ("정책", "AI 안전 가이드라인 초안 공개", "announced", "official", 5),
    ("제품", "이미지 생성 기능 출시 예정 발표", "announced", "press", None),
    ("모델", "오픈 가중치 모델 성능 주장", "claimed", "blog", 6),
    ("개발 도구", "에이전트 평가 도구 오픈소스 공개", "released", "official", 2),
]

_AUDIENCE = {
    "general": ("일반 사용자", "용어 설명을 늘리고 생활 속 쓰임을 중심으로"),
    "dev": ("개발자", "API·도구 변화와 바로 해 볼 일을 중심으로"),
    "edu": ("교육자", "수업에 쓸 수 있는 사례와 주의점을 중심으로"),
}


def _pause(ctx: RunContext, message: str) -> None:
    ctx.check_cancel()
    ctx.report(message)
    time.sleep(config.mock_delay())
    ctx.check_cancel()


def _candidate(index: int, sample: tuple, requested_at: datetime) -> dict:
    category, title, status, source_type, days_ago = sample
    date = None if days_ago is None else (requested_at - timedelta(days=days_ago)).date()
    sources = [{"url": f"https://example.com/mock/{index}", "name": f"모의 출처 {index}",
                "type": source_type}]
    if index == 1:  # 같은 발표를 다룬 기사 묶음 예시
        sources += [{"url": f"https://example.com/mock/{index}-{n}", "name": f"모의 언론 {n}",
                     "type": "press"} for n in (2, 3)]
    return {
        "id": f"cand_{index}",
        "title": f"[모의] {title}",
        "summary": "모의 데이터예요. 실제 검색 결과가 아니에요. 화면 흐름 확인용 요약 문장이에요.",
        "category": category,
        "publishedAt": date.isoformat() if date else None,
        "eventDate": date.isoformat() if date and index % 2 else None,
        "dateStatus": "unverified" if date is None else (
            "confirmed" if index % 2 else "published_only"),
        "sources": sources,
        "whyPick": "독자가 바로 써 볼 수 있는 변화예요." if status == "released"
        else "앞으로의 방향을 보여 주는 소식이에요.",
        "uncertainty": {"released": "사용 가능한 지역·요금제 조건은 아직 확인 전이에요.",
                        "announced": "발표만 됐고 실제 출시일은 정해지지 않았어요.",
                        "claimed": "업체 주장이고 독립 검증은 없어요."}[status],
        "status": status,
    }


def _research(ctx: RunContext, task: dict) -> EngineEvent:
    topic = task["topic"]
    _pause(ctx, f"'{topic}' 관련 검색어 4개로 찾는 중")
    if "실패" in topic:
        return EngineEvent(type="error", error_code="SEARCH_FAILED",
                           error_message="모의 검색 실패예요. 다시 시도해 보세요.")
    _pause(ctx, "같은 발표를 다룬 기사 묶는 중")
    requested_at = datetime.fromisoformat(task["requestedAt"])
    count = 3 if "적음" in topic and task["periodDays"] == 7 else len(_SAMPLES)
    samples = list(_SAMPLES[:count])
    if "기간밖" in topic:
        samples.append(("모델", "지난달 발표된 모델 소개 글", "released", "press", task["periodDays"] + 5))
    candidates = [_candidate(i + 1, s, requested_at) for i, s in enumerate(samples)]
    return EngineEvent(type="result", data={"candidates": candidates},
                       session_id=ctx.session_id or f"mock-{ctx.project_id}")


def _note(candidate: dict) -> dict:
    url = candidate["sources"][0]["url"]
    return {
        "candidateId": candidate["id"],
        "facts": [{"text": f"{candidate['title']}: 모의 사실 문장이에요.", "sourceUrls": [url]}],
        "limits": [candidate["uncertainty"]],
        "conflicts": [],
        "primarySources": [url],
        "unreachable": [],
    }


def _audience_question() -> dict:
    return {
        "id": "q_audience",
        "prompt": "어떤 독자에게 전달할까요?",
        "multiSelect": False,
        "options": [{"id": k, "label": v[0], "description": v[1]} for k, v in _AUDIENCE.items()],
        "allowFreeText": True,
        "recommendedOptionId": "dev",
        "recommendationReason": "고른 소식에 개발 도구 변화가 많아서요. (모의 추천)",
    }


def _deep_research(ctx: RunContext, task: dict) -> EngineEvent:
    notes = []
    for cand in task["candidates"]:
        _pause(ctx, f"원문 확인 중: {cand['title']}")
        notes.append(_note(cand))
    _pause(ctx, "독자와 편집 방향 판단 중")
    return EngineEvent(type="need_input", question=_audience_question(),
                       partial={"researchNotes": notes},
                       session_id=ctx.session_id or f"mock-{ctx.project_id}")


def _storyboard_cards(audience: str, candidates: list[dict], note: str = "") -> list[dict]:
    urls = [c["sources"][0]["url"] for c in candidates] or [None]
    plan = [
        ("cover", f"{audience}를 위한 이번 주 AI 소식{note}", "지금 알아 둘 변화 한눈에"),
        ("body", "무엇이 달라졌나", "핵심 변화 한 가지"),
        ("body", "어디에 쓸 수 있나", "바로 해 볼 수 있는 쓰임"),
        ("body", "조건과 한계", "아직 확인하지 못한 것"),
        ("body", "발표만 된 것", "출시와 발표를 구분해요"),
        ("summary", "요약과 출처", "세 줄 요약과 원문 링크"),
    ]
    return [
        {
            "id": f"card_{i + 1}", "order": i + 1, "role": role, "title": title,
            "keyLine": key, "sourceUrls": [urls[i % len(urls)]] if urls[0] else [],
            "imagePlan": {"kind": "generated", "textArea": "top",
                          "prompt": "짙은 남색 추상 기술 배경, 위쪽 40% 비움, 글자·로고 없음"},
        }
        for i, (role, title, key) in enumerate(plan)
    ]


def _editorial_and_storyboard(task: dict, audience: str) -> dict:
    return {
        "editorial": {
            "audience": audience,
            "whyUseful": f"{audience}가 이번 주 변화를 5분 안에 파악할 수 있어요. (모의)",
            "format": "핵심 요약형",
            "hooks": ["[모의] 이번 주 꼭 알아 둘 AI 변화 3가지",
                      "[모의] 발표와 출시, 무엇이 진짜 바뀌었나",
                      "[모의] 오늘 바로 써 볼 수 있는 것만 골랐어요"],
            "decidedBy": "user_answer",
        },
        "cards": _storyboard_cards(audience, task["candidates"]),
    }


class MockEngine:
    name = "mock"

    def start(self, ctx: RunContext, task: dict) -> EngineEvent:
        kind = task["kind"]
        if kind == "research":
            return _research(ctx, task)
        if kind == "deep_research":
            return _deep_research(ctx, task)
        if kind == "storyboard":
            _pause(ctx, "변경 요청 반영 중")
            cards = _storyboard_cards(task["editorial"]["audience"], task["candidates"],
                                      f" (수정: {task['instruction'][:20]})")
            return EngineEvent(type="result", data={"cards": cards})
        return EngineEvent(type="error", error_code="TOOL_UNAVAILABLE",
                           error_message="이미지 제작은 아직 연결하지 않았어요 (구현 4~5단계).")

    def send_answer(self, ctx: RunContext, task: dict, question: dict,
                    answer: dict) -> EngineEvent:
        _pause(ctx, "답변을 반영해서 스토리보드 만드는 중")
        if "freeText" in answer:
            audience = answer["freeText"]
        else:
            audience = _AUDIENCE[answer["optionId"]][0]
        return EngineEvent(type="result", data=_editorial_and_storyboard(task, audience))
