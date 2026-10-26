"""GET 응답 모양 (API_SPEC 2.1, 2.6)."""

from cardnews import questions, repo, service, sources, support
from cardnews.util import now


def public_run(run: dict | None) -> dict | None:
    if run is None:
        return None
    keys = ("id", "projectId", "kind", "status", "progress", "questionId", "error",
            "startedAt", "finishedAt", "resumedFrom")
    view = {k: run[k] for k in keys}
    if run["kind"] == "research":  # 조사 중에도 기준 시각·기간을 보여 주려고요
        span = {"months": support.MONTHS} if run["payload"].get("workflow") == "support" \
            else {"days": run["payload"]["periodDays"]}
        view["period"] = {**span, "requestedAt": run["payload"].get("requestedAt")}
    return view


def _research_view(data: dict) -> dict | None:
    research = data["research"]
    if not research:
        return research
    marked = sources.mark(research["candidates"], data.get("openedUrls", []))
    if research.get("workflow") == "support":  # D-day는 화면을 볼 때마다 오늘 기준으로 앱이 계산해요
        today = now().date()
        marked = [{**c, "dday": support.dday_text(c["deadline"], today)
                   if c.get("dateStatus") == "confirmed" and c.get("deadline") else None} for c in marked]
    return {**research, "candidates": marked}


def _result_view(project_id: str, result: dict | None) -> dict | None:
    if not result:
        return result
    base = f"/api/projects/{project_id}/files/"
    cards = [{**c, "imageUrl": base + c["image"]["file"] if c.get("image") else None,
              "pngUrl": base + c["png"] if c.get("png") else None} for c in result["cards"]]
    return {**result, "cards": cards}


def _exports_ready(data: dict) -> bool:
    approval, exports = data.get("finalApproval"), data.get("exports")
    return bool(approval and exports and exports["resultVersion"] == approval["resultVersion"])


def project_view(conn, project: dict) -> dict:
    data = project["data"]
    current = questions.open_question(data)
    return {
        "id": project["id"],
        "version": project["version"],
        "topic": project["topic"],
        "stage": project["stage"],
        "isMock": project["isMock"],
        "workflow": service.workflow(project),
        "maxSelection": service.max_selection(project),
        "engine": {"name": project["engineName"], "sessionId": project["sessionId"]},
        "research": _research_view(data),
        "selection": data["selection"],
        "researchNotes": data["researchNotes"],
        "editorial": data["editorial"],
        "storyboard": data["storyboard"],
        "result": _result_view(project["id"], data["result"]),
        "currentQuestion": questions.public(current) if current else None,
        "answers": data["answers"],
        "activeRun": public_run(repo.active_run(conn, project["id"])),
        "lastRun": public_run(repo.last_run(conn, project["id"])),
        "finalApproval": data["finalApproval"],
        "exportsReady": _exports_ready(data),
        "exports": service.exports_view(project) if _exports_ready(data) and project["stage"] == "final_approved" else None,
        "createdAt": project["createdAt"],
    }


def project_summary(conn, project: dict) -> dict:
    active = repo.active_run(conn, project["id"])
    return {
        "id": project["id"],
        "topic": project["topic"],
        "stage": project["stage"],
        "isMock": project["isMock"],
        "createdAt": project["createdAt"],
        "waitingForUser": bool(active and active["status"] == "waiting_for_user"),
    }
