"""Claude CLI 엔진을 가짜 claude 실행 파일로 확인해요 (실제 호출 없음)."""

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
from tests.fake_claude import SESSION

FAKE = Path(__file__).parent / "fake_claude.py"


@pytest.fixture
def cli(tmp_path, monkeypatch):
    wrapper = tmp_path / "claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("CARDNEWS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CARDNEWS_ENGINE", "claude-cli")
    monkeypatch.setenv("CARDNEWS_CLAUDE_BIN", str(wrapper))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_PID", str(tmp_path / "fake.pid"))
    from cardnews import db
    from cardnews.app import app

    db.init_db()
    with TestClient(app) as client:
        client.calls = lambda: [json.loads(l) for l in log.read_text().splitlines()]
        client.tmp = tmp_path
        yield client


def work():
    from cardnews import worker

    worker.run_pending()


def start(client, topic="AI 최신소식"):
    pid = client.post("/api/projects", json={"topic": topic}).json()["projectId"]
    assert client.post(f"/api/projects/{pid}/research", json={"requestId": rid()}).status_code == 202
    work()
    return pid, client.get(f"/api/projects/{pid}").json()


def to_question(client):
    pid, p = start(client)
    ids = [c["id"] for c in p["research"]["candidates"][:2]]
    v = client.post(f"/api/projects/{pid}/selection",
                    json={"candidateIds": ids, "version": p["version"]}).json()["version"]
    client.post(f"/api/projects/{pid}/deep-research", json={"version": v, "requestId": rid()})
    work()
    return pid, client.get(f"/api/projects/{pid}").json()


def arg(call, flag):
    argv = call["argv"]
    return argv[argv.index(flag) + 1] if flag in argv else None


# --- 넓은 조사 -----------------------------------------------------------------


def test_research_uses_real_engine_and_saves_session(cli):
    pid, p = start(cli)
    assert p["isMock"] is False
    assert p["engine"] == {"name": "claude-cli", "sessionId": SESSION}
    assert p["stage"] == "selecting"
    cands = p["research"]["candidates"]
    assert [c["id"] for c in cands] == [f"cand_{i}" for i in range(1, 9)]  # ID는 앱이 붙여요
    call = cli.calls()[0]
    assert arg(call, "--resume") is None  # 첫 호출은 새 세션
    assert arg(call, "--output-format") == "stream-json"
    assert arg(call, "--model") == "sonnet"
    assert arg(call, "--effort") == "medium"
    assert "--strict-mcp-config" in call["argv"]
    assert "Bash" in call["argv"][call["argv"].index("--disallowedTools") + 1:]


def test_bad_dates_and_unsafe_links_are_cleaned(cli):
    _, p = start(cli)
    first, last = p["research"]["candidates"][0], p["research"]["candidates"][-1]
    assert first["publishedAt"] is None and first["dateStatus"] == "unverified"
    assert all(s["url"].startswith("https://") for s in last["sources"])


def opened_flags(p) -> dict:
    return {s["url"]: s["opened"] for c in p["research"]["candidates"] for s in c["sources"]}


def test_sources_are_marked_opened_only_when_fetch_succeeded(cli):
    _, p = start(cli)
    flags = opened_flags(p)
    assert flags["https://news.example.com/1"] is True     # 200, www·끝 슬래시만 다름
    assert flags["https://news.example.com/2"] is False    # 403
    assert flags["https://news.example.com/4"] is False    # 열지 않음


def test_pages_opened_in_deep_research_count_too(cli):
    pid, p = to_question(cli)
    assert opened_flags(p)["https://news.example.com/3"] is True


def test_progress_shows_search_queries(cli):
    _, p = start(cli)
    messages = [e["message"] for e in p["lastRun"]["progress"]]
    assert any("AI 뉴스 이번 주" in m for m in messages)


def test_topic_is_passed_as_one_argument_not_shell(cli):
    topic = 'AI"; touch /tmp/pwned; echo "'
    start(cli, topic)
    prompt = arg(cli.calls()[0], "-p")
    assert topic in prompt
    assert not Path("/tmp/pwned").exists()


