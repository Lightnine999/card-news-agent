"""엔진 결과를 프로젝트 상태에 반영해요. 작업 프로세스가 트랜잭션 안에서 불러요."""

from datetime import datetime, timedelta

from cardnews import config, period, questions, repo, sources, support
from cardnews.engines.base import EngineEvent
from cardnews.errors import AppError
from cardnews.util import now_iso

STAGE_OF_KIND = {
    "research": "researching",
    "deep_research": "deep_researching",
    "storyboard": "editing",
    "production": "producing",
    "image_retry": "producing",
    "revision": "reviewing",
}


def finish_run(conn, run_id: str, status: str, error: dict | None = None) -> dict:
    return repo.update_run(conn, run_id, status=status, dispatch=False, error=error,
                           finishedAt=now_iso())


def wait_for_user(conn, project: dict, run: dict, question: dict, origin: str) -> dict:
    data, created = questions.add(project["data"], question, run["id"], origin)
    repo.update_run(conn, run["id"], status="waiting_for_user", dispatch=False,
                    questionId=created["id"])
    return {**project, "data": data}


def _merge_partial(data: dict, partial: dict) -> dict:
    """질문 전·결과와 함께 온 값을 합쳐요. 열어 본 URL은 단계마다 쌓아요."""
    opened = sources.merge(data.get("openedUrls", []), partial.get("openedUrls", []))
    return {**data, **partial, "openedUrls": opened}


def apply_event(conn, run: dict, event: EngineEvent) -> None:
    project = repo.get_project(conn, run["projectId"])
    if event.session_id:
        project = {**project, "sessionId": event.session_id}
    if event.type == "error":
        error = {"code": event.error_code or "INTERNAL_ERROR",
                 "message": event.error_message or "알 수 없는 오류예요."}
        finish_run(conn, run["id"], "failed", _with_actions(error))
        repo.save_project(conn, project)
        return
    if event.type == "need_input":
        project = {**project, "data": _merge_partial(project["data"], event.partial)}
        if run["kind"] == "deep_research":
            project = {**project, "stage": "editing"}
        repo.save_project(conn, wait_for_user(conn, project, run, event.question, "engine"))
        return
    project = {**project, "data": _merge_partial(project["data"], event.partial)}
    repo.save_project(conn, _apply_result(conn, project, run, event.data))


def _with_actions(error: dict) -> dict:
    return AppError(error["code"], error["message"]).to_dict()


def _apply_result(conn, project: dict, run: dict, result: dict) -> dict:
    kind = run["kind"]
    if kind == "research":
        return _apply_research(conn, project, run, result)
    if kind in ("deep_research", "storyboard"):
        finish_run(conn, run["id"], "succeeded")
        return _apply_storyboard(project, result)
    finish_run(conn, run["id"], "succeeded")
    return project


def _apply_research(conn, project: dict, run: dict, result: dict) -> dict:
    payload = run["payload"]
    if payload.get("workflow") == "support":
        return _apply_support_research(conn, project, run, result)
    days = payload["periodDays"]
    to = datetime.fromisoformat(payload["requestedAt"])
    research = {
        "requestedAt": payload["requestedAt"],
        "period": {"days": days, "from": (to - timedelta(days=days)).isoformat(timespec="seconds"),
                   "to": payload["requestedAt"]},
    }
    # 엔진이 기간 밖 소식을 넣었으면 앱이 빼고, 뺀 이유를 남겨 화면에 보여 줘요
    kept, excluded = period.split(result["candidates"], research)
    research = {**research, "candidates": kept, "excluded": excluded}
    project = {**project, "data": {**project["data"], "research": research}}
    found = len(kept)
    if found < config.EXPAND_THRESHOLD and days == 7:
        question = questions.expand_period_question(found, days)
        return wait_for_user(conn, project, run, question, "app")
    finish_run(conn, run["id"], "succeeded")
    return {**project, "stage": "selecting"}


def _apply_support_research(conn, project: dict, run: dict, result: dict) -> dict:
    """지원사업·공모전: 오늘부터 6개월 안의 공고만 남기고 두 묶음으로 나눠요. 적으면 분야·지역을 넓힐지 물어요."""
    payload = run["payload"]
    requested = datetime.fromisoformat(payload["requestedAt"])
    start, end = support.window(requested.date())
    kept, excluded = support.split(result["candidates"], requested.date())
    research = {"requestedAt": payload["requestedAt"], "workflow": "support",
                "period": {"months": support.MONTHS, "from": payload["requestedAt"], "to": end.isoformat()},
                "broadened": bool(payload.get("broaden")), "candidates": kept, "excluded": excluded}
    project = {**project, "data": {**project["data"], "research": research}}
    if len(kept) < support.EXPAND_THRESHOLD and not payload.get("broaden"):
        return wait_for_user(conn, project, run, questions.broaden_question(len(kept)), "app")
    finish_run(conn, run["id"], "succeeded")
    return {**project, "stage": "selecting"}


def _apply_storyboard(project: dict, result: dict) -> dict:
    data = project["data"]
    previous = data["storyboard"]["version"] if data["storyboard"] else 0
    storyboard = {"version": previous + 1, "cards": result["cards"], "approvedAt": None}
    if "dropped" in result:  # 지원사업: 심층 확인에서 빠진 공고와 이유
        storyboard = {**storyboard, "dropped": result["dropped"]}
    editorial = result.get("editorial", data["editorial"])
    return {**project, "stage": "storyboard_review",
            "data": {**data, "storyboard": storyboard, "editorial": editorial}}


def answer_app_question(conn, project: dict, run: dict, question: dict,
                        answer: dict) -> dict:
    """앱이 직접 낸 질문(30일 확장)은 엔진을 부르지 않고 여기서 처리해요."""
    if question["id"] == "q_broaden" and answer.get("optionId") == "broaden":
        payload = {**run["payload"], "broaden": True, "phase": "start", "requestedAt": None}
        repo.update_run(conn, run["id"], status="running", dispatch=True, payload=payload,
                        questionId=None)
        return project
    if question["id"] == "q_expand_period" and answer.get("optionId") == "expand":
        payload = {**run["payload"], "periodDays": 30, "phase": "start", "requestedAt": None}
        repo.update_run(conn, run["id"], status="running", dispatch=True, payload=payload,
                        questionId=None)
        return project
    finish_run(conn, run["id"], "succeeded")
    return {**project, "stage": "selecting"}
