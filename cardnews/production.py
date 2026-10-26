"""스토리보드 승인 뒤 카드별 그림 만들기와 글자 올리기 (구현 4·5단계).

카드는 한 장씩 차례로 만들고, 상태를 바로바로 저장해서 화면이 진행을 보여 줘요.
  pending → generating_image → rendering → done (점검 결과는 checks.layout에 따로)
                             ↘ failed (그 카드에만 재시도 버튼)
글자만 다시 올리는 run(render)은 그림을 그대로 쓰고 rendering부터 해요.
한 장이 실패해도 나머지는 계속해요. 다만 로그인 필요·도구 없음처럼 모든 카드가 같은 이유로
실패할 문제면 남은 카드는 부르지 않아요(할당량 낭비 방지).
"""

from pathlib import Path

from cardnews import config, db, pipeline, repo, revise, support
from cardnews.engines.base import Cancelled, RunContext
from cardnews.errors import AppError
from cardnews.images import agy, claude_svg, mock
from cardnews.render.runner import Renderer
from cardnews.util import now

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


UNFINISHED = ("pending", "generating_image", "rendering")


def mark_unfinished(result: dict | None, error: dict) -> dict | None:
    """끝나지 않은 카드(대기·만드는 중)를 실패로 바꿔요. 서버 재시작·취소 뒤 "만드는 중"으로 남지 않게요."""
    if not result:
        return result
    cards = [{**c, "status": "failed", "error": error} if c["status"] in UNFINISHED else c
             for c in result["cards"]]
    return {**result, "cards": cards}


def default_layout(plan: dict) -> dict:
    """글자 배치 기본값: 스토리보드가 비워 둔 자리, 나머지는 자동. 문구는 스토리보드 그대로(None)."""
    return {"textArea": plan["imagePlan"].get("textArea") or "top", "scale": None, "scrim": "auto",
            "color": "auto", "title": None, "keyLine": None, "body": None, "textEdited": False}


def _fresh_result(storyboard: dict, version: int) -> dict:
    cards = [{"cardId": c["id"], "cardVersion": 1, "status": "pending", "image": None, "png": None,
              "checks": None, "layout": default_layout(c), "error": None} for c in storyboard["cards"]]
    return {"version": version, "storyboardVersion": storyboard["version"], "cards": cards}


def _start_result(storyboard: dict, targets: dict[str, bool], fresh: bool):
    """처음 제작이면 새 결과를, 아니면 대상 카드만 새 버전으로 바꾼 결과를 만들어요. 나머지 카드는 그대로예요.

    targets = {카드 ID: 그림도 새로 그릴지}. 글자만 올리는 카드는 그림을 그대로 둬요.
    """
    def change(result: dict | None) -> dict:
        version = (result or {}).get("version", 0) + 1
        if fresh or not result:
            return _fresh_result(storyboard, version)
        cards = [{**c, "cardVersion": c["cardVersion"] + 1, "status": "pending", "png": None, "checks": None,
                  "error": None, **({"image": None} if targets[c["cardId"]] else {})}
                 if c["cardId"] in targets else c for c in result["cards"]]
        return {**result, "version": version, "cards": cards}
    return change


# --- 실행 ----------------------------------------------------------------------------


def _targets(run: dict, storyboard: dict, result: dict | None) -> tuple[list[tuple[dict, bool]], bool]:
    """([(카드, 그림도 그릴지)], 결과를 새로 시작할지).

    "이어서 하기"는 끝나지 않은 카드만, 그림이 이미 있으면 글자만 올려요.
    """
    entries = {c["cardId"]: c for c in (result or {}).get("cards", [])}
    has_image = lambda card: bool(entries.get(card["id"], {}).get("image"))  # noqa: E731
    if run["kind"] == "image_retry":
        return [(c, True) for c in storyboard["cards"] if c["id"] == run["payload"]["cardId"]], False
    if run["kind"] in ("render", "revision"):
        ids = set(run["payload"]["cardIds"])
        if run["payload"].get("onlyUnfinished"):  # 이어하기는 이미 끝난 카드를 다시 올리지 않아요
            ids = {i for i in ids if entries.get(i, {}).get("status") != "done"}
        redraw = set(run["payload"].get("redraw", []))  # 부분 수정에서 그림도 다시 만들 카드
        return [(c, c["id"] in redraw) for c in storyboard["cards"] if c["id"] in ids], False
    if run["payload"].get("onlyUnfinished") and result:
        return [(c, not has_image(c)) for c in storyboard["cards"]
                if entries.get(c["id"], {}).get("status") != "done"], False
    return [(c, True) for c in storyboard["cards"]], True


def _texts(card: dict, layout: dict, today=None) -> dict:
    texts = {k: layout.get(k) if layout.get(k) is not None else card.get(k) for k in ("title", "keyLine", "body")}
    if card.get("notice") and today:  # 공고 카드의 마감 줄은 고친 본문이어도 렌더링하는 날 기준으로 앱이 다시 써요
        texts = {**texts, "body": support.refresh_body(texts.get("body") or "", card["notice"], today)}
    return texts


