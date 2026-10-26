"""지원사업·공모전 작업 흐름 (모의 엔진·가짜 agy·모의 렌더러). 기존 최신 소식 흐름은 test_flow.py가 그대로 확인해요."""

import io
import re
import zipfile

from tests.conftest import rid
from tests.test_images import app_client, get, work  # noqa: F401  (app_client는 fixture)


def create(c, topic="IT·AI 창업 지원사업과 공모전", workflow="support"):
    res = c.post("/api/projects", json={"topic": topic, "workflow": workflow})
    assert res.status_code == 201, res.text
    pid = res.json()["projectId"]
    assert c.post(f"/api/projects/{pid}/research", json={"requestId": rid()}).status_code == 202
    work()
    return pid, get(c, pid)


def select(c, pid, p, ids):
    return c.post(f"/api/projects/{pid}/selection", json={"candidateIds": ids, "version": p["version"]})


def to_storyboard(c, count=4, upcoming=False):
    pid, p = create(c)
    cands = p["research"]["candidates"]
    ids = [x["id"] for x in cands[:count]]
    if upcoming:  # 곧 열릴 예정 공고도 하나 넣어요
        ids = ids[:count - 1] + [next(x["id"] for x in cands if x["group"] == "upcoming")]
    v = select(c, pid, p, ids).json()["version"]
    assert c.post(f"/api/projects/{pid}/deep-research", json={"version": v, "requestId": rid()}).status_code == 202
    work()
    return pid, get(c, pid)


def test_workflow_defaults_to_news(app_client):
    pid = app_client.post("/api/projects", json={"topic": "AI 최신소식"}).json()["projectId"]
    p = get(app_client, pid)
    assert p["workflow"] == "news" and p["maxSelection"] == 3
    bad = app_client.post("/api/projects", json={"topic": "x", "workflow": "other"})
    assert bad.status_code == 422


def test_support_research_groups_candidates_and_excludes(app_client):
    pid, p = create(app_client)
    r = p["research"]
    assert p["workflow"] == "support" and p["maxSelection"] == 7 and p["stage"] == "selecting"
    assert r["period"]["months"] == 6 and r["period"]["from"][:10] == r["requestedAt"][:10]
    groups = [c["group"] for c in r["candidates"]]
    assert groups == sorted(groups, key=["open", "upcoming"].index)  # 지금 지원 가능이 먼저
    assert {"open", "upcoming"} <= set(groups)
    assert all(any(s["type"] == "official" for s in c["sources"]) for c in r["candidates"])
    assert len(r["excluded"]) >= 3 and all(e["reason"] for e in r["excluded"])
    confirmed = [c for c in r["candidates"] if c["dateStatus"] == "confirmed"]
    assert confirmed and all(re.fullmatch(r"D-\d+|오늘 마감", c["dday"]) for c in confirmed)
    amounts = [c["amountKRW"] for c in r["candidates"] if c["group"] == "open" and c["amountKRW"]]
    assert amounts == sorted(amounts, reverse=True)


def test_few_support_results_ask_to_broaden_then_rerun(app_client):
    pid, p = create(app_client, topic="적음 제주 우주 게임 1인 창업 지원사업")
    q = p["currentQuestion"]
    assert q["id"] == "q_broaden" and "분야나 지역을 넓혀서" in q["prompt"]
    assert [o["label"] for o in q["options"]] == ["넓혀서 다시 찾기", "이대로 보기"]
    assert "6개월" not in q["options"][0]["label"]  # 기간은 넓히지 않아요
    res = app_client.post(f"/api/projects/{pid}/answers", json={
        "questionId": q["id"], "version": q["version"], "answer": {"optionId": "broaden"}, "requestId": rid()})
    assert res.status_code == 202, res.text
    work()
    p2 = get(app_client, pid)
    assert p2["stage"] == "selecting" and p2["currentQuestion"] is None
    assert p2["research"]["broadened"] is True and len(p2["research"]["candidates"]) >= 3
    assert p2["research"]["period"]["months"] == 6


