"""조사 기간 밖 후보 빼기 (DECISIONS D13).

엔진에게 기간 안 소식만 넣으라고 지시하지만 지키지 않을 때가 있어서 앱이 한 번 더 걸러요.
- 비교 대상은 게시일(publishedAt)이고, 날짜 단위로 시작일·끝날을 모두 포함해요.
- 게시일을 모르면 판단할 수 없어서 남겨요(화면에는 "날짜 미확인").
"""

from datetime import date, datetime


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso).date()


def _short(day: date) -> str:
    return day.strftime("%m-%d")


def _reason(published: date, start: date, end: date) -> str | None:
    window = f"조사 기간({_short(start)}~{_short(end)})"
    # 숫자 뒤 조사(이/가)는 읽는 법에 따라 달라서, 괄호로 감싸 "게시일이"로 읽히게 해요
    if published < start:
        return f"게시일({published.isoformat()})이 {window}보다 앞서요."
    if published > end:
        return f"게시일({published.isoformat()})이 {window}보다 뒤예요."
    return None


def split(candidates: list[dict], research: dict) -> tuple[list[dict], list[dict]]:
    """(남길 후보, 뺀 후보 기록)을 돌려줘요. 뺀 기록은 화면에 보여 줄 만큼만 남겨요."""
    start, end = _day(research["period"]["from"]), _day(research["requestedAt"])
    kept, excluded = [], []
    for cand in candidates:
        reason = _reason(date.fromisoformat(cand["publishedAt"]), start, end) \
            if cand.get("publishedAt") else None
        if reason is None:
            kept.append(cand)
            continue
        excluded.append({"title": cand["title"], "publishedAt": cand["publishedAt"],
                         "url": cand["sources"][0]["url"] if cand["sources"] else None,
                         "reason": reason})
    return kept, excluded
