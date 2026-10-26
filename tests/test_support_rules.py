"""지원사업·공모전 규칙 (cardnews/support.py, SUPPORT_PRD 세부 규칙)."""

from datetime import date

import pytest

from cardnews import support
from cardnews.errors import AppError

TODAY = date(2026, 10, 26)
OFFICIAL = [{"url": "https://k-startup.example.go.kr/notice/1", "name": "K-Startup", "type": "official"}]


def item(cid, status="confirmed", deadline="2026-11-14", open_month=None, basis="", amount=None,
         host="gov", sources=OFFICIAL):
    return {"id": cid, "title": f"공고 {cid}", "dateStatus": status, "deadline": deadline,
            "deadlineTime": None, "openMonth": open_month, "basis": basis, "amountKRW": amount,
            "hostType": host, "sources": sources}


# --- 6개월 기간 ---------------------------------------------------------------------


@pytest.mark.parametrize("start, months, expected", [
    (date(2026, 10, 26), 6, date(2027, 4, 26)),
    (date(2026, 8, 31), 6, date(2027, 2, 28)),   # 없는 날은 그 달 마지막 날
    (date(2027, 8, 31), 6, date(2028, 2, 29)),   # 윤년
])
def test_add_months(start, months, expected):
    assert support.add_months(start, months) == expected


def test_window_is_today_to_six_months():
    assert support.window(TODAY) == (date(2026, 10, 26), date(2027, 4, 26))


# --- 거르기와 묶음 --------------------------------------------------------------------


def test_split_groups_and_excludes_with_reasons():
    cands = [
        item("a", deadline="2026-11-14"),
        item("b", status="rolling", deadline=None),
        item("c", status="expected", deadline=None, open_month="2027-03", basis="2026년 통합공고 기준"),
        item("d", deadline="2026-10-25"),                                    # 이미 마감
        item("e", deadline="2027-05-30"),                                    # 6개월 밖
        item("f", status="unverified", deadline=None),
        item("g", status="expected", deadline=None, open_month="2027-02", basis=""),  # 예정 근거 없음
        item("h", status="expected", deadline=None, open_month="2027-06", basis="작년 6월 공고"),  # 6개월 밖
        item("i", sources=[{"url": "https://linkareer.example.com/x", "name": "모음", "type": "blog"}]),
        item("j", deadline=None),                                            # 확정인데 날짜 없음
    ]
    kept, excluded = support.split(cands, TODAY)
    assert [(c["id"], c["group"]) for c in kept] == [("a", "open"), ("b", "open"), ("c", "upcoming")]
    reasons = {e["title"]: e["reason"] for e in excluded}
    assert "이미 마감" in reasons["공고 d"] and "6개월 밖" in reasons["공고 e"]
    assert "확인하지 못했" in reasons["공고 f"] and "근거" in reasons["공고 g"]
    assert "6개월 밖" in reasons["공고 h"] and "공식" in reasons["공고 i"] and "확인하지 못했" in reasons["공고 j"]


def test_deadline_today_is_kept():
    kept, _ = support.split([item("a", deadline="2026-10-26")], TODAY)
    assert kept and kept[0]["group"] == "open"


def test_order_group_then_amount_then_host_then_deadline():
    cands = [
        {**item("up", status="expected", deadline=None, open_month="2026-12", basis="b", amount=10**9), "group": "upcoming"},
        {**item("small", amount=1_000_000), "group": "open"},
        {**item("none", amount=None), "group": "open"},
        {**item("big_corp", amount=50_000_000, host="corp"), "group": "open"},
        {**item("big_gov_late", amount=50_000_000, deadline="2026-12-01"), "group": "open"},
        {**item("big_gov_soon", amount=50_000_000, deadline="2026-11-02"), "group": "open"},
        {**item("roll", status="rolling", deadline=None, amount=50_000_000), "group": "open"},
    ]
    assert [c["id"] for c in support.ordered(cands)] == [
        "big_gov_soon", "big_gov_late", "roll", "big_corp", "small", "none", "up"]


# --- D-day와 카드 문구 -----------------------------------------------------------------


def test_dday_text():
    assert support.dday_text("2026-11-14", TODAY) == "D-19"
    assert support.dday_text("2026-10-26", TODAY) == "오늘 마감"


def notice(status="confirmed", **extra):
    base = {"target": "만 39세 이하 예비 창업자", "applyVia": "K-Startup", "dateStatus": status,
            "deadline": "2026-11-14", "deadlineTime": "18:00", "openMonth": None, "basis": "",
            "rollingText": None, "amountText": "최대 1억 원", "amountKRW": 100_000_000,
            "officialUrl": OFFICIAL[0]["url"], "prepare": "사업계획서 초안"}
    return {**base, **extra}


def test_notice_body_lines_by_status():
    assert support.notice_body(notice(), TODAY) == (
        "대상: 만 39세 이하 예비 창업자\n마감: 11월 14일 18:00 (D-19 · 10/26 기준)\n신청: K-Startup")
    rolling = support.notice_body(notice("rolling", deadline=None, rollingText="예산 소진 시 마감"), TODAY)
    assert "마감: 예산 소진 시 마감" in rolling and "D-" not in rolling
    expected = support.notice_body(notice("expected", deadline=None, openMonth="2027-03",
                                          basis="2026년 통합공고 기준"), TODAY)
    assert "열림: 2027년 3월 예정(미확정)" in expected and "D-" not in expected


