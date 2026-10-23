"""스토리보드 승인 → 카드별 그림 만들기 (가짜 agy, 실제 호출 없음)."""

import hashlib
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import rid

FAKE = Path(__file__).parent / "fake_agy.py"
FAKE_CLAUDE = Path(__file__).parent / "fake_claude.py"


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    wrapper = tmp_path / "agy"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    claude = tmp_path / "claude"  # 대신 만들기(SVG)가 실제 claude를 부르지 않게 가짜를 연결해요
    claude.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n')
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    brain = tmp_path / "brain"
    brain.mkdir()
    for key, value in {
        "CARDNEWS_DATA_DIR": str(tmp_path / "data"), "CARDNEWS_ENGINE": "mock",
        "CARDNEWS_MOCK_DELAY": "0", "CARDNEWS_IMAGE_GEN": "agy",
        "CARDNEWS_AGY_BIN": str(wrapper), "CARDNEWS_AGY_BRAIN": str(brain),
        "CARDNEWS_AGY_WAIT": "0.3", "FAKE_AGY_BRAIN": str(brain),
        "FAKE_AGY_LOG": str(tmp_path / "agy-calls.jsonl"), "FAKE_AGY_PID": str(tmp_path / "agy.pid"),
        "CARDNEWS_CLAUDE_BIN": str(claude), "FAKE_CLAUDE_LOG": str(tmp_path / "claude-calls.jsonl"),
        "CARDNEWS_IMAGE_FALLBACK": "none",  # 대신 만들기는 그 테스트에서만 켜요
    }.items():
        monkeypatch.setenv(key, value)
    from cardnews import db
    from cardnews.app import app

    db.init_db()
    with TestClient(app) as client:
        client.tmp = tmp_path
        client.calls = lambda: [json.loads(l) for l in (tmp_path / "agy-calls.jsonl").read_text().splitlines()]
        yield client


def work():
    from cardnews import worker

    worker.run_pending()


def get(c, pid):
    return c.get(f"/api/projects/{pid}").json()


def to_storyboard(c):
    pid = c.post("/api/projects", json={"topic": "AI 최신소식"}).json()["projectId"]
    c.post(f"/api/projects/{pid}/research", json={"requestId": rid()})
    work()
    p = get(c, pid)
    v = c.post(f"/api/projects/{pid}/selection",
               json={"candidateIds": ["cand_1", "cand_2"], "version": p["version"]}).json()["version"]
    c.post(f"/api/projects/{pid}/deep-research", json={"version": v, "requestId": rid()})
    work()
    q = get(c, pid)["currentQuestion"]
    c.post(f"/api/projects/{pid}/answers", json={"questionId": q["id"], "version": q["version"],
                                                "answer": {"optionId": "dev"}, "requestId": rid()})
    work()
    return pid, get(c, pid)


def approve(c, pid, p):
    res = c.post(f"/api/projects/{pid}/approve", json={
        "stage": "storyboard", "version": p["storyboard"]["version"], "requestId": rid()})
    assert res.status_code == 202, res.text
    return res.json()["runId"]


def produced(c):
    pid, p = to_storyboard(c)
    approve(c, pid, p)
    work()
    return pid, get(c, pid)


# --- 그림 만들기 -----------------------------------------------------------------


def test_each_card_gets_a_verified_image(app_client):
    pid, p = produced(app_client)
    result = p["result"]
    assert p["stage"] == "producing" and p["lastRun"]["status"] == "succeeded"
    assert len(result["cards"]) == len(p["storyboard"]["cards"])
    for card in result["cards"]:
        assert card["status"] == "image_ready", card
        img = card["image"]
        assert img["tool"] == "agy 1.4.5" and img["origin"] == "generated"
        assert img["originalFormat"] == "jpeg" and img["originalSize"] == [896, 1200]
        assert img["conversationId"] and img["prompt"] and img["createdAt"]
        assert img["disclosure"] == "생성 이미지"
        # 앱이 자기 폴더로 복사했고, 원본과 같은 파일이에요
        local = app_client.tmp / "data" / "projects" / pid / img["file"]
        assert hashlib.sha256(local.read_bytes()).hexdigest() == img["sha256"]
        res = app_client.get(card["imageUrl"])
        assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"


