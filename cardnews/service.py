"""웹 요청이 지켜야 할 규칙 (API_SPEC 3). 모든 함수는 트랜잭션 안에서 불려요."""

import json

from cardnews import config, db, pipeline, production, questions, repo
from cardnews.errors import AppError
from cardnews.util import body_hash, now_iso


# --- requestId 중복 방지 (API_SPEC 0.2) ----------------------------------------


def idempotent(scope: str, request_id: str | None, endpoint: str, body: dict, action):
    """같은 requestId·같은 입력이면 처음 응답을 그대로 돌려줘요.

    action(conn) → (status_code, response). 성공 응답만 저장해요.
    """
    with db.transaction() as conn:
        if request_id is None:
            return action(conn)
        digest = body_hash(endpoint, body)
        saved = repo.find_request(conn, scope, request_id)
        if saved is not None:
            if saved["body_hash"] != digest:
                raise AppError("IDEMPOTENCY_CONFLICT",
                               "같은 요청 ID로 다른 내용이 왔어요. 화면을 새로 불러올게요.",
                               {"requestId": request_id})
            return saved["status_code"], json.loads(saved["response"])
        status_code, response = action(conn)
        repo.save_request(conn, scope, request_id, endpoint, digest, status_code, response)
        return status_code, response


# --- 공통 확인 -----------------------------------------------------------------


IMAGE_KINDS = ("production", "image_retry")


def _require_stage(project: dict, *stages: str) -> None:
    if project["stage"] not in stages:
        raise AppError("STAGE_CONFLICT", "지금 단계에서는 할 수 없는 요청이에요.",
                       {"stage": project["stage"], "allowed": list(stages)})


def _require_version(current: int, sent: int) -> None:
    if current != sent:
        raise AppError("VERSION_CONFLICT", "화면이 바뀌어서 새로 불러올게요.",
                       {"currentVersion": current, "sentVersion": sent})


def _require_idle(conn, project_id: str) -> None:
    run = repo.active_run(conn, project_id)
    if run is not None:
        raise AppError("RUN_IN_PROGRESS", "이미 진행 중인 작업이 있어요.",
                       {"runId": run["id"], "status": run["status"]})


def _start_run(conn, project: dict, kind: str, payload: dict) -> tuple[dict, dict]:
    run = repo.insert_run(conn, project["id"], kind, {
        **payload, "phase": "start", "prevStage": project["stage"],
        "engineName": project["engineName"],
    })
    updated = repo.save_project(conn, {**project, "stage": pipeline.STAGE_OF_KIND[kind]})
    return updated, run


# --- 프로젝트·조사 ---------------------------------------------------------------


def create_project(conn, topic: str) -> dict:
    return repo.insert_project(conn, topic, config.engine_name())


def start_research(conn, project_id: str, period_days: int) -> dict:
    project = repo.get_project(conn, project_id)
    _require_stage(project, "created", "researching", "selecting")
    _require_idle(conn, project_id)
    data = {**project["data"], "research": None,
            "selection": {"candidateIds": [], "savedAt": None}}
    project, run = _start_run(conn, {**project, "data": data}, "research",
                              {"periodDays": period_days, "requestedAt": None})
    return {"runId": run["id"], "status": run["status"]}


def save_selection(conn, project_id: str, candidate_ids: list[str], version: int) -> dict:
    project = repo.get_project(conn, project_id)
    _require_stage(project, "selecting")
    _require_version(project["version"], version)
    known = {c["id"] for c in project["data"]["research"]["candidates"]}
    ids = list(dict.fromkeys(candidate_ids))
    if len(ids) > config.MAX_SELECTION:
        raise AppError("VALIDATION_ERROR", f"최대 {config.MAX_SELECTION}개까지 고를 수 있어요.")
    if not set(ids) <= known:
        raise AppError("VALIDATION_ERROR", "없는 후보가 들어 있어요.",
                       {"unknown": sorted(set(ids) - known)})
    selection = {"candidateIds": ids, "savedAt": now_iso()}
    saved = repo.save_project(conn, {**project, "data": {**project["data"],
                                                         "selection": selection}})
    return {"selection": selection, "version": saved["version"]}


def start_deep_research(conn, project_id: str, version: int) -> dict:
    project = repo.get_project(conn, project_id)
    _require_stage(project, "selecting")
    _require_version(project["version"], version)
    _require_idle(conn, project_id)
    count = len(project["data"]["selection"]["candidateIds"])
    if not 1 <= count <= config.MAX_SELECTION:
        raise AppError("STAGE_CONFLICT", "후보를 1~3개 고른 뒤에 진행할 수 있어요.",
                       {"selected": count})
    _, run = _start_run(conn, project, "deep_research", {})
    return {"runId": run["id"], "status": run["status"]}


# --- 질문 답변 -----------------------------------------------------------------


def submit_answer(conn, project_id: str, question_id: str, version: int,
                  answer: dict) -> dict:
    project = repo.get_project(conn, project_id)
    question = questions.check_answerable(project["data"], question_id, version)
    clean = questions.validate_answer(question, answer)
    run = repo.get_run(conn, question["runId"])
    record = {"questionId": question_id, "questionVersion": version, "answer": clean,
              "answeredAt": now_iso()}
    data = questions.set_status(project["data"], question_id, version, "answered")
    project = {**project, "data": {**data, "answers": [*data["answers"], record]}}
    if question["origin"] == "app":
        project = pipeline.answer_app_question(conn, project, run, question, clean)
    else:
        payload = {**run["payload"], "phase": "answer",
                   "question": questions.public(question), "answer": clean}
        repo.update_run(conn, run["id"], status="running", dispatch=True, payload=payload,
                        questionId=None)
    repo.save_project(conn, project)
    current = repo.get_run(conn, run["id"])
    return {"accepted": True, "runId": run["id"], "status": current["status"]}


