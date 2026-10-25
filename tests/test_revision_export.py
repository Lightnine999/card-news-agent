"""고른 카드만 글로 고치기 → 최종 승인 → 내보내기 → 내보낸 파일 검사 (모의 엔진·가짜 agy·모의 렌더러)."""

import io
import json
import zipfile

import pytest

from tests.conftest import rid
from tests.test_images import app_client, get, produced, work  # noqa: F401  (app_client는 fixture)


def revise(c, pid, p, card_ids, instruction="3번 카드 본문을 두 문장으로 줄여 줘", scope="auto"):
    return c.post(f"/api/projects/{pid}/revisions", json={
        "cardIds": card_ids, "instruction": instruction, "imageScope": scope,
        "version": p["result"]["version"], "requestId": rid()})


def approve_final(c, pid, p):
    return c.post(f"/api/projects/{pid}/approve",
                  json={"stage": "final", "version": p["result"]["version"], "requestId": rid()})


def approved(c):
    pid, p = produced(c)
    res = approve_final(c, pid, p)
    assert res.status_code == 200, res.text
    work()
    return pid, get(c, pid)


# --- 고른 카드만 고치기 ---------------------------------------------------------------


def test_text_revision_changes_only_chosen_card_without_agy(app_client):
    pid, p = produced(app_client)
    before = {c["cardId"]: c for c in p["result"]["cards"]}
    agy_calls = len(app_client.calls())
    assert revise(app_client, pid, p, ["card_3"], scope="text").status_code == 202
    work()
    p2 = get(app_client, pid)
    cards = {c["cardId"]: c for c in p2["result"]["cards"]}
    assert len(app_client.calls()) == agy_calls
    assert cards["card_3"]["cardVersion"] == 2 and cards["card_3"]["layout"]["textEdited"] is True
    assert cards["card_3"]["image"] == before["card_3"]["image"] and cards["card_3"]["revisionNote"]
    for cid, card in before.items():
        if cid != "card_3":
            assert cards[cid]["png"] == card["png"] and cards[cid]["cardVersion"] == 1
    assert p2["stage"] == "reviewing" and p2["lastRun"]["kind"] == "revision"


def test_image_scope_redraws_only_that_card(app_client):
    pid, p = produced(app_client)
    agy_calls = len(app_client.calls())
    assert revise(app_client, pid, p, ["card_2"], scope="image").status_code == 202
    work()
    cards = {c["cardId"]: c for c in get(app_client, pid)["result"]["cards"]}
    assert len(app_client.calls()) == agy_calls + 1
    assert cards["card_2"]["image"]["file"].endswith("card_2.v2.jpg")
    assert cards["card_1"]["image"]["file"].endswith("card_1.v1.jpg")


def test_auto_scope_follows_engine_decision(app_client):
    pid, p = produced(app_client)
    agy_calls = len(app_client.calls())
    revise(app_client, pid, p, ["card_4"], instruction="4번 카드 그림이 어색해. 다시 그려 줘")
    work()
    assert len(app_client.calls()) == agy_calls + 1  # 모의 수정기는 지시에 "그림"이 있으면 다시 그려요


def test_revision_requires_known_cards_and_instruction(app_client):
    pid, p = produced(app_client)
    assert revise(app_client, pid, p, ["card_99"]).json()["error"]["code"] == "VALIDATION_ERROR"
    assert revise(app_client, pid, p, ["card_1"], instruction="   ").status_code == 422
    assert revise(app_client, pid, p, []).status_code == 422


# --- 최종 승인 -----------------------------------------------------------------------


def test_final_approval_is_blocked_by_failed_layout_check(app_client):
    from cardnews import db, repo

    pid, p = produced(app_client)
    with db.transaction() as conn:
        project = repo.get_project(conn, pid)
        result = project["data"]["result"]
        cards = [{**c, "checks": {"layout": {**c["checks"]["layout"], "status": "fail"}}} if c["cardId"] == "card_2" else c
                 for c in result["cards"]]
        repo.save_project(conn, {**project, "data": {**project["data"], "result": {**result, "cards": cards}}})
    res = approve_final(app_client, pid, p)
    assert res.status_code == 409 and res.json()["error"]["details"]["cards"] == ["card_2"]


