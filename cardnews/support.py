"""지원사업·공모전 마감 카드뉴스 규칙 (SUPPORT_PRD.md 세부 규칙).

날짜를 거르고, 묶음·순서를 정하고, D-day와 카드 문구를 앱이 만들어요. 엔진이 적은 D-day는 쓰지 않아요.
- 날짜 상태: confirmed(공식 공고문 확인) / rolling(상시·소진 시) / expected(예정) / unverified(확인 못 함)
- 묶음: open(지금 지원 가능 = confirmed·rolling) / upcoming(곧 열릴 예정 = expected)
"""

import calendar
from datetime import date

from cardnews.errors import AppError

MONTHS = 6
MAX_SELECTION = 7
EXPAND_THRESHOLD = 3  # 거르고 남은 후보가 이보다 적으면 범위를 넓힐지 물어요
CARD_RANGE = (3, 9)   # 표지 1 + 공고 1~7 + 요약 1
HOST_RANK = {"gov": 0, "corp": 1, "univ": 2, "other": 3}
GROUP_RANK = {"open": 0, "upcoming": 1}
GROUP_LABEL = {"open": "지금 지원 가능", "upcoming": "곧 열릴 예정"}
NAME_MAX = 20  # 요약 카드에 적을 공고 이름 길이 (넘치면 …로 줄여요)