def test_agy_is_called_safely_with_layout_rules(app_client):
    _, p = produced(app_client)
    calls = app_client.calls()
    assert len(calls) == len(p["storyboard"]["cards"])
    argv = calls[0]["argv"]
    assert "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    prompt = argv[argv.index("-p") + 1]
    assert "글자" in prompt and "4:5" in prompt and "위쪽" in prompt  # 첫 카드는 위쪽에 글자 자리
    assert "복사" in prompt  # 파일을 옮기거나 복사하지 말라고 해요


def test_one_card_failing_keeps_others(app_client, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    _, p = produced(app_client)
    statuses = [c["status"] for c in p["result"]["cards"]]
    assert statuses[1] == "failed" and statuses.count("image_ready") == len(statuses) - 1
    err = p["result"]["cards"][1]["error"]
    assert err["code"] == "IMAGE_FAILED" and "retry_card" in err["nextActions"]
    assert p["lastRun"]["status"] == "succeeded"


def test_retry_remakes_only_that_card(app_client, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    pid, p = produced(app_client)
    before = {c["cardId"]: c["image"] for c in p["result"]["cards"]}
    monkeypatch.delenv("FAKE_AGY_FAIL_ON")
    res = app_client.post(f"/api/projects/{pid}/cards/card_2/retry",
                          json={"resultVersion": p["result"]["version"], "requestId": rid()})
    assert res.status_code == 202, res.text
    work()
    p2 = get(app_client, pid)
    cards = {c["cardId"]: c for c in p2["result"]["cards"]}
    assert cards["card_2"]["status"] == "image_ready" and cards["card_2"]["cardVersion"] == 2
    assert p2["result"]["version"] == p["result"]["version"] + 1
    for cid, image in before.items():
        if cid != "card_2":
            assert cards[cid]["image"] == image and cards[cid]["cardVersion"] == 1


def test_retry_only_for_failed_cards(app_client):
    pid, p = produced(app_client)
    res = app_client.post(f"/api/projects/{pid}/cards/card_1/retry",
                          json={"resultVersion": p["result"]["version"], "requestId": rid()})
    assert res.json()["error"]["code"] == "STAGE_CONFLICT"


@pytest.mark.parametrize("scenario,code", [
    ("not_json", "IMAGE_FAILED"),   # 응답을 읽지 못함
    ("stale", "IMAGE_FAILED"),      # 호출 전 그림만 있음 → 새 그림 없음
    ("tiny", "IMAGE_FAILED"),       # 너무 작은 그림
])
def test_bad_results_are_failures_not_success(app_client, monkeypatch, scenario, code):
    monkeypatch.setenv("FAKE_AGY_SCENARIO", scenario)
    _, p = produced(app_client)
    assert {c["status"] for c in p["result"]["cards"]} == {"failed"}
    assert p["result"]["cards"][0]["error"]["code"] == code


def test_login_problem_stops_after_first_card(app_client, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_SCENARIO", "auth")
    _, p = produced(app_client)
    assert len(app_client.calls()) == 1  # 남은 카드는 부르지 않아요
    assert {c["error"]["code"] for c in p["result"]["cards"]} == {"AUTH_REQUIRED"}


def test_missing_agy(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_AGY_BIN", str(app_client.tmp / "nope"))
    _, p = produced(app_client)
    assert {c["error"]["code"] for c in p["result"]["cards"]} == {"TOOL_UNAVAILABLE"}


def test_cancel_kills_agy(app_client, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_SCENARIO", "slow")
    pid, p = to_storyboard(app_client)
    run_id = approve(app_client, pid, p)
    thread = threading.Thread(target=work)
    thread.start()
    pid_file = app_client.tmp / "agy.pid"
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    child = int(pid_file.read_text())
    assert app_client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    thread.join(timeout=10)
    assert not thread.is_alive()
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_files_outside_project_are_not_served(app_client):
    pid, _ = produced(app_client)
    for path in ("../../app.db", "%2e%2e/%2e%2e/app.db", "/etc/hosts"):
        assert app_client.get(f"/api/projects/{pid}/files/{path}").status_code == 404


def test_mock_projects_use_local_placeholder_images(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_GEN", "auto")  # 모의 엔진 프로젝트 → 모의 그림
    _, p = produced(app_client)
    card = p["result"]["cards"][0]
    assert card["status"] == "image_ready"
    assert card["image"]["origin"] == "mock" and card["image"]["originalFormat"] == "png"
    assert not (app_client.tmp / "agy-calls.jsonl").exists()


def test_each_card_version_keeps_its_own_file(app_client, monkeypatch):
    """다시 만든 카드가 예전 버전 파일을 덮어쓰지 않아야 해요 (PRD: 버전 보관)."""
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    pid, p = produced(app_client)
    first = {c["cardId"]: c for c in p["result"]["cards"]}
    assert first["card_1"]["image"]["file"].endswith("card_1.v1.jpg")
    monkeypatch.delenv("FAKE_AGY_FAIL_ON")
    app_client.post(f"/api/projects/{pid}/cards/card_2/retry",
                    json={"resultVersion": p["result"]["version"], "requestId": rid()})
    work()
    card_2 = {c["cardId"]: c for c in get(app_client, pid)["result"]["cards"]}["card_2"]
    assert card_2["image"]["file"].endswith("card_2.v2.jpg")
    files_on_disk = sorted(f.name for f in (app_client.tmp / "data" / "projects" / pid
                                            / "results" / "images").iterdir())
    assert "card_1.v1.jpg" in files_on_disk and "card_2.v2.jpg" in files_on_disk


def interrupt_after_two_cards(c, pid):
    """카드 1·2만 끝난 채 서버가 꺼진 상황을 DB로 만들어요."""
    from cardnews import db, repo, worker

    with db.transaction() as conn:
        project = repo.get_project(conn, pid)
        run = repo.last_run(conn, pid)
        result = project["data"]["result"]
        cards = [{**card, "status": "image_ready" if i < 2 else ("generating_image" if i == 2 else "pending"),
                  "image": card["image"] if i < 2 else None} for i, card in enumerate(result["cards"])]
        repo.save_project(conn, {**project, "data": {**project["data"], "result": {**result, "cards": cards}}})
        repo.update_run(conn, run["id"], status="running", dispatch=False)
    worker.recover_interrupted()
    return run["id"]


def test_restart_marks_unfinished_cards_as_interrupted(app_client):
    pid, _ = produced(app_client)
    interrupt_after_two_cards(app_client, pid)
    cards = get(app_client, pid)["result"]["cards"]
    assert [c["status"] for c in cards[:2]] == ["image_ready", "image_ready"]
    assert {c["status"] for c in cards[2:]} == {"failed"}  # "그림 만드는 중"으로 남지 않아요
    assert {c["error"]["code"] for c in cards[2:]} == {"INTERRUPTED"}


def test_continue_after_restart_makes_only_unfinished_cards(app_client):
    pid, p = produced(app_client)
    before = {c["cardId"]: c["image"] for c in p["result"]["cards"][:2]}
    run_id = interrupt_after_two_cards(app_client, pid)
    calls_before = len(app_client.calls())
    res = app_client.post(f"/api/runs/{run_id}/resume", json={"mode": "continue", "requestId": rid()})
    assert res.status_code == 202, res.text
    work()
    cards = {c["cardId"]: c for c in get(app_client, pid)["result"]["cards"]}
    total = len(cards)
    assert len(app_client.calls()) - calls_before == total - 2  # 끝나지 않은 카드만 다시 만들어요
    assert all(c["status"] == "image_ready" for c in cards.values())
    for cid, image in before.items():
        assert cards[cid]["image"] == image  # 끝난 카드는 그대로예요


def test_restart_from_scratch_remakes_all_cards(app_client):
    pid, _ = produced(app_client)
    run_id = interrupt_after_two_cards(app_client, pid)
    calls_before = len(app_client.calls())
    app_client.post(f"/api/runs/{run_id}/resume", json={"mode": "restart", "requestId": rid()})
    work()
    total = len(get(app_client, pid)["storyboard"]["cards"])
    assert len(app_client.calls()) - calls_before == total  # 처음부터는 모든 카드를 다시 만들어요


def test_cancel_marks_unfinished_cards(app_client, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_SCENARIO", "slow")
    pid, p = to_storyboard(app_client)
    run_id = approve(app_client, pid, p)
    thread = threading.Thread(target=work)
    thread.start()
    pid_file = app_client.tmp / "agy.pid"
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    app_client.post(f"/api/runs/{run_id}/cancel")
    thread.join(timeout=10)
    cards = get(app_client, pid)["result"]["cards"]
    assert {c["status"] for c in cards} == {"failed"}
    assert {c["error"]["code"] for c in cards} == {"CANCELLED"}


# --- agy가 못 만들면 Claude CLI가 SVG로 대신 만들기 ----------------------------------


def svg_calls(c) -> list[list[str]]:
    log = c.tmp / "claude-calls.jsonl"
    calls = [json.loads(l)["argv"] for l in log.read_text().splitlines()] if log.exists() else []
    return [a for a in calls if json.loads(a[a.index("--json-schema") + 1])["title"] == "SvgImageOutput"]


def test_failed_agy_card_is_drawn_as_svg_by_claude(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_FALLBACK", "claude")
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    pid, p = produced(app_client)
    cards = p["result"]["cards"]
    assert {c["status"] for c in cards} == {"image_ready"}
    card_2 = cards[1]["image"]
    assert card_2["origin"] == "generated-svg" and card_2["originalFormat"] == "svg"
    assert card_2["originalSize"] == [1080, 1350] and card_2["file"].endswith("card_2.v1.svg")
    assert card_2["fallbackFrom"]["tool"] == "agy" and card_2["fallbackFrom"]["code"] == "IMAGE_FAILED"
    assert cards[0]["image"]["origin"] == "generated"  # 나머지는 agy 그림 그대로
    assert len(svg_calls(app_client)) == 1
    res = app_client.get(cards[1]["imageUrl"])
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in res.headers["content-security-policy"]  # SVG 안 스크립트 실행 막기
    assert "<text" not in res.text and "<script" not in res.text


def test_svg_card_can_be_redrawn_with_agy(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_FALLBACK", "claude")
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    pid, p = produced(app_client)
    monkeypatch.delenv("FAKE_AGY_FAIL_ON")
    res = app_client.post(f"/api/projects/{pid}/cards/card_2/retry",
                          json={"resultVersion": p["result"]["version"], "requestId": rid()})
    assert res.status_code == 202, res.text
    work()
    card_2 = get(app_client, pid)["result"]["cards"][1]
    assert card_2["cardVersion"] == 2 and card_2["image"]["origin"] == "generated"
    assert "fallbackFrom" not in card_2["image"]


def test_agy_prompt_forbids_commands():
    from cardnews.images import agy
    prompt = agy.image_prompt({"prompt": "열쇠 하나", "textArea": "top"}, 1, 6)
    assert "명령을 실행하지 말고" in prompt


def test_svg_prompt_keeps_same_style_and_no_text(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_FALLBACK", "claude")
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 1/")
    produced(app_client)
    argv = svg_calls(app_client)[0]
    prompt = argv[argv.index("-p") + 1]
    from cardnews.images import agy

    assert agy.STYLE in prompt and "위쪽" in prompt and "<text>" in prompt  # 같은 그림체·여백·글자 금지
    assert "--resume" not in argv  # 조사 세션과 섞지 않아요
    assert "WebSearch" in argv[argv.index("--disallowedTools") + 1:]


def test_missing_agy_draws_every_card_as_svg(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_FALLBACK", "claude")
    monkeypatch.setenv("CARDNEWS_AGY_BIN", str(app_client.tmp / "nope"))
    _, p = produced(app_client)
    cards = p["result"]["cards"]
    assert {c["image"]["origin"] for c in cards} == {"generated-svg"}
    assert {c["image"]["fallbackFrom"]["code"] for c in cards} == {"TOOL_UNAVAILABLE"}


def test_both_failing_shows_both_reasons(app_client, monkeypatch):
    monkeypatch.setenv("CARDNEWS_IMAGE_FALLBACK", "claude")
    monkeypatch.setenv("FAKE_AGY_FAIL_ON", "카드 2/")
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "svg_bad")
    _, p = produced(app_client)
    card_2 = p["result"]["cards"][1]
    assert card_2["status"] == "failed"
    assert "agy" in card_2["error"]["message"] and "Claude CLI" in card_2["error"]["message"]
