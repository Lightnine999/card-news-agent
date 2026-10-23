"""스토리보드 승인 뒤 카드별 그림 만들기 (구현 4단계).

카드는 한 장씩 차례로 만들고, 상태를 바로바로 저장해서 화면이 진행을 보여 줘요.
  pending → generating_image → image_ready (글자 렌더링은 5단계에서 이어 붙여요)
                              ↘ failed (그 카드에만 재시도 버튼)
한 장이 실패해도 나머지는 계속해요. 다만 로그인 필요·도구 없음처럼 모든 카드가 같은 이유로
실패할 문제면 남은 카드는 부르지 않아요(할당량 낭비 방지).
"""

from pathlib import Path

from cardnews import config, db, pipeline, repo
from cardnews.engines.base import Cancelled, RunContext
from cardnews.errors import AppError
from cardnews.images import agy, mock

STOP_CODES = {"AUTH_REQUIRED", "TOOL_UNAVAILABLE"}


def _generator(project: dict):
    choice = config.image_gen()
    if choice == "mock" or (choice == "auto" and project["isMock"]):
        return mock.generate, "모의 그림 생성기"
    return agy.generate, agy.agy_version()


# --- 결과(result) 갱신 ------------------------------------------------------------


def _update(run_id: str, change) -> dict:
    """run이 취소되지 않았는지 확인하고, result를 change(result)로 바꿔 저장해요."""
    with db.transaction() as conn:
        if repo.get_run(conn, run_id)["cancelRequested"]:
            raise Cancelled(run_id)
        project = repo.get_project(conn, repo.get_run(conn, run_id)["projectId"])
        result = change(project["data"]["result"])
        repo.save_project(conn, {**project, "data": {**project["data"], "result": result}})
        return result


def _set_card(card_id: str, **fields):
    def change(result: dict) -> dict:
        cards = [{**c, **fields} if c["cardId"] == card_id else c for c in result["cards"]]
        return {**result, "cards": cards}
    return change


def _start_result(run: dict, storyboard: dict):
    """제작이면 새 결과를, 재시도면 그 카드만 새 버전으로 바꾼 결과를 만들어요."""
    def change(result: dict | None) -> dict:
        version = (result or {}).get("version", 0) + 1
        if run["kind"] == "production":
            cards = [{"cardId": c["id"], "cardVersion": 1, "status": "pending", "image": None,
                      "error": None} for c in storyboard["cards"]]
            return {"version": version, "storyboardVersion": storyboard["version"], "cards": cards}
        target = run["payload"]["cardId"]
        cards = [{**c, "cardVersion": c["cardVersion"] + 1, "status": "pending", "image": None,
                  "error": None} if c["cardId"] == target else c for c in result["cards"]]
        return {**result, "version": version, "cards": cards}
    return change


# --- 실행 ----------------------------------------------------------------------------


def _targets(run: dict, storyboard: dict) -> list[dict]:
    if run["kind"] == "production":
        return storyboard["cards"]
    return [c for c in storyboard["cards"] if c["id"] == run["payload"]["cardId"]]


def _make_one(ctx: RunContext, generate, tool: str, card: dict, total: int, result: dict) -> None:
    version = next(c["cardVersion"] for c in result["cards"] if c["cardId"] == card["id"])
    project_dir = config.data_dir() / "projects" / ctx.project_id
    stem = project_dir / "results" / "images" / f"{card['id']}.v{version}"
    _update(ctx.run_id, _set_card(card["id"], status="generating_image"))
    ctx.report(f"그림 만드는 중: {card['order']}/{total} {card['title'][:30]}")
    record = generate(ctx, card["imagePlan"], card["order"], total, stem, tool)
    dest: Path = record.pop("dest")
    image = {**record, "file": dest.relative_to(project_dir).as_posix()}
    _update(ctx.run_id, _set_card(card["id"], status="image_ready", image=image))


def _fail(card_ids: list[str], err: AppError):
    def change(result: dict) -> dict:
        cards = [{**c, "status": "failed", "error": err.to_dict()} if c["cardId"] in card_ids else c
                 for c in result["cards"]]
        return {**result, "cards": cards}
    return change


def execute(run: dict, project: dict, ctx: RunContext) -> None:
    storyboard = project["data"]["storyboard"]
    targets = _targets(run, storyboard)
    result = _update(run["id"], _start_result(run, storyboard))
    try:
        generate, tool = _generator(project)
    except AppError as err:
        _update(run["id"], _fail([c["id"] for c in targets], err))
        targets = []
    total = len(storyboard["cards"])
    for i, card in enumerate(targets):
        try:
            _make_one(ctx, generate, tool, card, total, result)
        except AppError as err:
            stop = err.code in STOP_CODES
            ids = [c["id"] for c in targets[i:]] if stop else [card["id"]]
            _update(run["id"], _fail(ids, err))
            ctx.report(f"그림 실패: {card['order']}/{total} — {err.message}")
            if stop:
                break
    with db.transaction() as conn:
        if not repo.get_run(conn, run["id"])["cancelRequested"]:
            pipeline.finish_run(conn, run["id"], "succeeded")
