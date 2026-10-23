"""GET 응답 모양 (API_SPEC 2.1, 2.6)."""

from cardnews import questions, repo, sources


def public_run(run: dict | None) -> dict | None:
    if run is None:
        return None
    keys = ("id", "projectId", "kind", "status", "progress", "questionId", "error",
            "startedAt", "finishedAt", "resumedFrom")
    view = {k: run[k] for k in keys}
    if run["kind"] == "research":  # 조사 중에도 기준 시각·기간을 보여 주려고요
        view["period"] = {"days": run["payload"]["periodDays"],
                          "requestedAt": run["payload"].get("requestedAt")}
    return view


def _research_view(data: dict) -> dict | None:
    research = data["research"]
    if not research:
        return research
    marked = sources.mark(research["candidates"], data.get("openedUrls", []))
    return {**research, "candidates": marked}


def _result_view(project_id: str, result: dict | None) -> dict | None:
    if not result:
        return result
    base = f"/api/projects/{project_id}/files/"
    cards = [{**c, "imageUrl": base + c["image"]["file"] if c.get("image") else None,
              "pngUrl": base + c["png"] if c.get("png") else None} for c in result["cards"]]
    return {**result, "cards": cards}


def project_view(conn, project: dict) -> dict:
    data = project["data"]
    current = questions.open_question(data)
    return {
        "id": project["id"],
        "version": project["version"],
        "topic": project["topic"],
        "stage": project["stage"],
        "isMock": project["isMock"],
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
        "exportsReady": False,
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
