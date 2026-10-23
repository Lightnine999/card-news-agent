"""작업 프로세스. 웹 서버가 DB에 넣은 run을 가져가 엔진을 실행해요.

웹 요청과 분리돼 있어서 긴 작업도 HTTP 요청을 붙잡지 않아요 (PRD 실행 구조).
"""

import logging
import os
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from cardnews import config, db, pipeline, production, proc, repo
from cardnews.engines.base import Cancelled, EngineEvent, RunContext, get_engine
from cardnews.errors import AppError
from cardnews.util import now_iso

log = logging.getLogger("cardnews.worker")
POLL_SECONDS = 0.3
IMAGE_KINDS = ("production", "image_retry")


def recover_interrupted() -> int:
    """시작할 때 한 번: 가져갔는데 끝나지 않은 run은 끊긴 것으로 표시해요. 자동 재실행은 안 해요."""
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT id, kind, project_id FROM runs WHERE status='running' AND dispatch=0").fetchall()
        error = AppError("INTERRUPTED", "서버가 다시 시작돼서 작업이 멈췄어요.").to_dict()
        card_error = AppError("INTERRUPTED", "서버가 다시 시작돼서 이 카드 그림을 끝내지 못했어요.").to_dict()
        for row in rows:
            pipeline.finish_run(conn, row["id"], "interrupted", error)
            if row["kind"] in IMAGE_KINDS:
                _mark_cards(conn, row["project_id"], card_error)
    return len(rows)


def _mark_cards(conn, project_id: str, error: dict) -> None:
    project = repo.get_project(conn, project_id)
    result = production.mark_unfinished(project["data"]["result"], error)
    repo.save_project(conn, {**project, "data": {**project["data"], "result": result}})


def claim_next() -> dict | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE dispatch=1 AND cancel_requested=0 "
            "ORDER BY created_at, rowid LIMIT 1").fetchone()
        if row is None:
            return None
        run = repo.get_run(conn, row["id"])
        payload = run["payload"]
        if run["kind"] == "research" and payload["phase"] == "start" and not payload.get("requestedAt"):
            payload = {**payload, "requestedAt": now_iso()}  # 조사 기준 시각 = 시작 시각
        return repo.update_run(conn, run["id"], status="running", dispatch=False,
                               workerPid=os.getpid(), payload=payload,
                               startedAt=run["startedAt"] or now_iso())


def _context(run: dict, project: dict) -> RunContext:
    project_dir = config.data_dir() / "projects" / project["id"]
    run_dir = project_dir / "runs" / run["id"]
    run_dir.mkdir(parents=True, exist_ok=True)

    def report(message: str) -> None:
        with db.transaction() as conn:
            repo.append_progress(conn, run["id"], message)

    def check_cancel() -> None:
        with db.transaction() as conn:
            if repo.get_run(conn, run["id"])["cancelRequested"]:
                raise Cancelled(run["id"])

    return RunContext(run_id=run["id"], project_id=project["id"], topic=project["topic"],
                      session_id=project["sessionId"], run_dir=run_dir, report=report,
                      check_cancel=check_cancel, engine_dir=project_dir / "engine")


def _task(run: dict, project: dict) -> dict:
    data = project["data"]
    selected = set(data["selection"]["candidateIds"])
    candidates = [c for c in (data["research"] or {}).get("candidates", []) if c["id"] in selected]
    base = {"kind": run["kind"], "topic": project["topic"]}
    if run["kind"] == "research":
        return {**base, "periodDays": run["payload"]["periodDays"],
                "requestedAt": run["payload"]["requestedAt"]}
    return {**base, "candidates": candidates, "researchNotes": data["researchNotes"],
            "editorial": data["editorial"], "storyboard": data["storyboard"],
            "instruction": run["payload"].get("instruction")}


def _execute_images(run: dict, project: dict) -> None:
    try:
        production.execute(run, project, _context(run, project))
    except Cancelled:
        return
    except Exception:  # 예상 못 한 오류도 run에 남겨 화면에 보여요
        log.exception("run %s 실패", run["id"])
        with db.transaction() as conn:
            error = AppError("INTERNAL_ERROR", "그림을 만드는 중 예상하지 못한 오류가 났어요.").to_dict()
            pipeline.finish_run(conn, run["id"], "failed", error)


def execute(run: dict) -> None:
    with db.transaction() as conn:
        project = repo.get_project(conn, run["projectId"])
    if run["kind"] in IMAGE_KINDS:
        _execute_images(run, project)
        return
    try:
        engine = get_engine(run["payload"]["engineName"])
        ctx, task = _context(run, project), _task(run, project)
        if run["payload"]["phase"] == "answer":
            event = engine.send_answer(ctx, task, run["payload"]["question"],
                                       run["payload"]["answer"])
        else:
            event = engine.start(ctx, task)
    except Cancelled:
        return  # 취소 요청에서 이미 상태를 정리했어요
    except AppError as err:
        event = EngineEvent(type="error", error_code=err.code, error_message=err.message)
    except Exception:  # 엔진 코드의 예상 못 한 오류도 run에 남겨 화면에 보여요
        log.exception("run %s 실패", run["id"])
        event = EngineEvent(type="error", error_code="INTERNAL_ERROR",
                            error_message="작업 중 예상하지 못한 오류가 났어요.")
    _apply(run["id"], event)


def _apply(run_id: str, event: EngineEvent) -> None:
    with db.transaction() as conn:
        current = repo.get_run(conn, run_id)
        if current["cancelRequested"] or current["status"] != "running":
            return  # 그사이 취소됐으면 결과를 버려요
        pipeline.apply_event(conn, current, event)


def run_pending() -> None:
    """가져갈 run이 없을 때까지 차례로 처리해요 (테스트·디버그용)."""
    while (run := claim_next()) is not None:
        execute(run)


def _exit_with_parent(parent: int) -> None:
    """웹 서버가 끝나면 하던 작업도 바로 멈춰요.

    혼자 남아 작업을 끝내면 서버 없이 엔진 호출이 계속되고, 다음 서버의 복구와 겹쳐요.
    실행 중이던 run은 running으로 남고 다음 시작 때 interrupted로 표시돼요.
    """
    while os.getppid() == parent:
        time.sleep(POLL_SECONDS)
    _shutdown("웹 서버가 끝나서 작업 프로세스도 끝내요", 1)


def _shutdown(reason: str, code: int) -> None:
    """실행 중이던 claude·agy까지 끝내고 바로 나가요. 실행 중이던 run은 다음 시작 때 interrupted가 돼요."""
    killed = proc.kill_all()
    log.info("%s%s", reason, f" (실행 중이던 엔진 {killed}개도 끝냈어요)" if killed else "")
    os._exit(code)


def _on_signal(signum, _frame) -> None:
    _shutdown("종료 신호를 받아서 작업 프로세스를 끝내요", 0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[worker] %(message)s")
    db.init_db()
    recovered = recover_interrupted()
    if recovered:
        log.info("끊긴 작업 %d개를 interrupted로 표시했어요", recovered)
    signal.signal(signal.SIGTERM, _on_signal)  # 서버가 끌 때
    signal.signal(signal.SIGINT, _on_signal)   # 터미널에서 Ctrl+C
    threading.Thread(target=_exit_with_parent, args=(os.getppid(),), daemon=True).start()
    running: set[Future] = set()
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_RUNS) as pool:
        while True:
            running = {f for f in running if not f.done()}
            if len(running) < config.MAX_CONCURRENT_RUNS and (run := claim_next()):
                running.add(pool.submit(execute, run))
                continue
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
