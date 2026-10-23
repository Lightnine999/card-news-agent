"""DB 행 ↔ 파이썬 dict 변환. 비즈니스 규칙은 service.py에 있어요."""

import json
import sqlite3

from cardnews import config
from cardnews.errors import AppError
from cardnews.util import new_id, now_iso

ACTIVE_STATUSES = ("queued", "running", "waiting_for_user")


def empty_data() -> dict:
    return {
        "research": None,
        "selection": {"candidateIds": [], "savedAt": None},
        "researchNotes": [],
        "editorial": None,
        "storyboard": None,
        "result": None,
        "questions": [],
        "answers": [],
        "finalApproval": None,
    }


# --- 프로젝트 ------------------------------------------------------------------


def _project_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "version": row["version"],
        "topic": row["topic"],
        "stage": row["stage"],
        "isMock": bool(row["is_mock"]),
        "engineName": row["engine_name"],
        "sessionId": row["engine_session_id"],
        "data": json.loads(row["data"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def insert_project(conn, topic: str, engine_name: str) -> dict:
    pid, ts = new_id("prj"), now_iso()
    conn.execute(
        "INSERT INTO projects (id, version, topic, stage, is_mock, engine_name, "
        "engine_session_id, data, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, 1, topic, "created", int(engine_name == "mock"), engine_name, None,
         json.dumps(empty_data(), ensure_ascii=False), ts, ts),
    )
    return get_project(conn, pid)


def get_project(conn, pid: str) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "프로젝트를 찾지 못했어요.", {"projectId": pid})
    return _project_from_row(row)


def save_project(conn, project: dict) -> dict:
    """바뀐 프로젝트를 저장하고 version을 1 올린 새 dict를 돌려줘요."""
    updated = {**project, "version": project["version"] + 1, "updatedAt": now_iso()}
    conn.execute(
        "UPDATE projects SET version=?, stage=?, engine_session_id=?, data=?, updated_at=? "
        "WHERE id=?",
        (updated["version"], updated["stage"], updated["sessionId"],
         json.dumps(updated["data"], ensure_ascii=False), updated["updatedAt"], updated["id"]),
    )
    return updated


def list_projects(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [_project_from_row(r) for r in rows]


# --- 작업(run) -----------------------------------------------------------------


def _run_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "kind": row["kind"],
        "status": row["status"],
        "dispatch": bool(row["dispatch"]),
        "cancelRequested": bool(row["cancel_requested"]),
        "payload": json.loads(row["payload"]),
        "progress": json.loads(row["progress"]),
        "questionId": row["question_id"],
        "error": json.loads(row["error"]) if row["error"] else None,
        "workerPid": row["worker_pid"],
        "resumedFrom": row["resumed_from"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "createdAt": row["created_at"],
    }


def insert_run(conn, project_id: str, kind: str, payload: dict,
               resumed_from: str | None = None) -> dict:
    rid = new_id("run")
    conn.execute(
        "INSERT INTO runs (id, project_id, kind, status, dispatch, payload, resumed_from, "
        "created_at) VALUES (?,?,?,?,?,?,?,?)",
        (rid, project_id, kind, "queued", 1, json.dumps(payload, ensure_ascii=False),
         resumed_from, now_iso()),
    )
    return get_run(conn, rid)


def get_run(conn, run_id: str) -> dict:
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "작업을 찾지 못했어요.", {"runId": run_id})
    return _run_from_row(row)


_RUN_COLUMNS = {
    "status": "status", "dispatch": "dispatch", "cancelRequested": "cancel_requested",
    "payload": "payload", "progress": "progress", "questionId": "question_id",
    "error": "error", "workerPid": "worker_pid", "startedAt": "started_at",
    "finishedAt": "finished_at",
}
_JSON_FIELDS = {"payload", "progress", "error"}


def update_run(conn, run_id: str, **fields) -> dict:
    sets, values = [], []
    for key, value in fields.items():
        sets.append(f"{_RUN_COLUMNS[key]}=?")
        if key in _JSON_FIELDS and value is not None:
            value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            value = int(value)
        values.append(value)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", (*values, run_id))
    return get_run(conn, run_id)


def append_progress(conn, run_id: str, message: str) -> None:
    run = get_run(conn, run_id)
    entries = [*run["progress"], {"at": now_iso(), "message": message}]
    update_run(conn, run_id, progress=entries[-config.PROGRESS_KEEP:])


def active_run(conn, project_id: str) -> dict | None:
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    row = conn.execute(
        f"SELECT * FROM runs WHERE project_id=? AND status IN ({marks}) "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id, *ACTIVE_STATUSES),
    ).fetchone()
    return _run_from_row(row) if row else None


def last_run(conn, project_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return _run_from_row(row) if row else None


# --- requestId 기록 ------------------------------------------------------------


def find_request(conn, scope: str, request_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM idempotency WHERE scope=? AND request_id=?", (scope, request_id)
    ).fetchone()


def save_request(conn, scope: str, request_id: str, endpoint: str, digest: str,
                 status_code: int, response: dict) -> None:
    conn.execute(
        "INSERT INTO idempotency (scope, request_id, endpoint, body_hash, status_code, "
        "response, created_at) VALUES (?,?,?,?,?,?,?)",
        (scope, request_id, endpoint, digest, status_code,
         json.dumps(response, ensure_ascii=False), now_iso()),
    )
