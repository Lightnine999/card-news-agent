"""엔진 결과 거르기 규칙 (claude_schema)."""

from cardnews.engines import claude_schema as S


def out(sources: list[dict]) -> S.ResearchOutput:
    return S.ResearchOutput.model_validate({"status": "result", "candidates": [{
        "title": "t", "summary": "s", "category": "모델", "publishedAt": "2026-10-21",
        "eventDate": None, "sources": sources, "whyPick": "w", "uncertainty": "u",
        "status": "released"}]})


def src(kind: str, n: int) -> dict:
    return {"url": f"https://{kind}.example.com/{n}", "name": kind, "type": kind}


def test_sources_are_ordered_official_first():
    cands = S.to_candidates(out([src("blog", 1), src("press", 2), src("official", 3), src("paper", 4)]))
    assert [s["type"] for s in cands[0]["sources"]] == ["official", "paper", "press", "blog"]


def test_same_type_keeps_engine_order():
    cands = S.to_candidates(out([src("press", 1), src("press", 2)]))
    assert [s["url"] for s in cands[0]["sources"]] == ["https://press.example.com/1",
                                                       "https://press.example.com/2"]
