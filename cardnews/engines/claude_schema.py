"""Claude CLI에 요구하는 결과 형식(--json-schema)과, 받은 결과를 앱 데이터로 바꾸는 규칙.

엔진 결과는 믿지 않고 한 번 더 걸러요: 링크는 http(s)만, 날짜는 YYYY-MM-DD만,
ID는 앱이 붙이고, 카드 근거는 조사에 나온 URL만 인정해요.
"""

import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from cardnews.errors import AppError

MAX_CANDIDATES = 12
CARD_RANGE = (3, 10)
QUESTION_ID = re.compile(r"^q_[a-z0-9_]{1,40}$")
SOURCE_RANK = {"official": 0, "paper": 1, "press": 2, "blog": 3, "unknown": 4}


# --- 엔진이 돌려줄 형식 -----------------------------------------------------------


class SourceOut(BaseModel):
    url: str
    name: str
    type: Literal["official", "paper", "press", "blog", "unknown"]


class CandidateOut(BaseModel):
    title: str
    summary: str
    category: str
    publishedAt: str | None
    eventDate: str | None
    sources: list[SourceOut]
    whyPick: str
    uncertainty: str
    status: Literal["released", "announced", "claimed", "unknown"]


class ErrorOut(BaseModel):
    code: Literal["SEARCH_FAILED", "TOOL_UNAVAILABLE"]
    message: str


class ResearchOutput(BaseModel):
    status: Literal["result", "error"]
    candidates: list[CandidateOut] = []
    error: ErrorOut | None = None


class FactOut(BaseModel):
    text: str
    sourceUrls: list[str]


class UnreachableOut(BaseModel):
    url: str
    reason: str


class NoteOut(BaseModel):
    candidateId: str
    facts: list[FactOut]
    limits: list[str]
    conflicts: list[FactOut]
    primarySources: list[str]
    unreachable: list[UnreachableOut]


class OptionOut(BaseModel):
    id: str
    label: str
    description: str


class QuestionOut(BaseModel):
    id: str
    prompt: str
    options: list[OptionOut]
    allowFreeText: bool
    recommendedOptionId: str | None
    recommendationReason: str


class EditorialOut(BaseModel):
    audience: str
    whyUseful: str
    format: str
    hooks: list[str]
    decidedBy: Literal["ai_recommendation", "user_answer"]


class ImagePlanOut(BaseModel):
    kind: Literal["generated", "none"]
    prompt: str
    textArea: Literal["top", "bottom", "center"]


class CardOut(BaseModel):
    role: Literal["cover", "body", "summary", "next_action"]
    title: str
    keyLine: str
    sourceUrls: list[str]
    imagePlan: ImagePlanOut


class DeepResearchOutput(BaseModel):
    status: Literal["result", "need_input", "error"]
    researchNotes: list[NoteOut] = []
    question: QuestionOut | None = None
    editorial: EditorialOut | None = None
    cards: list[CardOut] = []
    error: ErrorOut | None = None


class AnswerOutput(BaseModel):
    status: Literal["result", "error"]
    editorial: EditorialOut | None = None
    cards: list[CardOut] = []
    error: ErrorOut | None = None


class StoryboardOutput(BaseModel):
    status: Literal["result", "error"]
    cards: list[CardOut] = []
    error: ErrorOut | None = None


def schema_json(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)


def parse(model: type[BaseModel], raw: dict):
    try:
        return model.model_validate(raw)
    except ValidationError as err:
        raise AppError("ENGINE_OUTPUT_INVALID", "엔진 결과가 약속한 형식과 달라요.",
                       {"errors": err.error_count()}) from err


def invalid(message: str) -> AppError:
    return AppError("ENGINE_OUTPUT_INVALID", message)


# --- 앱 데이터로 바꾸기 -----------------------------------------------------------


def safe_url(url: str) -> str | None:
    url = url.strip()
    return url if re.match(r"^https?://[^\s]+$", url, re.IGNORECASE) else None


