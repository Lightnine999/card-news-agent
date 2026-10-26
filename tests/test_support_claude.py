"""지원사업·공모전 작업의 Claude CLI 경로를 가짜 claude로 확인해요 (실제 호출 없음)."""

from tests.conftest import rid
from tests.test_claude_engine import cli, work  # noqa: F401  (cli는 fixture)


def start(client, topic="IT·AI 창업 지원사업"):
    pid = client.post("/api/projects", json={"topic": topic, "workflow": "support"}).json()["projectId"]
    assert client.post(f"/api/projects/{pid}/research", json={"requestId": rid()}).status_code == 202
    work()
    return pid, client.get(f"/api/projects/{pid}").json()


def test_support_research_prompt_and_schema(cli):
    pid, p = start(cli)
    call = cli.calls()[0]["argv"]
    prompt = call[call.index("-p") + 1]
    assert "오늘부터 6개월" in prompt and "공식 공고문" in prompt and "대학생" in prompt
    assert '"title": "SupportResearchOutput"' in call[call.index("--json-schema") + 1]
    assert "WebFetch" in call[call.index("--allowedTools") + 1:]
    r = p["research"]
    titles = {c["title"] for c in r["candidates"]}
    assert "모음 사이트에만 있는 공고" not in titles  # 공식 링크가 없으면 후보로 보여 주지 않아요
    assert any("공식" in e["reason"] for e in r["excluded"])


def test_support_deep_research_builds_cards(cli):
    pid, p = start(cli)
    ids = [c["id"] for c in p["research"]["candidates"][:3]]
    v = cli.post(f"/api/projects/{pid}/selection", json={"candidateIds": ids, "version": p["version"]}).json()["version"]
    cli.post(f"/api/projects/{pid}/deep-research", json={"version": v, "requestId": rid()})
    work()
    p = cli.get(f"/api/projects/{pid}").json()
    assert p["stage"] == "storyboard_review", p["lastRun"]
    call = cli.calls()[-1]["argv"]
    assert '"title": "SupportDeepOutput"' in call[call.index("--json-schema") + 1]
    cards = p["storyboard"]["cards"]
    assert [c["role"] for c in cards][0] == "cover" and cards[-1]["role"] == "summary"
    assert sum(1 for c in cards if c.get("notice")) == 3
    assert all("엔진이 쓴 D-1" not in c["body"] for c in cards if c.get("notice"))


def test_news_research_still_uses_news_schema(cli):
    pid = cli.post("/api/projects", json={"topic": "AI 최신소식"}).json()["projectId"]
    cli.post(f"/api/projects/{pid}/research", json={"requestId": rid()})
    work()
    call = cli.calls()[0]["argv"]
    assert '"title": "ResearchOutput"' in call[call.index("--json-schema") + 1]