# --- 스토리보드·승인 -------------------------------------------------------------


def storyboard_feedback(conn, project_id: str, instruction: str, version: int) -> dict:
    project = repo.get_project(conn, project_id)
    _require_stage(project, "storyboard_review")
    _require_version(project["data"]["storyboard"]["version"], version)
    _require_idle(conn, project_id)
    _, run = _start_run(conn, project, "storyboard", {"instruction": instruction})
    return {"runId": run["id"]}


def approve(conn, project_id: str, stage: str, version: int) -> tuple[int, dict]:
    project = repo.get_project(conn, project_id)
    if stage == "storyboard":
        return 202, _approve_storyboard(conn, project, version)
    return 200, _approve_final(conn, project, version)


def _approve_storyboard(conn, project: dict, version: int) -> dict:
    _require_stage(project, "storyboard_review")
    _require_version(project["data"]["storyboard"]["version"], version)
    _require_idle(conn, project["id"])
    storyboard = {**project["data"]["storyboard"], "approvedAt": now_iso()}
    project = {**project, "data": {**project["data"], "storyboard": storyboard}}
    _, run = _start_run(conn, project, "production", {})
    return {"runId": run["id"]}


def _approve_final(conn, project: dict, version: int) -> dict:
    _require_stage(project, "reviewing")
    result = project["data"]["result"]
    _require_version(result["version"], version)
    if any(card["status"] != "done" for card in result["cards"]):
        raise AppError("STAGE_CONFLICT", "모든 카드가 완료돼야 최종 승인할 수 있어요.")
    approval = {"resultVersion": version, "approvedAt": now_iso()}
    repo.save_project(conn, {**project, "stage": "final_approved",
                             "data": {**project["data"], "finalApproval": approval}})
    return {"finalApproval": approval}


def retry_card(conn, project_id: str, card_id: str, result_version: int) -> dict:
    project = repo.get_project(conn, project_id)
    _require_stage(project, "producing")
    result = project["data"]["result"]
    if result is None:
        raise AppError("STAGE_CONFLICT", "아직 제작 결과가 없어요.")
    _require_version(result["version"], result_version)
    card = next((c for c in result["cards"] if c["cardId"] == card_id), None)
    if card is None:
        raise AppError("NOT_FOUND", "카드를 찾지 못했어요.", {"cardId": card_id})
    redraw = card["status"] == "image_ready" and (card.get("image") or {}).get("fallbackFrom")
    if card["status"] != "failed" and not redraw:  # agy 대신 그린 카드는 agy로 다시 그릴 수 있어요
        raise AppError("STAGE_CONFLICT", "실패했거나 대신 그린 카드만 다시 만들 수 있어요.",
                       {"status": card["status"]})
    _require_idle(conn, project_id)
    _, run = _start_run(conn, project, "image_retry", {"cardId": card_id})
    return {"runId": run["id"]}


# --- 취소·이어하기 ---------------------------------------------------------------


def cancel_run(conn, run_id: str) -> dict:
    run = repo.get_run(conn, run_id)
    if run["status"] not in repo.ACTIVE_STATUSES:
        return {"status": run["status"]}
    repo.update_run(conn, run_id, status="cancelled", cancelRequested=True, dispatch=False,
                    finishedAt=now_iso(),
                    error=AppError("CANCELLED", "작업을 취소했어요.").to_dict())
    project = repo.get_project(conn, run["projectId"])
    data = questions.stale_for_run(project["data"], run_id)
    if run["kind"] in IMAGE_KINDS:
        card_error = AppError("CANCELLED", "취소해서 이 카드 그림을 끝내지 못했어요.").to_dict()
        data = {**data, "result": production.mark_unfinished(data["result"], card_error)}
    repo.save_project(conn, {**project, "stage": run["payload"]["prevStage"], "data": data})
    return {"status": "cancelled"}


def resume_run(conn, run_id: str, mode: str) -> dict:
    run = repo.get_run(conn, run_id)
    if run["status"] not in ("failed", "interrupted"):
        raise AppError("STAGE_CONFLICT", "끊기거나 실패한 작업만 이어갈 수 있어요.",
                       {"status": run["status"]})
    project = repo.get_project(conn, run["projectId"])
    _require_idle(conn, project["id"])
    same_engine = run["payload"].get("engineName") == project["engineName"]
    images = run["kind"] in IMAGE_KINDS  # 그림 작업은 엔진 세션 없이 남은 카드만 이어서 만들어요
    if mode == "continue" and not images and not (project["sessionId"] and same_engine):
        raise AppError("STAGE_CONFLICT", "이어갈 엔진 세션이 없어요. 처음부터 다시 해 주세요.",
                       next_actions=["restart"])
    if mode == "restart":
        project = {**project, "sessionId": None}
    payload = {k: v for k, v in run["payload"].items() if k not in ("question", "answer")}
    payload = {**payload, "phase": "start", "requestedAt": None,
               "onlyUnfinished": images and mode == "continue"}
    new_run = repo.insert_run(conn, project["id"], run["kind"], payload, resumed_from=run_id)
    repo.save_project(conn, {**project, "stage": pipeline.STAGE_OF_KIND[run["kind"]]})
    return {"runId": new_run["id"]}