def safe_urls(urls: list[str]) -> list[str]:
    return list(dict.fromkeys(u for u in map(safe_url, urls) if u))


def safe_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _date_status(published: str | None, event: str | None) -> str:
    if published and event:
        return "confirmed"
    return "published_only" if published or event else "unverified"


def to_candidates(out: ResearchOutput) -> list[dict]:
    result = []
    for cand in out.candidates:
        sources = [{**s.model_dump(), "url": u} for s in cand.sources if (u := safe_url(s.url))]
        sources = sorted(sources, key=lambda s: SOURCE_RANK[s["type"]])  # 공식 출처가 먼저 보이게
        if not sources:
            continue  # 열어 볼 수 있는 출처가 없으면 후보로 보여 주지 않아요
        published, event = safe_date(cand.publishedAt), safe_date(cand.eventDate)
        result.append({**cand.model_dump(), "sources": sources, "publishedAt": published,
                       "eventDate": event, "dateStatus": _date_status(published, event)})
    return [{"id": f"cand_{i}", **c} for i, c in enumerate(result[:MAX_CANDIDATES], 1)]


def to_notes(notes: list[NoteOut], selected: set[str]) -> list[dict]:
    clean = []
    for note in notes:
        if note.candidateId not in selected:
            continue
        clean.append({
            "candidateId": note.candidateId,
            "facts": [{"text": f.text, "sourceUrls": safe_urls(f.sourceUrls)} for f in note.facts],
            "limits": note.limits,
            "conflicts": [{"text": c.text, "sourceUrls": safe_urls(c.sourceUrls)}
                          for c in note.conflicts],
            "primarySources": safe_urls(note.primarySources),
            "unreachable": [u.model_dump() for u in note.unreachable],
        })
    return clean


def to_question(q: QuestionOut | None) -> dict:
    if q is None or not 2 <= len(q.options) <= 5:
        raise invalid("엔진이 낸 질문에 선택지가 부족해요.")
    option_ids = [o.id for o in q.options]
    if len(set(option_ids)) != len(option_ids):
        raise invalid("엔진이 낸 질문의 선택지 ID가 겹쳐요.")
    recommended = q.recommendedOptionId if q.recommendedOptionId in option_ids else None
    return {
        "id": q.id if QUESTION_ID.match(q.id) else "q_editorial",
        "prompt": q.prompt,
        "multiSelect": False,
        "options": [o.model_dump() for o in q.options],
        "allowFreeText": q.allowFreeText,
        "recommendedOptionId": recommended,
        "recommendationReason": q.recommendationReason if recommended else None,
    }


def allowed_urls(candidates: list[dict], notes: list[dict]) -> set[str]:
    urls = {s["url"] for c in candidates for s in c["sources"]}
    for note in notes:
        urls |= set(note["primarySources"])
        urls |= {u for f in note["facts"] + note["conflicts"] for u in f["sourceUrls"]}
    return urls


def to_cards(cards: list[CardOut], allowed: set[str]) -> list[dict]:
    low, high = CARD_RANGE
    if not low <= len(cards) <= high:
        raise invalid(f"스토리보드가 {len(cards)}장이에요. {low}~{high}장이어야 해요.")
    return [{
        "id": f"card_{i}", "order": i, "role": c.role, "title": c.title, "keyLine": c.keyLine,
        # 조사에 없던 URL은 근거로 인정하지 않아요 → 화면에 "근거 없음"으로 보여요
        "sourceUrls": [u for u in safe_urls(c.sourceUrls) if u in allowed],
        "imagePlan": c.imagePlan.model_dump(),
    } for i, c in enumerate(cards, 1)]


def to_editorial(e: EditorialOut | None, decided_by: str) -> dict:
    if e is None:
        raise invalid("엔진이 편집 제안을 돌려주지 않았어요.")
    return {**e.model_dump(), "hooks": e.hooks[:3], "decidedBy": decided_by}
