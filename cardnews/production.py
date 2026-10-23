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
from cardnews.images import agy, claude_svg, mock

STOP_CODES = {"AUTH_REQUIRED", "TOOL_UNAVAILABLE"}


def _tools(project: dict) -> dict:
    """그림 도구 계획: 기본 도구, 대안(Claude CLI SVG), 그리고 기본 도구가 이미 쓸 수 없는지."""
    choice = config.image_gen()
    if choice == "mock" or (choice == "auto" and project["isMock"]):
        return {"primary": (mock.generate, "모의 그림 생성기"), "fallback": None, "down": None}
    fallback = (claude_svg.generate, claude_svg.tool_name()) if config.image_fallback() == "claude" else None
    try:
        return {"primary": (agy.generate, agy.agy_version()), "fallback": fallback, "down": None}
    except AppError as err:  # agy가 없으면 처음부터 대안으로 그려요
        return {"primary": None, "fallback": fallback, "down": err}


def _draw(ctx: RunContext, tools: dict, plan: dict, index: int, total: int, stem: Path) -> dict:
    """agy로 그리고, 못 그리면 Claude CLI SVG로 대신 그려요. 둘 다 못 그리면 두 이유를 함께 알려요."""
    agy_error = tools["down"]
    if tools["primary"] and agy_error is None:
        generate, tool = tools["primary"]
        try:
            return generate(ctx, plan, index, total, stem, tool)
        except AppError as err:
            agy_error = err
            if err.code in STOP_CODES:
                tools["down"] = err  # 남은 카드는 agy를 다시 부르지 않아요
    if tools["fallback"] is None:
        raise agy_error
    generate, tool = tools["fallback"]
    ctx.report(f"agy 대신 Claude CLI로 그리는 중: {index}/{total} ({agy_error.message[:40]})")
    try:
        record = generate(ctx, plan, index, total, stem, tool)
    except AppError as err:
        raise AppError(err.code, f"agy로 못 만들었어요({agy_error.message}). "
                                 f"Claude CLI로도 못 만들었어요({err.message})") from err
    return {**record, "fallbackFrom": {"tool": "agy", "code": agy_error.code, "message": agy_error.message}}


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


UNFINISHED = ("pending", "generating_image")


def mark_unfinished(result: dict | None, error: dict) -> dict | None:
    """끝나지 않은 카드(대기·만드는 중)를 실패로 바꿔요. 서버 재시작·취소 뒤 "만드는 중"으로 남지 않게요."""
    if not result:
        return result
    cards = [{**c, "status": "failed", "error": error} if c["status"] in UNFINISHED else c
             for c in result["cards"]]
    return {**result, "cards": cards}


def _fresh_result(storyboard: dict, version: int) -> dict:
    cards = [{"cardId": c["id"], "cardVersion": 1, "status": "pending", "image": None,
              "error": None} for c in storyboard["cards"]]
    return {"version": version, "storyboardVersion": storyboard["version"], "cards": cards}


def _start_result(storyboard: dict, target_ids: set[str], fresh: bool):
    """처음 제작이면 새 결과를, 아니면 대상 카드만 새 버전으로 바꾼 결과를 만들어요. 나머지 카드는 그대로예요."""
    def change(result: dict | None) -> dict:
        version = (result or {}).get("version", 0) + 1
        if fresh or not result:
            return _fresh_result(storyboard, version)
        cards = [{**c, "cardVersion": c["cardVersion"] + 1, "status": "pending", "image": None,
                  "error": None} if c["cardId"] in target_ids else c for c in result["cards"]]
        return {**result, "version": version, "cards": cards}
    return change


# --- 실행 ----------------------------------------------------------------------------


def _targets(run: dict, storyboard: dict, result: dict | None) -> tuple[list[dict], bool]:
    """(만들 카드, 결과를 새로 시작할지). "이어서 하기"는 끝나지 않은 카드만 만들어요."""
    if run["kind"] == "image_retry":
        return [c for c in storyboard["cards"] if c["id"] == run["payload"]["cardId"]], False
    if run["payload"].get("onlyUnfinished") and result:
        done = {c["cardId"] for c in result["cards"] if c["status"] == "image_ready"}
        return [c for c in storyboard["cards"] if c["id"] not in done], False
    return storyboard["cards"], True


def _make_one(ctx: RunContext, tools: dict, card: dict, total: int, result: dict) -> None:
    version = next(c["cardVersion"] for c in result["cards"] if c["cardId"] == card["id"])
    project_dir = config.data_dir() / "projects" / ctx.project_id
    stem = project_dir / "results" / "images" / f"{card['id']}.v{version}"
    _update(ctx.run_id, _set_card(card["id"], status="generating_image"))
    ctx.report(f"그림 만드는 중: {card['order']}/{total} {card['title'][:30]}")
    record = _draw(ctx, tools, card["imagePlan"], card["order"], total, stem)
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
    targets, fresh = _targets(run, storyboard, project["data"]["result"])
    result = _update(run["id"], _start_result(storyboard, {c["id"] for c in targets}, fresh))
    tools = _tools(project)
    total = len(storyboard["cards"])
    for i, card in enumerate(targets):
        try:
            _make_one(ctx, tools, card, total, result)
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