def test_each_project_has_its_own_engine_folder(cli):
    start(cli, "주제 A")
    start(cli, "주제 B")
    cwds = {c["cwd"] for c in cli.calls()}
    assert len(cwds) == 2


def test_few_results_ask_to_expand(cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "few")
    _, p = start(cli)
    assert p["currentQuestion"]["id"] == "q_expand_period"


# --- 심층 조사·질문·이어가기 ----------------------------------------------------


def test_deep_research_resumes_session_and_asks(cli):
    pid, p = to_question(cli)
    deep_call = cli.calls()[-1]
    assert arg(deep_call, "--resume") == SESSION
    prompt = arg(deep_call, "-p")
    selected = p["selection"]["candidateIds"]
    assert all(f"id={cid}" in prompt for cid in selected)
    assert p["currentQuestion"]["id"] == "q_audience"
    assert p["activeRun"]["status"] == "waiting_for_user"
    assert {n["candidateId"] for n in p["researchNotes"]} == set(selected)


def test_answer_continues_same_session_with_answer(cli):
    pid, p = to_question(cli)
    q = p["currentQuestion"]
    cli.post(f"/api/projects/{pid}/answers", json={
        "questionId": q["id"], "version": q["version"], "answer": {"optionId": "dev"},
        "requestId": rid()})
    work()
    p = cli.get(f"/api/projects/{pid}").json()
    call = cli.calls()[-1]
    assert arg(call, "--resume") == SESSION
    assert "개발자" in arg(call, "-p")
    assert p["stage"] == "storyboard_review"
    assert [c["id"] for c in p["storyboard"]["cards"]] == [f"card_{i}" for i in range(1, 6)]
    # 조사에 없던 출처 URL은 근거로 인정하지 않아요
    assert p["storyboard"]["cards"][0]["sourceUrls"] == ["https://news.example.com/1"]


# --- 실패 ----------------------------------------------------------------------


def failed(client, scenario, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", scenario)
    _, p = start(client)
    assert p["lastRun"]["status"] == "failed"
    return p["lastRun"]["error"]


def test_login_needed_is_reported(cli, monkeypatch):
    assert failed(cli, "auth", monkeypatch)["code"] == "AUTH_REQUIRED"


def test_unstructured_output_is_not_success(cli, monkeypatch):
    assert failed(cli, "bad_output", monkeypatch)["code"] == "ENGINE_OUTPUT_INVALID"


def test_missing_claude_binary(cli, monkeypatch):
    monkeypatch.setenv("CARDNEWS_CLAUDE_BIN", str(cli.tmp / "nope"))
    assert failed(cli, "ok", monkeypatch)["code"] == "TOOL_UNAVAILABLE"


def test_lost_session_asks_to_restart(cli, monkeypatch):
    pid, p = start(cli)
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "lost_session")
    ids = [p["research"]["candidates"][0]["id"]]
    v = cli.post(f"/api/projects/{pid}/selection",
                 json={"candidateIds": ids, "version": p["version"]}).json()["version"]
    cli.post(f"/api/projects/{pid}/deep-research", json={"version": v, "requestId": rid()})
    work()
    err = cli.get(f"/api/projects/{pid}").json()["lastRun"]["error"]
    assert err["code"] == "ENGINE_OUTPUT_INVALID"
    assert "처음부터" in err["message"]


def test_cancel_kills_claude_process(cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "slow")
    pid = cli.post("/api/projects", json={"topic": "취소"}).json()["projectId"]
    run_id = cli.post(f"/api/projects/{pid}/research", json={"requestId": rid()}).json()["runId"]
    thread = threading.Thread(target=work)
    thread.start()
    pid_file = cli.tmp / "fake.pid"
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    child = int(pid_file.read_text())
    assert cli.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    thread.join(timeout=10)
    assert not thread.is_alive()
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)  # 하위 claude 프로세스가 정리됐어요


def test_out_of_period_candidates_are_excluded(cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "out_of_period")
    _, p = start(cli)
    titles = [c["title"] for c in p["research"]["candidates"]]
    assert len(titles) == 8 and "후보 90" not in titles and "후보 91" not in titles
    excluded = p["research"]["excluded"]
    assert [e["title"] for e in excluded] == ["후보 90", "후보 91"]
    assert all(e["reason"] for e in excluded)