def test_revision_after_approval_clears_it(app_client):
    pid, p = approved(app_client)
    assert p["stage"] == "final_approved" and p["finalApproval"] and p["exportsReady"] is True
    assert revise(app_client, pid, p, ["card_3"], scope="text").status_code == 202
    p2 = get(app_client, pid)
    assert p2["finalApproval"] is None and p2["stage"] == "reviewing" and p2["exportsReady"] is False
    assert app_client.get(f"/api/projects/{pid}/exports").json()["error"]["code"] == "STAGE_CONFLICT"


def test_layout_change_after_approval_clears_it(app_client):
    pid, p = approved(app_client)
    res = app_client.post(f"/api/projects/{pid}/cards/card_1/layout", json={
        "resultVersion": p["result"]["version"], "layout": {"textArea": "bottom"}, "requestId": rid()})
    assert res.status_code == 202
    assert get(app_client, pid)["finalApproval"] is None


def test_exports_are_refused_before_approval(app_client):
    pid, _ = produced(app_client)
    assert app_client.get(f"/api/projects/{pid}/exports").json()["error"]["code"] == "STAGE_CONFLICT"


# --- 내보내기와 검사 -------------------------------------------------------------------


def test_export_files_and_zip(app_client):
    pid, p = approved(app_client)
    view = app_client.get(f"/api/projects/{pid}/exports").json()
    names = {f["name"] for f in view["files"]}
    total = len(p["storyboard"]["cards"])
    assert {f"cards/card_{i:02d}.png" for i in range(1, total + 1)} <= names
    assert {"sources.md", "image-credits.md", "verify.md", f"cardnews_{pid}_v{view['resultVersion']}.zip"} <= names
    zip_url = next(f["url"] for f in view["files"] if f["name"].endswith(".zip"))
    res = app_client.get(zip_url)
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert len([n for n in zf.namelist() if n.startswith("cards/")]) == total
        sources_md = zf.read("sources.md").decode()
        credits = zf.read("image-credits.md").decode()
    assert "조사 기준 시각" in sources_md and "## 카드 1." in sources_md
    assert "생성 이미지" in credits and "요청 문장" in credits


def test_download_only_listed_files(app_client):
    pid, p = approved(app_client)
    v = p["finalApproval"]["resultVersion"]
    assert app_client.get(f"/api/projects/{pid}/exports/v{v}/broken.zip").status_code == 404
    assert app_client.get(f"/api/projects/{pid}/exports/v{v}/../app.db").status_code == 404
    assert app_client.get(f"/api/projects/{pid}/exports/v{v + 9}/sources.md").status_code == 404


def test_verify_never_marks_unchecked_items_as_pass(app_client):
    pid, p = approved(app_client)
    report = app_client.get(f"/api/projects/{pid}/exports").json()["verify"]
    items = report["items"]
    by = lambda check: [i for i in items if i["check"] == check]  # noqa: E731
    assert by("누락")[0]["status"] == "pass"
    assert {i["status"] for i in by("크기")} == {"pass"}
    assert {i["status"] for i in by("글자 잘림")} == {"pass"}  # 렌더링 넘침 없음 + 같은 파일
    # 모의 엔진은 출처를 열어 보지 않아요 → 통과가 아니라 '사용자 확인 필요'
    assert all(i["status"] != "pass" for i in by("출처"))
    assert all(i["whatToCheck"] for i in items if i["status"] != "pass")
    assert any(i["target"] == "전체" and "지금도 열리는지" in i["detail"] for i in by("출처"))
    assert report["needs_check"] == sum(1 for i in items if i["status"] == "needs_check")


