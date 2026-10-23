"""조사 기간 밖 후보 빼기 (cardnews/period.py)."""

from cardnews import period

RESEARCH = {"requestedAt": "2026-10-23T12:58:00+09:00",
            "period": {"days": 7, "from": "2026-10-16T12:58:00+09:00", "to": "2026-10-23T12:58:00+09:00"}}


def cand(cid: str, published: str | None) -> dict:
    return {"id": cid, "title": f"후보 {cid}", "publishedAt": published,
            "sources": [{"url": f"https://example.com/{cid}", "name": "출처", "type": "press"}]}


def test_boundaries_are_inclusive_by_date():
    kept, excluded = period.split([cand("a", "2026-10-16"), cand("b", "2026-10-23")], RESEARCH)
    assert [c["id"] for c in kept] == ["a", "b"] and excluded == []


def test_before_and_after_period_are_excluded_with_reason():
    kept, excluded = period.split([cand("old", "2026-10-15"), cand("new", "2026-10-24"),
                                   cand("ok", "2026-10-20")], RESEARCH)
    assert [c["id"] for c in kept] == ["ok"]
    assert [(e["title"], e["publishedAt"]) for e in excluded] == [("후보 old", "2026-10-15"),
                                                                 ("후보 new", "2026-10-24")]
    assert "앞서요" in excluded[0]["reason"] and "10-16" in excluded[0]["reason"]
    assert "뒤예요" in excluded[1]["reason"]
    assert excluded[0]["url"] == "https://example.com/old"


def test_unknown_date_is_kept():
    kept, excluded = period.split([cand("x", None)], RESEARCH)
    assert [c["id"] for c in kept] == ["x"] and excluded == []


def test_thirty_day_period():
    research = {**RESEARCH, "period": {**RESEARCH["period"], "days": 30,
                                       "from": "2026-09-23T12:58:00+09:00"}}
    kept, _ = period.split([cand("a", "2026-09-23"), cand("b", "2026-09-22")], research)
    assert [c["id"] for c in kept] == ["a"]