def test_few_support_results_keep_as_is(app_client):
    pid, p = create(app_client, topic="적음 제주 우주 게임")
    q = p["currentQuestion"]
    app_client.post(f"/api/projects/{pid}/answers", json={
        "questionId": q["id"], "version": q["version"], "answer": {"optionId": "keep"}, "requestId": rid()})
    work()
    p2 = get(app_client, pid)
    assert p2["stage"] == "selecting" and len(p2["research"]["candidates"]) < 3


def test_support_selection_allows_seven(app_client):
    pid, p = create(app_client)
    ids = [c["id"] for c in p["research"]["candidates"]]
    assert len(ids) >= 7
    assert select(app_client, pid, p, ids[:7]).status_code == 200
    p = get(app_client, pid)
    over = select(app_client, pid, p, ids[:7] + ["cand_99"])
    assert over.json()["error"]["code"] == "VALIDATION_ERROR"


def test_support_storyboard_one_card_per_notice_with_app_dday(app_client):
    pid, p = to_storyboard(app_client, count=4)
    cards = p["storyboard"]["cards"]
    assert p["stage"] == "storyboard_review" and 3 <= len(cards) <= 9
    assert cards[0]["role"] == "cover" and cards[-1]["role"] == "summary"
    notices = [c for c in cards if c.get("notice")]
    assert len(notices) == 4
    for c in notices:
        lines = c["body"].split("\n")
        assert lines[0].startswith("대상: ") and lines[2].startswith("신청: ")
        if c["notice"]["dateStatus"] == "confirmed":
            assert re.search(r"\((D-\d+|오늘 마감) · \d+/\d+ 기준\)", lines[1])
        if c["notice"]["dateStatus"] == "expected":
            assert "예정(미확정)" in lines[1] and "D-" not in lines[1]
    assert cards[-1]["keyLine"].startswith("지금 지원 가능 ")


def test_support_export_checks_deadline_dday_amount(app_client):
    pid, p = to_storyboard(app_client, count=4, upcoming=True)
    app_client.post(f"/api/projects/{pid}/approve", json={
        "stage": "storyboard", "version": p["storyboard"]["version"], "requestId": rid()})
    work()
    p = get(app_client, pid)
    assert p["stage"] == "reviewing", p["lastRun"]
    res = app_client.post(f"/api/projects/{pid}/approve", json={
        "stage": "final", "version": p["result"]["version"], "requestId": rid()})
    assert res.status_code == 200, res.text
    work()
    view = app_client.get(f"/api/projects/{pid}/exports").json()
    items = view["verify"]["items"]
    checks = {i["check"] for i in items}
    assert {"마감일", "D-day", "금액", "예정 공고"} <= checks
    assert view["verify"]["fail"] == 0, [i for i in items if i["status"] == "fail"]
    assert not any(i["check"] == "날짜" for i in items)  # 뉴스 게시일 검사는 쓰지 않아요
    zip_url = next(f["url"] for f in view["files"] if f["name"].endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(app_client.get(zip_url).content)) as zf:
        text = zf.read("sources.md").decode()
    assert "오늘부터 6개월" in text and "마감:" in text


URL = "https://a.example.go.kr/n"


def _plan(**extra):
    notice = {"dateStatus": "confirmed", "deadline": "2026-11-14", "officialUrl": URL,
              "amountText": "최대 1억 원", "basis": "", **extra}
    return {"order": 2, "role": "body", "notice": notice, "keyLine": notice["amountText"], "candidateId": "cand_1"}


def test_support_verify_fails_on_wrong_dday_and_expired():
    from datetime import date

    from cardnews import verify_export

    today = date(2026, 10, 26)
    plan = _plan()
    wrong = verify_export.support_dday(plan, {"render": {"texts": {"body": "마감: 11월 14일 (D-3 · 10/26 기준)"},
                                                       "ddayBase": "2026-10-26"}}, today)
    assert wrong["status"] == "fail"
    later = verify_export.support_dday(plan, {"render": {"texts": {"body": "마감: 11월 14일 (D-19 · 10/26 기준)"},
                                                       "ddayBase": "2026-10-26"}}, date(2026, 10, 28))
    assert later["status"] == "needs_check" and "다시 계산" in later["detail"]
    official = {URL}
    assert verify_export.support_deadline(plan, {URL}, date(2026, 11, 20), official)["status"] == "fail"
    assert verify_export.support_deadline(plan, set(), today, official)["status"] == "needs_check"
    assert verify_export.support_deadline(plan, {URL}, today, official)["status"] == "pass"
    # 엔진이 열어 봤어도 공식 출처가 아니면(모음 사이트 등) 통과가 아니에요
    assert verify_export.support_deadline(plan, {URL}, today, set())["status"] == "needs_check"