def test_verify_catches_missing_card_and_date_out_of_period(app_client):
    from cardnews import export, verify_export, db, repo, config

    pid, p = approved(app_client)
    with db.transaction() as conn:
        project = repo.get_project(conn, pid)
    data = project["data"]
    cand = data["research"]["candidates"][0]
    url = cand["sources"][0]["url"]
    old = {**cand, "publishedAt": "2001-01-01"}
    cands = [old, *data["research"]["candidates"][1:]]
    plans = [{**c, "sourceUrls": [url], "keyLine": "1999년 3월 4일에 바뀌었어요"} if c["id"] == "card_2" else c
             for c in data["storyboard"]["cards"]]
    project = {**project, "data": {**data, "research": {**data["research"], "candidates": cands},
                                   "storyboard": {**data["storyboard"], "cards": plans}}}
    out, listed = export.build(project, data["finalApproval"]["resultVersion"])
    zip_path = out / listed[-1]["name"]
    with zipfile.ZipFile(zip_path) as zf, zipfile.ZipFile(out / "broken.zip", "w") as broken:
        for n in zf.namelist():
            if n != "cards/card_03.png":
                broken.writestr(n, zf.read(n))
    report = verify_export.verify(project, out, out / "broken.zip")
    items = report["items"]
    assert any(i["check"] == "누락" and i["status"] == "fail" and "card_03" in i["detail"] for i in items)
    card2_date = next(i for i in items if i["check"] == "날짜" and i["target"] == "카드 2")
    assert card2_date["status"] == "fail" and "2001-01-01" in card2_date["detail"]


def test_verify_flags_text_date_not_in_research(app_client):
    from cardnews import verify_export

    data = {"research": {"candidates": [{"title": "t", "summary": "2026년 10월 22일 발표", "publishedAt": None}]},
            "researchNotes": []}
    evidence = verify_export._evidence_dates(data)
    plan = {"order": 1, "role": "body", "title": "a", "keyLine": "10월 22일 발표", "body": "3월 5일에 시작", "sourceUrls": []}
    item = verify_export._dates(plan, {}, {}, {**data, "research": {**data["research"], "requestedAt": "x",
                                                                     "period": {"from": "2026-10-16", "to": "2026-10-23"}}},
                                evidence)
    assert item["status"] == "needs_check" and "3월 5일" in item["detail"] and "10월 22일" not in item["detail"]


@pytest.mark.parametrize("scenario", ["ok"])
def test_claude_revision_args_have_no_tools_and_no_session(app_client, monkeypatch, scenario, tmp_path):
    from cardnews import revise as R
    from cardnews.engines.base import RunContext

    calls = []
    monkeypatch.setattr(R.claude_cli, "run_claude", lambda ctx, args, step: calls.append((args, step)) or {
        "structured_output": {"cards": [
            {"cardId": "card_3", "title": "t", "keyLine": "k", "body": "b", "redrawImage": False,
             "imagePrompt": None, "note": "n"},
            {"cardId": "card_1", "title": "x", "keyLine": "x", "body": None, "redrawImage": True,
             "imagePrompt": "p", "note": "고르지 않은 카드"}]}})
    pid, p = produced(app_client)
    from cardnews import db, repo
    with db.transaction() as conn:
        project = {**repo.get_project(conn, pid), "isMock": False}
    ctx = RunContext(run_id="r", project_id=pid, topic="t", session_id=None, run_dir=tmp_path,
                     report=lambda m: None, check_cancel=lambda: None)
    edits = R.revise(ctx, project, ["card_3"], "3번 본문을 줄여 줘")
    assert set(edits) == {"card_3"}  # 고르지 않은 카드는 버려요
    args, step = calls[0]
    assert step == "revision" and "--no-session-persistence" in args and "--resume" not in args
    assert "WebSearch" in args[args.index("--disallowedTools"):]
    assert json.loads(args[args.index("--json-schema") + 1])["title"] == "RevisionOutput"


def test_edited_cards_and_claim_support_need_user_check(app_client):
    pid, p = produced(app_client)
    revise(app_client, pid, p, ["card_3"], scope="text")
    work()
    p = get(app_client, pid)
    approve_final(app_client, pid, p)
    work()
    items = app_client.get(f"/api/projects/{pid}/exports").json()["verify"]["items"]
    assert any(i["target"] == "카드 3" and "고친 문구" in i["detail"] and i["status"] == "needs_check" for i in items)
    assert any(i["target"] == "전체" and "원문 내용과 맞는지" in i["detail"] for i in items)


# --- 검토에서 나온 경우들 ----------------------------------------------------------


def _date_item(key_line, body="", urls=(), index=None, candidates=()):
    from cardnews import verify_export

    data = {"research": {"candidates": list(candidates), "requestedAt": "2026-10-23T12:00:00+09:00",
                         "period": {"from": "2026-10-16T12:00:00+09:00", "to": "2026-10-23T12:00:00+09:00"}},
            "researchNotes": [{"facts": [{"text": "2026년 10월 22일 발표"}], "limits": []}]}
    plan = {"order": 2, "role": "body", "title": "t", "keyLine": key_line, "body": body, "sourceUrls": list(urls)}
    return verify_export._dates(plan, {}, index or {}, data, verify_export._evidence_dates(data))


