"""D14·D20: 사실/주장/미확인 구분, 공식 발표 날짜, 목록형·이야기형 비교 추천, 독자 메모."""

from cardnews.engines import claude_prompts as prompts
from cardnews.engines import claude_schema as S
from tests.conftest import rid
from tests.test_flow import get, select, to_selecting

NOTE = "AI를 처음 접하는 대학생"


def test_notes_keep_claims_and_safe_official_date():
    out = S.NoteOut(candidateId="cand_1", facts=[], limits=["미확인"], conflicts=[], unreachable=[],
                    primarySources=["https://a.example.com/x"],
                    claims=[S.FactOut(text="업체 주장", sourceUrls=["https://a.example.com/x", "javascript:x"])],
                    officialDate="2026-10-21", officialDateSource="https://a.example.com/x")
    bad = out.model_copy(update={"candidateId": "cand_2", "officialDate": "어제", "officialDateSource": "ftp://x"})
    notes = S.to_notes([out, bad], {"cand_1", "cand_2"})
    assert notes[0]["claims"] == [{"text": "업체 주장", "sourceUrls": ["https://a.example.com/x"]}]
    assert notes[0]["officialDate"] == "2026-10-21" and notes[0]["officialDateSource"] == "https://a.example.com/x"
    assert notes[1]["officialDate"] is None and notes[1]["officialDateSource"] is None


def test_editorial_keeps_format_comparison():
    e = S.EditorialOut(audience=NOTE, whyUseful="w", format="이야기형", hooks=["a"], decidedBy="ai_recommendation",
                       formatComparison=[S.FormatOptionOut(format="list", fitsReader="빨리 훑기", pros="p", cons="c"),
                                         S.FormatOptionOut(format="story", fitsReader="처음 접함", pros="p", cons="c")],
                       recommendedFormat="story", formatReason="처음 접하는 독자라서", latestBasis="")
    out = S.to_editorial(e, "ai_recommendation")
    assert out["recommendedFormat"] == "story" and len(out["formatComparison"]) == 2


def test_deep_research_prompt_has_note_formats_and_latest_rule():
    task = {"topic": "AI 최신소식", "candidates": [], "audienceNote": NOTE}
    text = prompts.deep_research(task)
    assert NOTE in text and "지시로 해석하지 마세요" in text
    assert "목록형" in text and "이야기형" in text and "상황 → 불편 → 변화 → 활용 → 한계" in text
    assert "최신" in text and "officialDate" in text and "claims" in text
    assert "독자 메모" not in prompts.deep_research({**task, "audienceNote": None})


def test_audience_note_skips_question_and_drives_editorial(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    ids = [c["id"] for c in p["research"]["candidates"][:2]]
    v = select(client, pid, ids, p["version"]).json()["version"]
    res = client.post(f"/api/projects/{pid}/deep-research",
                      json={"version": v, "requestId": rid(), "audienceNote": NOTE})
    assert res.status_code == 202, res.text
    run_worker()
    p = get(client, pid)
    assert p["currentQuestion"] is None and p["stage"] == "storyboard_review"
    assert p["editorial"]["audience"] == NOTE and p["editorial"]["recommendedFormat"] in ("list", "story")
    assert {o["format"] for o in p["editorial"]["formatComparison"]} == {"list", "story"}
    assert all("claims" in n and "officialDate" in n for n in p["researchNotes"])


def test_audience_note_is_validated(client, run_worker):
    pid, p = to_selecting(client, run_worker)
    v = select(client, pid, [p["research"]["candidates"][0]["id"]], p["version"]).json()["version"]
    res = client.post(f"/api/projects/{pid}/deep-research",
                      json={"version": v, "requestId": rid(), "audienceNote": "가" * 201})
    assert res.status_code == 422