def add_months(day: date, months: int) -> date:
    """몇 달 뒤 같은 날. 그 달에 없는 날이면 그 달 마지막 날이에요(8/31 + 6개월 = 2/28)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def window(today: date) -> tuple[date, date]:
    return today, add_months(today, MONTHS)


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-")[:2]
    return int(year), int(month)


def _has_official(item: dict) -> bool:
    return any(s.get("type") == "official" for s in item.get("sources", []))


def exclusion_reason(item: dict, today: date) -> str | None:
    """뺄 이유. 남기면 None. item은 후보(넓은 조사) 또는 공고 확인 결과(심층 확인)예요."""
    start, end = window(today)
    status = item.get("dateStatus")
    if "sources" in item and not _has_official(item):
        return "주최 측 공식 공고 링크가 없어요(모음 사이트에만 있어요)."
    if status == "rolling":
        return None
    if status == "confirmed":
        if not item.get("deadline"):
            return "마감일을 공식 페이지에서 확인하지 못했어요."
        deadline = date.fromisoformat(item["deadline"])
        if deadline < start:
            return f"이미 마감됐어요(마감 {item['deadline']})."
        if deadline > end:
            return f"마감({item['deadline']})이 오늘부터 6개월 밖이에요."
        return None
    if status == "expected":
        if not item.get("openMonth") or not (item.get("basis") or "").strip():
            return "열릴 시기를 뒷받침할 공식 근거가 없어요."
        opens = _month(item["openMonth"])
        if opens < (start.year, start.month):
            return f"예정 달({item['openMonth']})이 이미 지났는데 공고를 확인하지 못했어요."
        if opens > (end.year, end.month):
            return f"열릴 예정({item['openMonth']})이 오늘부터 6개월 밖이에요."
        return None
    return "마감·열림 날짜를 공식 페이지에서 확인하지 못했어요."


def group_of(item: dict) -> str:
    return "upcoming" if item.get("dateStatus") == "expected" else "open"


def split(candidates: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """(남긴 후보 — 묶음을 붙이고 정렬함, 뺀 후보 기록)."""
    kept, excluded = [], []
    for cand in candidates:
        reason = exclusion_reason(cand, today)
        if reason is None:
            kept.append({**cand, "group": group_of(cand)})
            continue
        url = cand["sources"][0]["url"] if cand.get("sources") else None
        excluded.append({"title": cand["title"], "url": url, "reason": reason})
    return ordered(kept), excluded


def _when(item: dict) -> tuple:
    """마감 임박 순서: 확정 마감일 → 상시(맨 뒤). 예정은 열릴 달 순서."""
    if item.get("dateStatus") == "confirmed" and item.get("deadline"):
        return (0, item["deadline"])
    if item.get("dateStatus") == "expected" and item.get("openMonth"):
        return (0, item["openMonth"])
    return (1, "")


def sort_key(item: dict) -> tuple:
    amount = item.get("amountKRW")
    return (GROUP_RANK[item.get("group") or group_of(item)],
            0 if amount else 1, -(amount or 0),   # 금액을 모르면 금액 순위에 넣지 않고 뒤로
            HOST_RANK.get(item.get("hostType"), 3), _when(item))


def ordered(items: list[dict]) -> list[dict]:
    return sorted(items, key=sort_key)


# --- D-day와 카드 문구 ----------------------------------------------------------------


def dday_text(deadline: str, today: date) -> str:
    days = (date.fromisoformat(deadline) - today).days
    if days < 0:
        return "마감 지남"
    return "오늘 마감" if days == 0 else f"D-{days}"


def _md(iso: str) -> str:
    day = date.fromisoformat(iso)
    return f"{day.month}월 {day.day}일"


def deadline_line(notice: dict, today: date) -> str:
    status = notice.get("dateStatus")
    if status == "expected":
        year, month = _month(notice["openMonth"])
        return f"열림: {year}년 {month}월 예정(미확정)"
    if status == "rolling":
        return f"마감: {notice.get('rollingText') or '상시 모집'}"
    time = f" {notice['deadlineTime']}" if notice.get("deadlineTime") else ""
    return (f"마감: {_md(notice['deadline'])}{time} "
            f"({dday_text(notice['deadline'], today)} · {today.month}/{today.day} 기준)")


def notice_body(notice: dict, today: date) -> str:
    return f"대상: {notice['target']}\n{deadline_line(notice, today)}\n신청: {notice['applyVia']}"


def refresh_body(body: str, notice: dict, today: date) -> str:
    """고친 본문이라도 마감·열림 줄은 앱이 오늘 기준으로 다시 써요. 그 줄이 없어졌으면 두 번째 줄에 다시 넣어요."""
    lines = [line for line in (body or "").split("\n") if line.strip()]
    fresh = deadline_line(notice, today)
    index = next((i for i, line in enumerate(lines) if line.startswith(("마감:", "열림:"))), None)
    if index is None:
        return "\n".join([*lines[:1], fresh, *lines[1:]])
    return "\n".join([*lines[:index], fresh, *lines[index + 1:]])


def official_urls(candidates: list[dict], notes: list[dict]) -> set[str]:
    """공식 근거로 인정하는 주소: 후보의 official 출처 + 심층 확인에서 실제로 연 1차 자료."""
    urls = {s["url"] for c in candidates for s in c.get("sources", []) if s.get("type") == "official"}
    return urls | {u for n in notes for u in n.get("primarySources", [])}


def _short_when(notice: dict) -> str:
    if notice.get("dateStatus") == "expected":
        return f"{_month(notice['openMonth'])[1]}월 예정"
    if notice.get("dateStatus") == "rolling":
        return "상시"
    day = date.fromisoformat(notice["deadline"])
    return f"{day.month}/{day.day} 마감"


def _name(name: str) -> str:
    return name if len(name) <= NAME_MAX else name[:NAME_MAX - 1] + "…"


def summary_texts(entries: list[tuple[str, dict]]) -> tuple[str, str]:
    """요약 카드 (핵심 문장, 본문). entries = [(공고 이름, 확인 결과)]. D-day는 쓰지 않아요."""
    groups = [group_of(n) for _, n in entries]
    key_line = f"지금 지원 가능 {groups.count('open')} · 곧 열릴 예정 {groups.count('upcoming')}"
    if len(entries) == 1:
        name, notice = entries[0]
        prepare = notice.get("prepare") or "공고문의 제출 서류"
        when = _md(notice["deadline"]) + " 마감" if notice.get("dateStatus") == "confirmed" else _short_when(notice)
        return key_line, f"{_name(name)}: {when}\n미리 준비: {prepare}"
    by_deadline = sorted(entries, key=lambda e: (GROUP_RANK[group_of(e[1])], _when(e[1])))
    return key_line, "\n".join(f"{_short_when(n)} · {_name(name)}" for name, n in by_deadline)


def _official_url(notice: dict, cand: dict) -> list[str]:
    if notice.get("officialUrl"):
        return [notice["officialUrl"]]
    return [s["url"] for s in cand.get("sources", []) if s.get("type") == "official"][:1]


def finalize_cards(cards: list[dict], notes: list[dict], candidates: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """엔진이 낸 카드를 앱 규칙으로 정리해요: 확인 결과로 거른 공고만, 정한 순서로, 문구는 확인 결과로.

    돌려주는 것: (카드, 심층 확인에서 빠진 공고 기록)
    """
    official = official_urls(candidates, notes)
    # 공식 공고문 주소는 조사에 나온 공식 주소일 때만 인정해요(모음 사이트·새 주소는 버려요)
    notices = {n["candidateId"]: {**n["notice"], "officialUrl": n["notice"].get("officialUrl")
                                  if n["notice"].get("officialUrl") in official else None}
               for n in notes if n.get("notice")}
    cands = {c["id"]: c for c in candidates}
    dropped, bodies = [], []
    for card in cards:
        cid = card.get("candidateId")
        if card["role"] in ("cover", "summary") or not cid or cid not in cands:
            continue
        notice = notices.get(cid)
        reason = "심층 확인 결과가 없어요." if notice is None else exclusion_reason(notice, today)
        if reason:
            dropped.append({"candidateId": cid, "title": cands[cid]["title"], "reason": reason})
            continue
        bodies.append({**card, "keyLine": notice.get("amountText") or "금액 확인 필요",
                       "body": notice_body(notice, today), "notice": notice,
                       "sourceUrls": _official_url(notice, cands[cid]),
                       "group": group_of(notice), "amountKRW": notice.get("amountKRW"),
                       "hostType": cands[cid].get("hostType"), "dateStatus": notice.get("dateStatus"),
                       "deadline": notice.get("deadline"), "openMonth": notice.get("openMonth")})
    carded = {c.get("candidateId") for c in cards}
    dropped += [{"candidateId": cid, "title": c["title"], "reason": "엔진이 이 공고의 카드를 만들지 않았어요."}
                for cid, c in cands.items() if cid not in carded]
    if not bodies:
        raise AppError("ENGINE_OUTPUT_INVALID", "공식 공고문으로 다시 확인해 보니 카드로 만들 공고가 남지 않았어요.",
                       {"dropped": [d["reason"] for d in dropped]})
    seen, unique = set(), []
    for card in ordered(bodies):  # 같은 공고 카드가 두 장이면 하나만 써요
        if card["candidateId"] not in seen:
            seen.add(card["candidateId"])
            unique.append(card)
    cover = next((c for c in cards if c["role"] == "cover"), None)
    summary = next((c for c in cards if c["role"] == "summary"), None)
    if cover is None or summary is None:
        raise AppError("ENGINE_OUTPUT_INVALID", "표지와 요약 카드가 있어야 해요.")
    key_line, body = summary_texts([(c["title"], c["notice"]) for c in unique])
    summary = {**summary, "keyLine": key_line, "body": body,
               "sourceUrls": list(dict.fromkeys(u for c in unique for u in c["sourceUrls"]))}
    extra = ("group", "amountKRW", "hostType", "dateStatus", "deadline", "openMonth")
    final = [cover, *[{k: v for k, v in c.items() if k not in extra} for c in unique], summary]
    low, high = CARD_RANGE
    if not low <= len(final) <= high:
        raise AppError("ENGINE_OUTPUT_INVALID", f"카드가 {len(final)}장이에요. {low}~{high}장이어야 해요.")
    return [{**c, "id": f"card_{i}", "order": i} for i, c in enumerate(final, 1)], dropped