def test_date_without_anything_to_compare_is_not_pass():
    assert _date_item("날짜 없는 문장")["status"] == "needs_check"


def test_unknown_source_date_is_not_pass():
    assert _date_item("10월 22일 발표", urls=["https://x.example.com/a"])["status"] == "needs_check"


@pytest.mark.parametrize("text", ["10/24 출시", "2026.10.24 발표", "2026-10-24 공개", "10월 23~25일 행사",
                                  "10월 말 출시", "다음 달 1일", "올해 3분기"])
def test_other_date_forms_need_check(text):
    item = _date_item(text)
    assert item["status"] == "needs_check", item


def test_known_date_passes_when_compared():
    from cardnews import sources

    url = "https://a.example.com/x"
    index = {sources.normalize(url): {"publishedAt": "2026-10-22", "opened": True}}
    assert _date_item("10월 22일 발표", urls=[url], index=index)["status"] == "pass"


def test_cancelled_export_releases_approval(app_client):
    pid, p = produced(app_client)
    res = approve_final(app_client, pid, p)
    run_id = res.json()["runId"]
    assert app_client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    p2 = get(app_client, pid)
    assert p2["stage"] == "reviewing" and p2["finalApproval"] is None
    assert approve_final(app_client, pid, p2).status_code == 200  # 다시 승인할 수 있어요


def test_engine_must_return_every_chosen_card(app_client, monkeypatch, tmp_path):
    from cardnews import revise as R, db, repo
    from cardnews.engines.base import RunContext
    from cardnews.errors import AppError

    monkeypatch.setattr(R.claude_cli, "run_claude", lambda ctx, args, step: {"structured_output": {"cards": [
        {"cardId": "card_3", "title": "t", "keyLine": "k", "body": "b", "redrawImage": False,
         "imagePrompt": None, "note": "n"}]}})
    pid, _ = produced(app_client)
    with db.transaction() as conn:
        project = {**repo.get_project(conn, pid), "isMock": False}
    ctx = RunContext(run_id="r", project_id=pid, topic="t", session_id=None, run_dir=tmp_path,
                     report=lambda m: None, check_cancel=lambda: None)
    with pytest.raises(AppError) as err:
        R.revise(ctx, project, ["card_3", "card_4"], "줄여 줘")
    assert err.value.code == "ENGINE_OUTPUT_INVALID"


def test_verify_files_are_downloadable_and_in_zip(app_client):
    pid, p = approved(app_client)
    view = app_client.get(f"/api/projects/{pid}/exports").json()
    names = {f["name"] for f in view["files"]}
    assert {"verify.json", "verify.md"} <= names
    zip_url = next(f["url"] for f in view["files"] if f["name"].endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(app_client.get(zip_url).content)) as zf:
        assert "verify.md" in zf.namelist()


def test_date_without_official_date_needs_check():
    from cardnews import sources

    url = "https://news.example.com/a"
    index = {sources.normalize(url): {"publishedAt": "2026-10-21", "opened": False, "candidateId": "cand_3"}}
    item = _date_item("보도에 따르면 공개됐어요", urls=[url], index=index)
    assert item["status"] == "needs_check" and "공식 발표 날짜" in item["detail"]


def test_date_with_official_date_passes():
    from cardnews import sources, verify_export

    url = "https://deepmind.example.com/blog"
    index = {sources.normalize(url): {"publishedAt": "2026-10-22", "opened": True, "candidateId": "cand_7"}}
    data = {"research": {"candidates": [], "requestedAt": "x",
                         "period": {"from": "2026-10-18T12:00:00+09:00", "to": "2026-10-25T12:00:00+09:00"}},
            "researchNotes": [{"candidateId": "cand_7", "facts": [], "limits": [], "officialDate": "2026-10-22"}]}
    plan = {"order": 6, "role": "body", "title": "t", "keyLine": "지도를 공개했어요", "body": "", "sourceUrls": [url]}
    item = verify_export._dates(plan, {}, index, data, verify_export._evidence_dates(data))
    assert item["status"] == "pass" and "공식 발표일 2026-10-22" in item["detail"]
