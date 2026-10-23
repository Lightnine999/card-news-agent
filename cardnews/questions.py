"""질문 기록. project.data.questions에 지나간 질문까지 모두 남겨요.

질문 상태: open(답 기다림) / answered / stale(취소·재시작으로 지나감)
"""

from cardnews.errors import AppError

FREE_TEXT_MAX = 300


def open_question(data: dict) -> dict | None:
    return next((q for q in reversed(data["questions"]) if q["status"] == "open"), None)


def find(data: dict, qid: str, version: int) -> dict | None:
    return next((q for q in data["questions"] if q["id"] == qid and q["version"] == version),
                None)


def add(data: dict, question: dict, run_id: str, origin: str) -> tuple[dict, dict]:
    """새 질문을 열어요. 같은 ID의 질문이 있었으면 version을 올리고, 열려 있던 질문은 stale로."""
    same = [q["version"] for q in data["questions"] if q["id"] == question["id"]]
    created = {
        "multiSelect": False, "allowFreeText": False,
        "recommendedOptionId": None, "recommendationReason": None,
        **question,
        "version": max(same, default=0) + 1,
        "runId": run_id,
        "origin": origin,  # engine: 엔진이 낸 질문 / app: 앱이 직접 낸 질문
        "status": "open",
    }
    rest = [{**q, "status": "stale"} if q["status"] == "open" else q for q in data["questions"]]
    return {**data, "questions": [*rest, created]}, created


def set_status(data: dict, qid: str, version: int, status: str) -> dict:
    questions = [{**q, "status": status} if q["id"] == qid and q["version"] == version else q
                 for q in data["questions"]]
    return {**data, "questions": questions}


def stale_for_run(data: dict, run_id: str) -> dict:
    questions = [{**q, "status": "stale"} if q["runId"] == run_id and q["status"] == "open"
                 else q for q in data["questions"]]
    return {**data, "questions": questions}


def check_answerable(data: dict, qid: str, version: int) -> dict:
    current = open_question(data)
    if current and current["id"] == qid and current["version"] == version:
        return current
    past = find(data, qid, version)
    if past and past["status"] == "answered":
        raise AppError("ALREADY_ANSWERED", "이 질문에는 이미 답이 반영됐어요.",
                       {"questionId": qid, "version": version})
    raise AppError("QUESTION_STALE", "지금 기다리는 질문이 아니에요. 화면을 새로 불러올게요.",
                   {"questionId": qid, "version": version,
                    "current": public(current) if current else None})


def validate_answer(question: dict, answer: dict) -> dict:
    option_ids = {o["id"] for o in question["options"]}
    if "freeText" in answer:
        text = answer["freeText"].strip()
        if not question["allowFreeText"]:
            raise AppError("VALIDATION_ERROR", "이 질문은 직접 입력을 받지 않아요.")
        if not 1 <= len(text) <= FREE_TEXT_MAX:
            raise AppError("VALIDATION_ERROR", f"직접 입력은 1~{FREE_TEXT_MAX}자예요.")
        return {"freeText": text}
    if "optionIds" in answer:
        chosen = answer["optionIds"]
        if not question["multiSelect"] or not chosen or not set(chosen) <= option_ids:
            raise AppError("VALIDATION_ERROR", "선택지가 올바르지 않아요.")
        return {"optionIds": list(dict.fromkeys(chosen))}
    if answer.get("optionId") not in option_ids:
        raise AppError("VALIDATION_ERROR", "선택지가 올바르지 않아요.")
    return {"optionId": answer["optionId"]}


def public(question: dict) -> dict:
    return {k: v for k, v in question.items() if k != "origin"}


def expand_period_question(found: int, days: int) -> dict:
    return {
        "id": "q_expand_period",
        "prompt": f"최근 {days}일 결과가 {found}개뿐이에요. 30일로 넓힐까요?",
        "options": [
            {"id": "expand", "label": "30일로 넓히기", "description": "더 많은 후보를 찾지만 조금 오래된 소식도 섞여요."},
            {"id": "keep", "label": "이대로 보기", "description": f"찾은 {found}개 안에서 골라요."},
        ],
        "allowFreeText": False,
        "recommendedOptionId": "expand",
        "recommendationReason": "후보가 적으면 다양한 소식을 비교하기 어려워서요.",
    }