def _make_one(ctx: RunContext, tools: dict, renderer: Renderer, card: dict, total: int, draw: bool) -> None:
    with db.transaction() as conn:
        entry = next(c for c in repo.get_project(conn, ctx.project_id)["data"]["result"]["cards"]
                     if c["cardId"] == card["id"])
    project_dir = config.data_dir() / "projects" / ctx.project_id
    image = entry["image"]
    if draw:
        stem = project_dir / "results" / "images" / f"{card['id']}.v{entry['cardVersion']}"
        _update(ctx.run_id, _set_card(card["id"], status="generating_image"))
        ctx.report(f"그림 만드는 중: {card['order']}/{total} {card['title'][:30]}")
        plan = {**card["imagePlan"], "prompt": entry.get("imagePrompt") or card["imagePlan"]["prompt"]}
        record = _draw(ctx, tools, plan, card["order"], total, stem)
        dest: Path = record.pop("dest")
        image = {**record, "file": dest.relative_to(project_dir).as_posix()}
    _update(ctx.run_id, _set_card(card["id"], status="rendering", image=image))
    ctx.report(f"글자 올리는 중: {card['order']}/{total} {card['title'][:30]}")
    layout = entry.get("layout") or default_layout(card)
    today = now().date()
    texts = _texts(card, layout, today)
    out = renderer.render(
        out_stem=project_dir / "results" / "cards" / f"{card['id']}.v{entry['cardVersion']}",
        texts=texts, role=card["role"], layout=layout,
        bg=project_dir / image["file"] if image else None,
        disclose=bool(image) and str(image.get("origin", "")).startswith("generated"))
    _update(ctx.run_id, _set_card(
        card["id"], status="done", layout=layout, png=out["png"].relative_to(project_dir).as_posix(),
        checks={"layout": out["checks"]},
        render={"applied": out["applied"], "autoFixes": out["autoFixes"], "texts": texts,
                **({"ddayBase": today.isoformat()} if card.get("notice") else {})}))


def _fail(card_ids: list[str], err: AppError):
    def change(result: dict) -> dict:
        cards = [{**c, "status": "failed", "error": err.to_dict()} if c["cardId"] in card_ids else c
                 for c in result["cards"]]
        return {**result, "cards": cards}
    return change


def _run_cards(ctx: RunContext, targets: list[tuple[dict, bool]], tools: dict, total: int) -> None:
    renderer = Renderer()
    try:
        for i, (card, draw) in enumerate(targets):
            try:
                _make_one(ctx, tools, renderer, card, total, draw)
            except AppError as err:
                stop = err.code in STOP_CODES
                ids = [c["id"] for c, _ in targets[i:]] if stop else [card["id"]]
                _update(ctx.run_id, _fail(ids, err))
                ctx.report(f"카드 실패: {card['order']}/{total} — {err.message}")
                if stop:
                    break
    finally:
        renderer.close()


def _plan_revision(run: dict, project: dict, ctx: RunContext) -> dict:
    """고칠 문구를 받아 run에 저장해요. 이어하기 때는 저장한 문구를 다시 써요(엔진을 또 부르지 않아요)."""
    payload = run["payload"]
    edits = payload.get("edits") or revise.revise(ctx, project, payload["cardIds"], payload["instruction"])
    scope = payload.get("imageScope", "auto")
    redraw = [cid for cid, e in edits.items()
              if scope == "image" or (scope == "auto" and e["redrawImage"])]
    payload = {**payload, "edits": edits, "redraw": redraw}
    with db.transaction() as conn:
        repo.update_run(conn, run["id"], payload=payload)
    return {**run, "payload": payload}


def _apply_edits(storyboard: dict, edits: dict, redraw: list[str]):
    """고친 문구를 카드 배치(layout)에 넣어요. 그림을 다시 만들 카드에는 새 그림 요청을 남겨요."""
    plans = {c["id"]: c for c in storyboard["cards"]}

    def change(result: dict) -> dict:
        cards = []
        for c in result["cards"]:
            edit = edits.get(c["cardId"])
            if edit is None:
                cards.append(c)
                continue
            layout = c.get("layout") or default_layout(plans[c["cardId"]])
            now = _texts(plans[c["cardId"]], layout)
            texts = {k: edit[k] for k in revise.TEXT_FIELDS if edit.get(k) and edit[k] != now.get(k)}
            extra = {"imagePrompt": edit["imagePrompt"]} if c["cardId"] in redraw and edit.get("imagePrompt") else {}
            cards.append({**c, **extra, "revisionNote": edit["note"],
                          "layout": {**layout, **texts, "textEdited": bool(texts) or layout.get("textEdited", False)}})
        return {**result, "cards": cards}
    return change


def execute(run: dict, project: dict, ctx: RunContext) -> None:
    storyboard = project["data"]["storyboard"]
    if run["kind"] == "revision":
        run = _plan_revision(run, project, ctx)
    targets, fresh = _targets(run, storyboard, project["data"]["result"])
    _update(run["id"], _start_result(storyboard, {c["id"]: draw for c, draw in targets}, fresh))
    if run["kind"] == "revision":
        _update(run["id"], _apply_edits(storyboard, run["payload"]["edits"], run["payload"]["redraw"]))
    tools = _tools(project) if any(draw for _, draw in targets) else {}
    _run_cards(ctx, targets, tools, len(storyboard["cards"]))
    with db.transaction() as conn:
        if repo.get_run(conn, run["id"])["cancelRequested"]:
            return
        pipeline.finish_run(conn, run["id"], "succeeded")
        current = repo.get_project(conn, project["id"])
        if all(c["status"] == "done" for c in current["data"]["result"]["cards"]):
            repo.save_project(conn, {**current, "stage": "reviewing"})  # 6장 모두 글자까지 올렸으면 검수로
