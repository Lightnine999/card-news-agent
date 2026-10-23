"""엔진이 실제로 연 URL 모으기·맞추기 (cardnews/sources.py)."""

from cardnews import sources


def use(tid: str, url: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "WebFetch", "input": {"url": url}}]}}


def result(tid: str, code: int | None, final: str | None = None) -> dict:
    event = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "..."}]}}
    if code is not None:
        event["tool_use_result"] = {"code": code, "url": final}
    return event


def collect(events: list[dict]) -> set[str]:
    tracker = sources.FetchTracker()
    for e in events:
        tracker.feed(e)
    return tracker.opened


def test_only_successful_fetches_count():
    opened = collect([
        use("a", "https://ok.example.com/a"), result("a", 200),
        use("b", "https://blocked.example.com/b"), result("b", 403),
        use("c", "https://never.example.com/c"),            # 결과가 오지 않음
        use("d", "https://nocode.example.com/d"), result("d", None),
    ])
    assert opened == {"https://ok.example.com/a"}


def test_redirect_final_url_also_counts():
    opened = collect([use("a", "https://a.example.com/old"), result("a", 200, "https://a.example.com/new")])
    assert opened == {"https://a.example.com/old", "https://a.example.com/new"}


def test_web_search_is_not_opening():
    event = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "s", "name": "WebSearch", "input": {"query": "x"}}]}}
    assert collect([event, result("s", 200)]) == set()


def test_normalize_ignores_www_trailing_slash_fragment_and_case():
    same = ["https://www.Example.com/news/", "https://example.com/news#top", "HTTPS://example.com/news"]
    assert len({sources.normalize(u) for u in same}) == 1
    assert sources.normalize("https://example.com/news?id=1") != sources.normalize("https://example.com/news?id=2")


def test_mark_sources():
    cands = [{"id": "cand_1", "sources": [
        {"url": "https://www.example.com/a/", "type": "official"},
        {"url": "https://example.com/b", "type": "official"}]}]
    marked = sources.mark(cands, ["https://example.com/a"])
    assert [s["opened"] for s in marked[0]["sources"]] == [True, False]
    assert "opened" not in cands[0]["sources"][0]  # 원본은 바꾸지 않아요