def test_support_amount_must_be_in_official_facts():
    from cardnews import verify_export

    card = {"render": {"texts": {"keyLine": "최대 1억 원"}}}
    good = [{"candidateId": "cand_1", "facts": [{"text": "지원 금액은 최대 1억 원이에요", "sourceUrls": [URL]}]}]
    made_up = [{"candidateId": "cand_1", "facts": [{"text": "지원 금액은 최대 5천만 원", "sourceUrls": [URL]}]}]
    blog_only = [{"candidateId": "cand_1", "facts": [{"text": "최대 1억 원", "sourceUrls": ["https://blog.example.com/a"]}]}]
    args = ({URL}, {URL})
    assert verify_export.support_amount(_plan(), card, *args, good)["status"] == "pass"
    assert verify_export.support_amount(_plan(), card, *args, made_up)["status"] == "needs_check"
    assert verify_export.support_amount(_plan(), card, *args, blog_only)["status"] == "needs_check"


def test_support_expected_and_rolling_rechecked_at_export():
    from datetime import date

    from cardnews import verify_export

    exp = _plan(dateStatus="expected", deadline=None, openMonth="2026-09", basis="작년 공고")
    card = {"render": {"texts": {"body": "열림: 2026년 9월 예정(미확정)"}}}
    assert verify_export.support_expected(exp, card, {URL}, date(2026, 10, 26), {URL})["status"] == "fail"
    ok = _plan(dateStatus="expected", deadline=None, openMonth="2027-01", basis="작년 공고")
    card2 = {"render": {"texts": {"body": "열림: 2027년 1월 예정(미확정)"}}}
    assert verify_export.support_expected(ok, card2, set(), date(2026, 10, 26), {URL})["status"] == "needs_check"
    assert verify_export.support_expected(ok, card2, {URL}, date(2026, 10, 26), {URL})["status"] == "pass"
    roll = _plan(dateStatus="rolling", deadline=None)
    items = verify_export._support_checks(roll, {"render": {"texts": {"body": "마감: 상시 모집 D-3"}}}, {URL},
                                          date(2026, 10, 26), {URL}, [])
    assert any(i["check"] == "D-day" and i["status"] == "fail" for i in items)


def test_news_flow_unchanged_by_support(app_client):
    pid = app_client.post("/api/projects", json={"topic": "AI 최신소식"}).json()["projectId"]
    app_client.post(f"/api/projects/{pid}/research", json={"requestId": rid()})
    work()
    p = get(app_client, pid)
    assert p["research"]["period"]["days"] == 7 and "months" not in p["research"]["period"]
    assert all("group" not in c for c in p["research"]["candidates"])


def test_revised_notice_card_keeps_app_dday_line(app_client):
    pid, p = to_storyboard(app_client, count=3)
    app_client.post(f"/api/projects/{pid}/approve", json={
        "stage": "storyboard", "version": p["storyboard"]["version"], "requestId": rid()})
    work()
    p = get(app_client, pid)
    res = app_client.post(f"/api/projects/{pid}/revisions", json={
        "cardIds": ["card_2"], "instruction": "2번 본문을 짧게", "imageScope": "text",
        "version": p["result"]["version"], "requestId": rid()})
    assert res.status_code == 202, res.text
    work()
    card = next(c for c in get(app_client, pid)["result"]["cards"] if c["cardId"] == "card_2")
    assert card["layout"]["textEdited"] is True
    body = card["render"]["texts"]["body"]
    assert re.search(r"마감: .*\((D-\d+|오늘 마감) · \d+/\d+ 기준\)", body), body
    assert body.count("기준)") == 1