def card(role, cid=None, title="t"):
    return {"role": role, "title": title, "keyLine": "엔진 문장", "body": "엔진 본문 D-3",
            "imageRole": "분위기", "sourceUrls": [],
            "imagePlan": {"kind": "generated", "prompt": "p", "textArea": "top"}, "candidateId": cid}


def note(cid, **extra):
    return {"candidateId": cid, "facts": [], "limits": [], "conflicts": [], "primarySources": [],
            "unreachable": [], "claims": [], "notice": notice(**extra)}


CANDS = [{"id": f"cand_{i}", "title": f"공고 {i}", "sources": OFFICIAL, "hostType": "gov"} for i in (1, 2, 3)]


def test_finalize_orders_and_fills_cards_from_notices():
    cards = [card("cover"), card("body", "cand_1", "작은 공고"), card("body", "cand_2", "큰 공고"),
             card("summary")]
    notes = [note("cand_1", amountKRW=1_000_000, amountText="상금 100만 원"),
             note("cand_2", amountKRW=50_000_000, amountText="총상금 5천만 원")]
    out, dropped = support.finalize_cards(cards, notes, CANDS[:2], TODAY)
    assert [c["role"] for c in out] == ["cover", "body", "body", "summary"]
    assert [c.get("candidateId") for c in out[1:3]] == ["cand_2", "cand_1"]
    assert [c["order"] for c in out] == [1, 2, 3, 4] and [c["id"] for c in out] == ["card_1", "card_2", "card_3", "card_4"]
    assert out[1]["keyLine"] == "총상금 5천만 원" and "D-19" in out[1]["body"] and out[1]["notice"]["deadline"]
    assert out[1]["sourceUrls"] == [OFFICIAL[0]["url"]]
    assert out[3]["keyLine"] == "지금 지원 가능 2 · 곧 열릴 예정 0" and "D-" not in out[3]["body"]
    assert dropped == []


def test_finalize_drops_notices_that_failed_deep_check():
    cards = [card("cover"), card("body", "cand_1"), card("body", "cand_2"), card("body", "cand_3"), card("summary")]
    notes = [note("cand_1"), note("cand_2", deadline="2026-10-20"), note("cand_3", dateStatus="unverified", deadline=None)]
    out, dropped = support.finalize_cards(cards, notes, CANDS, TODAY)
    assert [c.get("candidateId") for c in out if c["role"] == "body"] == ["cand_1"]
    assert {d["candidateId"] for d in dropped} == {"cand_2", "cand_3"}


def test_finalize_unknown_amount_says_check_needed():
    out, _ = support.finalize_cards([card("cover"), card("body", "cand_1"), card("summary")],
                                    [note("cand_1", amountText="", amountKRW=None)], CANDS, TODAY)
    assert out[1]["keyLine"] == "금액 확인 필요"


def test_finalize_without_any_notice_card_fails():
    with pytest.raises(AppError) as err:
        support.finalize_cards([card("cover"), card("body", "cand_1"), card("summary")],
                               [note("cand_1", deadline="2026-01-01")], CANDS, TODAY)
    assert err.value.code == "ENGINE_OUTPUT_INVALID"


def test_single_notice_summary_has_deadline_and_preparation():
    out, _ = support.finalize_cards([card("cover"), card("body", "cand_1"), card("summary")],
                                    [note("cand_1")], CANDS, TODAY)
    assert "11월 14일" in out[2]["body"] and "사업계획서 초안" in out[2]["body"]


def test_summary_shortens_long_names_with_ellipsis():
    long = "2026년 예비창업패키지 일반분야 예비창업자 모집"
    _, body = support.summary_texts([(long, notice()), ("짧은 공모전", notice(deadline="2026-11-20"))])
    assert "…" in body and long not in body and "짧은 공모전" in body


# --- 검토에서 나온 경우들 ------------------------------------------------------------


def test_past_deadline_is_not_negative_dday():
    assert support.dday_text("2026-10-20", TODAY) == "마감 지남"


def test_refresh_body_rewrites_stale_deadline_line():
    stale = "대상: 대학생만\n마감: 11월 14일 18:00 (D-19 · 10/26 기준) (모의 수정)\n신청: K-Startup"
    fresh = support.refresh_body(stale, notice(), date(2026, 10, 28))
    assert fresh.split("\n") == ["대상: 대학생만", "마감: 11월 14일 18:00 (D-17 · 10/28 기준)", "신청: K-Startup"]
    no_line = support.refresh_body("대상과 신청을 한 문장으로 바꾼 본문", notice(), TODAY)
    assert "D-19 · 10/26 기준" in no_line.split("\n")[1]  # 마감 줄이 없어졌으면 다시 넣어요


def test_finalize_records_selected_notice_without_card():
    cards = [card("cover"), card("body", "cand_1"), card("summary")]
    _, dropped = support.finalize_cards(cards, [note("cand_1"), note("cand_2")], CANDS[:2], TODAY)
    assert [(d["candidateId"], "카드를 만들지" in d["reason"]) for d in dropped] == [("cand_2", True)]


def test_finalize_ignores_non_official_official_url():
    blog = "https://linkareer.example.com/x"
    cands = [{**CANDS[0], "sources": [*OFFICIAL, {"url": blog, "name": "모음", "type": "blog"}]}]
    out, _ = support.finalize_cards([card("cover"), card("body", "cand_1"), card("summary")],
                                    [note("cand_1", officialUrl=blog)], cands, TODAY)
    assert out[1]["sourceUrls"] == [OFFICIAL[0]["url"]] and out[1]["notice"]["officialUrl"] is None
